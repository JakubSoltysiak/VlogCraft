"""Repeat the bounded three-layer native recorder campaign with a frozen MSI and a diagnostic worker."""

import argparse
from contextlib import contextmanager
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import time

import psutil

ROOT = Path(__file__).resolve().parents[1]
HOST = Path("Programs/VlogCraft Studio/VlogCraftStudio.exe")
WORKER = Path("_internal/engine/native/VlogCraftNative.exe")
IMAGE = "campaign-image.private.json"
CAPTURE_KEY = "VLOGCRAFT_STALL_CAPTURE"
COMPLETION_KEY = "VLOGCRAFT_COMPLETION_TRACE"
REFILL_KEY = "VLOGCRAFT_DIAGNOSTIC_NO_REFILL_HOLD"
LEGACY_REFILL_KEY = "VLOGCRAFT_DIAGNOSTIC_LEGACY_REFILL_HOLD"
LEGACY_POLL_KEY = "VLOGCRAFT_DIAGNOSTIC_LEGACY_POLL_ORDER"
DIAGNOSTIC_KEYS = (REFILL_KEY, LEGACY_REFILL_KEY, LEGACY_POLL_KEY)
WORKER_OVERRIDE_KEY = "VLOGCRAFT_NATIVE_BINARY"
PICTURE_HANDOFF_KEY = "VLOGCRAFT_EXPERIMENTAL_PICTURE_HANDOFF"
CONTROLLED_ENV_KEYS = (CAPTURE_KEY, COMPLETION_KEY, "VLOGCRAFT_NATIVE_TRACE_FILE", "VLOGCRAFT_HANDOFF_TRACE_FILE", WORKER_OVERRIDE_KEY,
                       *DIAGNOSTIC_KEYS, PICTURE_HANDOFF_KEY)
REFILL_IMAGE = "refill-image.private.json"
EDITOR_PREVIEW = [958, 539]
PROTECTED_FIXTURE_SHA256 = [
    "b9afde2760e3fdbcc551d0f15563e3cd2f88f5ea96d5484d91b39c7bfb5a8b8c",
    "135a23fe7a9160719d52c0048b0da5c5023dddef1f965b3a9f79db34c8361d9f",
    "9e5eb133025e13f751ff7094868d6cfca64611c7d6f65569c4f9c6de0fead75a",
]
REFILL_ORDER = (("A", "B"), ("B", "A"))
BOUNDED_POLL_ORDER = (("C", "D"), ("D", "C"))
ORDINARY_ORDER = (("R", "F"), ("F", "R"))
PAIR_STOPPING_RULES = {
    "refill": "Review pair one before pair two. Stop after the two declared pairs, or if controls fail. Retain all attempts.",
    "bounded poll": "Review pair one before pair two. Use the reverse pair only for a promising or ambiguous result. "
                    "Stop if controls fail or both arms exhibit the same post-expiry starvation. Retain every attempt.",
    "ordinary": "Review the initial recorder-off comparison. Reverse only if the candidate meets the short timing screens. "
                 "Retain every attempt.",
}
BASELINES = {
    "cand1": {
        "msi_sha256": "4d82887f41389b458278056970e12a49319850b0fb13df281c1f36fe947e9bd4",
        "host_sha256": "cb09208757e396e6a808d9f9bb88312817154a3e373eb34d40a430ac315eaf93",
        "worker_sha256": "1717545bd55170d5299b524fd4a94bd12cb1564e6c31ff3f7cd3a9ab313746e0",
        "head_at_build": "893dc6e23af419a69591bdbe5386f0db3f97cceb",
    },
    "cand3": {
        "msi_sha256": "2f9de210fe88a2e4903e679bb61e081201973b073f20bba2bce3cf14bc0b8266",
        "host_sha256": "23e85f11a30e6f885f00220aa9966fbf6545389b9c61d0ef4f22e49d6cfca490",
        "worker_sha256": "2251ac360af922971b0fbcde1a08eb2b4693e7f994e8bf77bf44d1897c0f36a6",
        "head_at_build": "7086ed380d279855b2d81f87d4d2105e268b6335",
        "native_build_inputs_sha256": "2b64013979934da70095dca25a0e6a9fdafa5c68b87a24d6b71bcc14d8e6f11d",
    },
    "cand4": {
        "msi_sha256": "8047cde8308fe394abc2fa2c6543d6c02f8b5dd2dc6ed7accfdb34e76daa0cf5",
        "host_sha256": "fd0fcbca279f3ce20e1bcd5d33e212e1cba88b2025c806003b39b9e9922ce4ed",
        "worker_sha256": "152866b9a0ba6d9b4722e7e567ad1299d8a10a2cba6cd7b3160117c1178452f3",
        "head_at_build": "b42e37630810e880a38dda2b111168b9bd5d11f9",
        "native_build_inputs_sha256": "9e6bf0b5004e074e02cfca62aa154e2c5d251b4eb646ba87e1c8586d62d7df99",
    },
    "b817372": {
        "msi_sha256": "4513cef410ffe7d2fe775b0b1eec8dc86732f82dcbe9cf5d7ae30d055dd76fa0",
        "host_sha256": "e6330cc74de309c658feba9beaa58847782b30226f861836a94401ab2bbdfa90",
        "worker_sha256": "0138b285593a55aa5ac57c3448ee23e2b4c61be0dd6d80af9bf7d1014f7dcc49",
    },
}
PUBLISHED = {
    "cand1": "28c0abf221c87e1b7c673a36abe70fac594cdc27",
    "cand3": "59008494539a3a622ebc92f85fd072c39f527dcc",
    "cand4": "d11445a467e10a8757a672256d7975977d47522a",
}
MAX_ON = 3


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path, data):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2)
        stream.write("\n")


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


@contextmanager
def serial():
    # Use one campaign at a time on the same Windows workstation, including
    # campaigns started in other checkouts. This lock does not target processes.
    import msvcrt

    with (Path(tempfile.gettempdir()) / "vlogcraft-phase3b-stall.lock").open("a+b") as lock:
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as err:
            raise RuntimeError("A Phase 3B recorder command is already running") from err
        yield


def media_hashes(media):
    return [digest(media / f"h264-4k60-{i}.mp4") for i in range(3)]


def media_stats(media):
    stats = [(media / f"h264-4k60-{i}.mp4").stat() for i in range(3)]
    return [[row.st_size, row.st_mtime_ns] for row in stats]


def verify(exe, host_sha, worker_sha):
    if digest(exe) != host_sha or digest(exe.parent / WORKER) != worker_sha:
        raise ValueError("Host or native playback worker differs from the campaign receipt")


def verify_package(label, msi, exe):
    identity = BASELINES[label]
    if digest(msi) != identity["msi_sha256"]:
        raise ValueError(f"The frozen MSI must match the published {label} artifact")
    verify(exe, identity["host_sha256"], identity["worker_sha256"])


def extract(msi, layout, log):
    subprocess.run(["msiexec.exe", "/a", str(msi), "/qn", "TARGETDIR=" + str(layout),
                    "/L*v", str(log)], check=True, cwd=ROOT)


def image_workspace():
    return Path(tempfile.mkdtemp(prefix="vc3b-", dir=Path(os.environ["LOCALAPPDATA"]) / "Temp"))


def native_build_digest():
    files = [ROOT / "tools/setup_architecture_lab.py"]
    for folder in ("native", "experiments/native_d3d11", "experiments/render_phase2"):
        files.extend(path for path in (ROOT / folder).rglob("*") if path.suffix in (".cpp", ".h"))
    source = hashlib.sha256()
    for path in sorted(files):
        source.update(path.relative_to(ROOT).as_posix().encode() + b"\0")
        source.update(path.read_bytes().replace(b"\r\n", b"\n") + b"\0")
    return source.hexdigest()


def build_refill_worker(results):
    sys.path.insert(0, str(ROOT))
    from tools.setup_architecture_lab import SPECS

    toolchain = ROOT / "build/tools/architecture"
    zig = toolchain / "zig/zig-x86_64-windows-0.17.1/zig.exe"
    sdk = toolchain / "ffmpeg-shared/ffmpeg-9.0.2-full_build-shared"
    archives = {component: read(toolchain / component / "qualified-archive.json")["sha256"]
                for component in ("zig", "ffmpeg-shared")}
    if any(sha != SPECS[component][1] for component, sha in archives.items()):
        raise ValueError("The native compiler and SDK must match the pinned lab toolchain")
    results.mkdir(parents=True)
    executable = results / "VlogCraftNative.exe"
    source = native_build_digest()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    subprocess.run([
        sys.executable, "benchmarks/run_qa.py", "--results", str(results / "build-diagnostic-supervisor"),
        "--status", str(results / "build-diagnostic-status.json"), "--timeout", "1200", "--",
        str(zig), "c++", "-std=c++17", "-O2", "-target", "x86_64-windows-gnu",
        str(ROOT / "native/player.cpp"), "-I" + str(sdk / "include"), "-L" + str(sdk / "lib"),
        "-lavformat", "-lavcodec", "-lavutil", "-lswscale", "-ld3d11", "-ldxgi", "-o", str(executable),
    ], check=True, cwd=ROOT)
    if source != native_build_digest():
        raise ValueError("Native inputs changed during compilation")
    with executable.open("rb") as stream:
        if stream.read(2) != b"MZ":
            raise ValueError("The diagnostic worker is missing its PE header")
        stream.seek(0x3c)
        stream.seek(struct.unpack("<I", stream.read(4))[0])
        if stream.read(6) != b"PE\0\0\x64\x86":
            raise ValueError("The diagnostic worker is not AMD64")
    save(results / "build-diagnostic.json", {
        "head_at_build": head, "native_build_inputs_sha256": source, "toolchain_archive_sha256": archives,
        "worker": {"bytes": executable.stat().st_size, "sha256": digest(executable), "machine": "AMD64"},
    })


def prepare(results, msi, worker, media, baseline):
    identity = BASELINES[baseline]
    host_sha = identity["host_sha256"]
    if digest(msi) != identity["msi_sha256"]:
        raise ValueError(f"The frozen MSI must match the published {baseline} artifact")
    supplied = digest(worker)
    if supplied == identity["worker_sha256"]:
        raise ValueError("Supply the separately built recorder worker")
    fixtures = media_hashes(media)
    results.mkdir(parents=True)
    workspace = image_workspace()
    control = workspace / "frozen"
    diagnostic = workspace / "recorder"
    extract(msi, control, results / "msi-admin.private.log")
    verify(control / HOST, host_sha, identity["worker_sha256"])
    shutil.copytree(control, diagnostic)
    shutil.copyfile(worker, (diagnostic / HOST).parent / WORKER)
    verify(diagnostic / HOST, host_sha, supplied)
    save(results / IMAGE, {
        "baseline_label": baseline, "frozen_msi_sha256": identity["msi_sha256"],
        "diagnostic_worker_sha256": supplied, "media_sha256": fixtures,
        "control": str(control / HOST), "diagnostic": str(diagnostic / HOST), "media": str(media),
        "media_stats": media_stats(media),
        "declared_trial_seconds": 60, "maximum_recorder_on_trials": MAX_ON,
        "review_each_capture_before_scheduling_another": True,
    })


def refill_plan(comparison, hold_arm, legacy_refill_supported, *, candidate_picture_handoff=False):
    if candidate_picture_handoff and comparison != "ordinary":
        raise ValueError("--candidate-picture-handoff requires --comparison ordinary")
    if comparison == "ordinary":
        environment = {arm: dict.fromkeys(DIAGNOSTIC_KEYS) for arm in ORDINARY_ORDER[0]}
        if candidate_picture_handoff:
            environment["R"][PICTURE_HANDOFF_KEY] = None
            environment["F"][PICTURE_HANDOFF_KEY] = "1"
        return ORDINARY_ORDER, environment
    legacy_refill = {LEGACY_REFILL_KEY: "1"} if legacy_refill_supported else {}
    if comparison == "refill":
        return REFILL_ORDER, {"A": {REFILL_KEY: None, **legacy_refill}, "B": {REFILL_KEY: "1", **legacy_refill}}
    if comparison == "bounded":
        return (("A", "D"),), {
            "A": {REFILL_KEY: None, LEGACY_REFILL_KEY: "1"},
            "D": {REFILL_KEY: None, LEGACY_REFILL_KEY: None},
        }
    if hold_arm == "D":
        if not legacy_refill_supported:
            raise ValueError("The D arm needs the independently expiring refill policy")
        legacy_refill = {LEGACY_REFILL_KEY: None}
    refill_value = "1" if hold_arm == "B" else None
    order = BOUNDED_POLL_ORDER if hold_arm == "D" else ((hold_arm, "C"),)
    return order, {
        hold_arm: {REFILL_KEY: refill_value, LEGACY_POLL_KEY: None, **legacy_refill},
        "C": {REFILL_KEY: refill_value, LEGACY_POLL_KEY: "1", **legacy_refill},
    }


def refill_baselines(comparison, hold_arm):
    if comparison == "ordinary" or (comparison == "poll-order" and hold_arm == "D"):
        return "cand4", "cand3"
    return "cand3", "cand1"


def prepare_refill(results, worker, media, packages, *, comparison="refill", hold_arm="B",
                   candidate_poll_policy="source_first", candidate_picture_handoff=False):
    results.mkdir(parents=True, exist_ok=True)
    if (results / REFILL_IMAGE).exists():
        raise FileExistsError("Use a fresh refill campaign name")
    worker_sha = digest(worker)
    worker_bytes = worker.read_bytes()
    legacy_refill_supported = LEGACY_REFILL_KEY.encode() in worker_bytes
    order, arm_environment = refill_plan(comparison, hold_arm, legacy_refill_supported,
                                         candidate_picture_handoff=candidate_picture_handoff)
    if candidate_picture_handoff:
        if candidate_poll_policy != "source_first":
            raise ValueError("The picture-handoff comparison requires source-first polling")
        if PICTURE_HANDOFF_KEY.encode() not in worker_bytes:
            raise ValueError("Supply a candidate worker with support for picture handoff")
    required = {"refill": REFILL_KEY, "bounded": LEGACY_REFILL_KEY, "poll-order": LEGACY_POLL_KEY}
    if comparison in required and required[comparison].encode() not in worker_bytes:
        raise ValueError(f"Supply an instrumented worker with support for the {comparison} comparison")
    build_path = worker.with_name("build-diagnostic.json")
    build = read(build_path) if build_path.is_file() else None
    if build is not None and build["worker"]["sha256"] != worker_sha:
        raise ValueError("Diagnostic worker differs from its build receipt")
    baseline_labels = refill_baselines(comparison, hold_arm)
    review_candidate = baseline_labels[0] == "cand4"
    if review_candidate and (build is None or not build.get("head_at_build") or not build.get("native_build_inputs_sha256")):
        raise ValueError("The comparison needs a source and worker build receipt")
    fixtures = media_hashes(media)
    if review_candidate and fixtures != PROTECTED_FIXTURE_SHA256:
        raise ValueError("The three generated clips must match the retained editor-size fixture")
    snapshots = media_stats(media)
    workspace = image_workspace()
    package_receipts = {}
    for label in baseline_labels:
        msi, exe = packages[label]
        if exe is None:
            layout = workspace / label
            if digest(msi) != BASELINES[label]["msi_sha256"]:
                raise ValueError(f"The frozen MSI must match the published {label} artifact")
            extract(msi, layout, results / (label + "-msi-admin.private.log"))
            exe = layout / HOST
        verify_package(label, msi, exe)
        package_receipts[label] = {
            **BASELINES[label], "published_commit": PUBLISHED[label], "executable": str(exe), "msi": str(msi),
        }
    latest_label = baseline_labels[0]
    latest = package_receipts[latest_label]
    if worker_sha in {package["worker_sha256"] for package in package_receipts.values()}:
        raise ValueError("Supply the separately built instrumented worker")
    diagnostic = workspace / "refill"
    shutil.copytree(Path(latest["executable"]).parents[2], diagnostic)
    exe = diagnostic / HOST
    verify(exe, latest["host_sha256"], latest["worker_sha256"])
    shutil.copyfile(worker, exe.parent / WORKER)
    verify(exe, latest["host_sha256"], worker_sha)
    rule_key = "bounded poll" if comparison == "poll-order" and hold_arm == "D" else comparison
    save(results / REFILL_IMAGE, {
        "packages": package_receipts,
        "diagnostic_host_baseline": latest_label, "diagnostic_executable": str(exe),
        "diagnostic_worker_sha256": worker_sha, "diagnostic_build": build,
        "media": str(media), "media_sha256": fixtures, "media_stats": snapshots,
        "declared_trial_seconds": 60, "physical_preview_px": EDITOR_PREVIEW,
        "comparison": comparison, "reference_hold_arm": "D" if comparison == "ordinary" else hold_arm,
        "candidate_poll_policy": candidate_poll_policy if comparison == "ordinary" else None,
        **({"candidate_picture_handoff": True} if candidate_picture_handoff else {}),
        "order": order, "arm_environment": arm_environment,
        "reverse_review_required": review_candidate,
        "stopping_rule": PAIR_STOPPING_RULES.get(rule_key, "Stop after the single declared pair. Retain both attempts."),
    })


def conditions():
    user = ctypes.windll.user32
    user.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
    user.GetDC.restype = ctypes.c_void_p
    old = user.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    dc = user.GetDC(None)
    battery = psutil.sensors_battery()
    try:
        return {"physical_desktop_px": [user.GetSystemMetrics(0), user.GetSystemMetrics(1)],
                "desktop_hz": ctypes.windll.gdi32.GetDeviceCaps(ctypes.c_void_p(dc), 116),
                "system_dpi": user.GetDpiForSystem(),
                "ac": battery.power_plugged if battery is not None else None}
    finally:
        user.ReleaseDC(None, ctypes.c_void_p(dc))
        if old:
            user.SetThreadDpiAwarenessContext(ctypes.c_void_p(old))


def run(results, arm, slot, capture=False):
    image = json.loads((results / IMAGE).read_text(encoding="utf-8"))
    label = image.get("baseline_label", "b817372")
    baseline = BASELINES[label]
    if image["frozen_msi_sha256"] != baseline["msi_sha256"]:
        raise ValueError("Frozen MSI hash does not match the selected campaign baseline")
    frozen = arm == "frozen"
    recording = arm == "on" or capture
    name = f"{arm}-{slot}"
    exe = Path(image["control" if frozen else "diagnostic"])
    worker = baseline["worker_sha256"] if frozen else image["diagnostic_worker_sha256"]
    media = Path(image["media"])
    verify(exe, baseline["host_sha256"], worker)
    if media_stats(media) != image["media_stats"]:
        raise ValueError("Generated fixture media changed after campaign preparation")
    env = dict(os.environ)
    for key in CONTROLLED_ENV_KEYS:
        env.pop(key, None)
    if recording:
        env[CAPTURE_KEY] = str(results / (name + "-stall.private.json"))
    options = ["--seconds", "60", "--width", "3840", "--rate", "60/1", "--cut", ".5", "--layers", "3",
               "--window-mode", "visible", "--trace"]
    save(results / (name + "-conditions.json"), {
        "case": "composition", "arm": arm, "surface_requested": "small", "native_stall_recorder": recording,
        "native_miss_trace": False, "runtime_observer": True, "pdh_enabled": True,
        "UTC_start": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "baseline_label": label, "baseline_msi_sha256": baseline["msi_sha256"],
        "executable_sha256": baseline["host_sha256"], "native_worker_sha256": worker, "conditions": conditions(),
        "benchmark_options": options,
    })
    returncode = subprocess.run(
        [sys.executable, "benchmarks/run_qa.py", "--results", str(results / (name + "-supervisor")),
         "--status", str(results / "campaign-status.json"), "--timeout", "200", "--",
         sys.executable, "benchmarks/native_playback.py", str(exe), str(media), str(results / name), *options],
        cwd=ROOT, env=env,
    ).returncode
    verify(exe, baseline["host_sha256"], worker)
    return returncode


def display_settings(condition):
    return {key: condition.get(key) for key in ("physical_desktop_px", "desktop_hz", "system_dpi")}


def run_refill_trial(results, image, label, slot, position, arm):
    baseline_label = image["diagnostic_host_baseline"]
    baseline = BASELINES[baseline_label]
    recording = image["comparison"] != "ordinary"
    original_worker = not recording and arm == "R"
    exe = Path(image["packages"][baseline_label]["executable"] if original_worker else image["diagnostic_executable"])
    worker_sha = baseline["worker_sha256"] if original_worker else image["diagnostic_worker_sha256"]
    media = Path(image["media"])
    verify(exe, baseline["host_sha256"], worker_sha)
    if media_stats(media) != image["media_stats"]:
        raise ValueError("Generated fixture media changed after campaign preparation")
    condition = conditions()
    if condition["ac"] is not True:
        raise ValueError("Connect the workstation to AC before running the matched comparison")
    capture = results / (label + "-stall.private.jsonl")
    if capture.exists() or capture.with_suffix(capture.suffix + ".live").exists():
        raise FileExistsError(capture)
    env = dict(os.environ)
    for key in CONTROLLED_ENV_KEYS:
        env.pop(key, None)
    if recording:
        env[CAPTURE_KEY] = str(capture)
    requested_env = image["arm_environment"][arm]
    env.update({key: value for key, value in requested_env.items() if value is not None})
    options = ["--seconds", "60", "--width", "3840", "--rate", "60/1", "--cut", ".5", "--layers", "3",
               "--window-mode", "visible", "--trace", "--actual-display"]
    save(results / (label + "-conditions.json"), {
        "case": "composition", "pair": slot, "position": position, "arm": arm,
        "surface_requested": "editor", "physical_preview_required_px": EDITOR_PREVIEW,
        "native_stall_recorder": recording, "native_miss_trace": False, "runtime_observer": True, "pdh_enabled": True,
        "UTC_start": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "baseline_label": baseline_label, "baseline_msi_sha256": baseline["msi_sha256"],
        "executable_sha256": baseline["host_sha256"], "native_worker_sha256": worker_sha,
        "diagnostic_flag": {key: env.get(key) for key in requested_env},
        "conditions": condition, "benchmark_options": options,
    })
    returncode = subprocess.run(
        [sys.executable, "benchmarks/run_qa.py", "--results", str(results / (label + "-supervisor")),
         "--status", str(results / (label + "-status.json")), "--timeout", "200", "--",
         sys.executable, "benchmarks/native_playback.py", str(exe), str(media), str(results / label), *options],
        cwd=ROOT, env=env,
    ).returncode
    verify(exe, baseline["host_sha256"], worker_sha)
    if media_stats(media) != image["media_stats"]:
        raise ValueError("Generated fixture media changed during the trial")
    return {"trial": label, "arm": arm, "supervisor_exit": returncode,
            "display_after": display_settings(conditions())}


def run_refill_pair(results, slot, reverse_reviewed=False):
    image = read(results / REFILL_IMAGE)
    if not 1 <= slot <= len(image["order"]):
        raise ValueError("The requested pair is outside the declared comparison")
    if reverse_reviewed and not (slot == 2 and image.get("reverse_review_required")):
        raise ValueError("Reverse review applies only to the second pair of a selected comparison")
    decision = {}
    if slot == 2:
        review = results / "pair-1-review.json"
        first_review = read(review) if review.is_file() else {}
        if not first_review.get("comparison_valid"):
            raise ValueError("Pair one must have a valid review before pair two may run")
        if image.get("reverse_review_required"):
            if not reverse_reviewed:
                raise ValueError("Use --reverse-reviewed after reviewing the first pair's causal evidence")
            if image["comparison"] == "ordinary":
                candidate = next(arm for arm in first_review["attempts"] if arm["arm"] == "F")
                if not all(candidate["performance_screens"].values()):
                    raise ValueError("The first ordinary candidate attempt missed a timing screen. Retain and review the attempt.")
            if first_review["attempts"][0]["display_before"] != display_settings(conditions()):
                raise ValueError("The display settings differ from the first pair")
            decision = {"reverse_reviewed": True, "first_pair_review_sha256": digest(review)}
    for label in refill_baselines(image["comparison"], image["reference_hold_arm"]):
        package = image["packages"][label]
        if (package["published_commit"] != PUBLISHED[label] or
                any(package[key] != value for key, value in BASELINES[label].items())):
            raise ValueError(f"{label} package receipt changed")
        verify_package(label, Path(package["msi"]), Path(package["executable"]))
    order = image["order"][slot - 1]
    save(results / f"pair-{slot}-start.json", {"pair": slot, "order": order, **decision})
    attempts = []
    try:
        for position, arm in enumerate(order, 1):
            label = f"pair-{slot}-{position}-{arm.lower()}"
            try:
                attempts.append(run_refill_trial(results, image, label, slot, position, arm))
            except (Exception, KeyboardInterrupt) as error:
                attempts.append({"trial": label, "arm": arm, "supervisor_exit": None, "launcher_error": type(error).__name__})
                raise
    finally:
        save(results / f"pair-{slot}-exits.json", {"pair": slot, "attempts": attempts})
    return int(any(row["supervisor_exit"] for row in attempts))


def decoder_attribution(results):
    image = read(results / REFILL_IMAGE)
    if image["comparison"] != "poll-order" or image["reference_hold_arm"] != "D":
        raise ValueError("Prepare a bounded polling-order diagnostic image first")
    trace = results / "api-gpu.private.etl"
    if trace.exists() or (results / "api-attribution-d-conditions.json").exists():
        raise FileExistsError("Use a fresh attribution directory")
    providers = results / "api-providers.txt"
    providers.write_text('"Microsoft-Windows-DxgKrnl" 0x0800C001 5\n'
                         '"Microsoft-Windows-Direct3D11" 0xffffffffffffffff 5\n', encoding="ascii")
    session = f"VlogCraftDecoderAttribution-{os.getpid()}"
    subprocess.run(["logman", "start", session, "-pf", providers, "-bs", "256", "-nb", "32", "128",
                    "-o", trace, "-f", "bincirc", "-max", "1536", "-ets"], check=True)
    try:
        attempt = run_refill_trial(results, image, "api-attribution-d", 0, 1, "D")
        save(results / "api-attribution-exit.json", attempt)
        return attempt["supervisor_exit"]
    finally:
        subprocess.run(["logman", "stop", session, "-ets"], check=True)


def effective_policy(raw):
    initial = raw.get("base") or {}
    active = raw.get("last") or {}
    final = raw.get("drained_last") or active
    policies = ("completion_poll_policy", "refill_policy", "stall_recording")
    counters = ("combined_poll_opportunities", "source_wait_poll_bypasses")
    observed = {key: active.get(key) for key in policies}
    observed["consistent_through_drain"] = all(
        observed[key] is not None and initial.get(key) == observed[key] == final.get(key) for key in policies
    )
    for key in counters:
        start, stop = initial.get(key), active.get(key)
        observed[key] = stop - start if type(start) is int and type(stop) is int and stop >= start >= 0 else None
    return observed


def effective_picture_handoff(raw):
    initial, active, drained = (raw.get(key) or {} for key in ("base", "last", "drained_last"))
    enabled = active.get("picture_handoff")
    consistent = (type(enabled) is bool and initial.get("picture_handoff") is enabled
                  and drained.get("picture_handoff") is enabled)
    start, stop, final = (status.get("handoff_draws") for status in (initial, active, drained))
    counters_valid = all(type(value) is int for value in (start, stop, final)) and 0 <= start <= stop <= final
    return {
        "enabled": enabled,
        "consistent_through_drain": consistent,
        "active_draws": stop - start if counters_valid else None,
        "drained_draws": final if counters_valid else None,
    }


def attempt_json(path):
    if not path.is_file():
        return {}
    try:
        data = read(path)
    except (UnicodeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def summarize_refill_attempt(results, attempt, image):
    from phase3b_stall_evidence import reduce_record

    name = attempt["trial"]
    playback = results / name / "native-playback.json"
    supervisor = results / (name + "-supervisor") / "supervisor.json"
    capture = results / (name + "-stall.private.jsonl")
    live = capture.with_suffix(capture.suffix + ".live")
    receipt_path = results / (name + "-conditions.json")
    receipt = attempt_json(receipt_path)
    raw = attempt_json(playback)
    kept = capture if capture.is_file() else live if live.is_file() else None
    recorded = attempt_json(kept) if kept is not None else {}
    if not recorded and kept == capture and live.is_file():
        kept, recorded = live, attempt_json(live)
    try:
        reduced_capture = reduce_record(recorded) if recorded else None
    except (ValueError, KeyError, IndexError, TypeError):
        reduced_capture = None
    last = raw.get("last") or {}
    drained = raw.get("drained_last") or last
    completed_frame = drained.get("completed_sequence_frame")
    physical = raw.get("physical_alignment", {}).get("actual_client_pixels", [None] * 4)[2:]
    native = [last.get("surface_width"), last.get("surface_height")]
    power = raw.get("conditions", {}).get("samples", [])
    ac = bool(power) and all(row.get("ac_power") is True for row in power)
    window = raw.get("window_condition", {})
    visible = window.get("mode") == "visible" and window.get("condition_held") is True
    owned = attempt_json(supervisor).get("process_ownership", {})
    clean = bool(owned) and all(owned.get(key) == 0 for key in (
        "job_members_at_cleanup", "remaining_owned_processes", "unrelated_processes_targeted",
        "new_visible_terminal_windows_after"))
    deferred = [row.get("deferred_refills") for row in last.get("decoder_statistics", [])]
    requested = image["arm_environment"][attempt["arm"]]
    baseline = image["diagnostic_host_baseline"]
    ordinary = image["comparison"] == "ordinary"
    original_worker = ordinary and attempt["arm"] == "R"
    expected_worker = image["packages"][baseline]["worker_sha256"] if original_worker else image["diagnostic_worker_sha256"]
    policy = effective_policy(raw)
    correct_hold_counters = len(deferred) == 3 and all(type(count) is int and count >= 0 for count in deferred)
    if not image.get("reverse_review_required"):
        correct_hold_counters = correct_hold_counters and (not any(deferred) if requested[REFILL_KEY] == "1" else any(deferred))
    controls = {
        "supervisor_passed": attempt["supervisor_exit"] == 0,
        "exact_editor_geometry": physical == native == image["physical_preview_px"],
        "ac_observed": ac,
        "visible_foreground_unobscured": visible,
        "owned_process_cleanup": clean,
        "exact_audio_and_endpoint": (raw.get("reached_end") is True and raw.get("underruns") == 0 and
                                     raw.get("samples") == raw.get("expected_samples") == 2_880_000 and
                                     completed_frame == 3599),
        "declared_workload": (
            raw.get("seconds") == 60 and raw.get("rate") == "60/1" and raw.get("cut_seconds") == .5 and
            raw.get("video_tracks") == raw.get("audio_tracks") == raw.get("source_files") == 3 and
            raw.get("original_resolution") == raw.get("program_resolution") == [3840, 2160] and
            raw.get("source_rewind_schedule") == "original" and raw.get("source_switches") is False and
            raw.get("proxies") is False and raw.get("intermediate_encoded_video_files") == 0
        ),
        "expected_hold_counters": bool(correct_hold_counters),
        "matched_binary_and_flag": (
            receipt.get("native_worker_sha256") == expected_worker and
            receipt.get("baseline_label") == baseline and
            receipt.get("baseline_msi_sha256") == image["packages"][baseline]["msi_sha256"] and
            receipt.get("executable_sha256") == image["packages"][baseline]["host_sha256"] and
            receipt.get("diagnostic_flag") == requested
        ),
    }
    if ordinary:
        controls["native_recorders_off"] = (kept is None and receipt.get("native_stall_recorder") is False
                                            and receipt.get("native_miss_trace") is False
                                            and (original_worker or policy["stall_recording"] is False))
        controls["effective_bounded_poll_policy"] = original_worker or (
            policy["consistent_through_drain"] and policy["completion_poll_policy"] == image["candidate_poll_policy"]
            and policy["refill_policy"] == "bounded"
        )
        if image.get("candidate_picture_handoff") and not original_worker:
            handoff = effective_picture_handoff(raw)
            policy["picture_handoff"] = handoff
            controls["effective_picture_handoff"] = (
                handoff["enabled"] is True and handoff["consistent_through_drain"] and (handoff["active_draws"] or 0) > 0
            )
    else:
        controls["instrumented_capture_complete"] = kept == capture and "pacing_schema" in recorded and reduced_capture is not None
    display = display_settings(receipt.get("conditions", {}))
    if image.get("reverse_review_required"):
        if not ordinary:
            eager = attempt["arm"] == "C"
            opportunities = policy["combined_poll_opportunities"]
            bypasses = policy["source_wait_poll_bypasses"]
            controls["effective_bounded_poll_policy"] = (
                policy["consistent_through_drain"] and policy["completion_poll_policy"] == ("eager" if eager else "source_first")
                and policy["refill_policy"] == "bounded" and policy["stall_recording"] is True
                and (opportunities == bypasses == 0 if eager else opportunities is not None and bypasses is not None)
            )
        controls.update({
            "display_unchanged": all(value is not None for value in display.values()) and display == attempt.get("display_after"),
            "observer_protocol": bool(raw.get("runtime_trace")) and bool(raw.get("status_trace")) and
                                 raw.get("gpu_counter_observer", "").startswith("legacy high-frequency"),
        })
    start = raw.get("base") or {}
    frame_keys = ("distinct_sequence_submissions", "skipped_sequence_frames", "source_wait_iterations", "gpu_wait_iterations",
                  "skipped_after_source_wait", "skipped_after_gpu_wait", "skipped_without_queue_wait")
    frame_delta = {key: last[key] - start[key] if key in last and key in start else None for key in frame_keys}
    active_intervals = last.get("timings", {}).get("playback_present_interval", {})
    active_gap = active_intervals.get("max_ms") if active_intervals.get("count", 0) > 0 else None
    fps = raw.get("distinct_sequence_fps")
    skips = frame_delta["skipped_sequence_frames"]
    screens = {"at_least_59_5_fps": fps >= 59.5 if fps is not None else None,
               "under_30_skips": skips < 30 if skips is not None else None,
               "at_most_100ms_gap": active_gap <= 100 if active_gap is not None else None}
    return {
        **{key: attempt[key] for key in ("trial", "arm", "supervisor_exit", "launcher_error", "display_after") if key in attempt},
        "controls": controls, "valid_comparison_arm": all(controls.values()),
        "physical_preview_px": physical, "native_surface_px": native,
        "host_sha256": receipt.get("executable_sha256"), "worker_sha256": receipt.get("native_worker_sha256"),
        "diagnostic_flag": receipt.get("diagnostic_flag"),
        "effective_policy": policy, "display_before": display,
        "policy_basis": "identified cand4 default and scrubbed environment" if original_worker else "native status",
        "measured_seconds": raw.get("measured_seconds"), "distinct_sequence_fps": raw.get("distinct_sequence_fps"),
        "frames": {**{key: last.get(key) for key in frame_keys},
                   **{key: last.get(key) for key in ("peak_source_queue_frames", "peak_inflight_gpu_frames")}},
        "active_frame_delta": frame_delta,
        "performance_screens": screens,
        "timings": {key: last.get("timings", {}).get(key) for key in ("playback_present_interval", "present_call")},
        "deferred_refills_by_decoder": deferred,
        "completed_sequence_frame": completed_frame,
        "samples": raw.get("samples"), "expected_samples": raw.get("expected_samples"), "underruns": raw.get("underruns"),
        "capture_sha256": digest(kept) if kept is not None else None,
        "capture_finalized": kept == capture,
        "capture_reduced": reduced_capture is not None,
        "recorder": reduced_capture,
    }


def collect_refill_pair(results, image, slot):
    order = image["order"][slot - 1]
    exits_path = results / f"pair-{slot}-exits.json"
    if exits_path.is_file():
        attempts = read(exits_path)["attempts"]
    else:
        attempts = []
        for position, arm in enumerate(order, 1):
            label = f"pair-{slot}-{position}-{arm.lower()}"
            if (results / (label + "-conditions.json")).is_file():
                attempts.append({"trial": label, "arm": arm, "supervisor_exit": None})
    arms = [summarize_refill_attempt(results, attempt, image) for attempt in attempts]
    valid = [arm["arm"] for arm in arms if arm["valid_comparison_arm"]]
    matching_display = len(arms) == 2 and arms[0]["display_before"] == arms[1]["display_before"]
    if slot == 2 and image.get("reverse_review_required") and matching_display:
        first = read(results / "pair-1-review.json")
        matching_display = arms[0]["display_before"] == first["attempts"][0]["display_before"]
    pair_valid = valid == order and (matching_display or not image.get("reverse_review_required"))
    result = {"pair": slot, "attempts": arms, "matching_display": matching_display, "comparison_valid": pair_valid}
    if image["comparison"] == "ordinary":
        result["candidate_passed"] = pair_valid and all(next(arm for arm in arms if arm["arm"] == "F")["performance_screens"].values())
    return result


def review_refill_pair(results, slot):
    image = read(results / REFILL_IMAGE)
    report_path = results / f"pair-{slot}-review.json"
    if not report_path.is_file():
        if not (results / f"pair-{slot}-exits.json").is_file():
            raise ValueError("A pair review requires its exit receipt. Use refill-evidence to retain a partially written pair.")
        save(report_path, collect_refill_pair(results, image, slot))
    report = read(report_path)
    print(json.dumps({
        "pair": slot, "comparison_valid": report["comparison_valid"],
        **({"candidate_passed": report["candidate_passed"]} if "candidate_passed" in report else {}),
        "attempts": [{key: arm.get(key) for key in (
            "trial", "arm", "controls", "effective_policy", "measured_seconds", "distinct_sequence_fps", "frames",
            "active_frame_delta", "timings", "deferred_refills_by_decoder", "performance_screens"
        )} for arm in report["attempts"]],
    }, indent=2))
    return int(not report["comparison_valid"] or report.get("candidate_passed") is False)


def export_refill(results, output):
    image = read(results / REFILL_IMAGE)
    build = image["diagnostic_build"]
    diagnostic_build = None if build is None else {
        "head_at_build": build["head_at_build"], "native_build_inputs_sha256": build["native_build_inputs_sha256"],
        "worker": {key: build["worker"][key] for key in ("bytes", "sha256", "machine")},
    }
    if diagnostic_build is not None and "toolchain_archive_sha256" in build:
        diagnostic_build["toolchain_archive_sha256"] = {
            key: build["toolchain_archive_sha256"][key] for key in ("zig", "ffmpeg-shared")
        }
    pairs = []
    for slot, order in enumerate(image["order"], 1):
        start_path = results / f"pair-{slot}-start.json"
        if not start_path.is_file():
            continue
        start = read(start_path)
        report_path = results / f"pair-{slot}-review.json"
        pairs.append({**collect_refill_pair(results, image, slot), "order": order,
                      "reverse_reviewed": start.get("reverse_reviewed", False),
                      "first_pair_review_sha256": start.get("first_pair_review_sha256"),
                      "review_sha256": digest(report_path) if report_path.is_file() else None})
    save(output, {
        "comparison": image["comparison"], "reference_hold_arm": image["reference_hold_arm"],
        "candidate_poll_policy": image.get("candidate_poll_policy"),
        **({"candidate_picture_handoff": True} if image.get("candidate_picture_handoff") else {}),
        "diagnostic_host_baseline": image["diagnostic_host_baseline"],
        "diagnostic_worker_sha256": image["diagnostic_worker_sha256"], "diagnostic_build": diagnostic_build,
        "packages": {label: {key: package[key] for key in (*BASELINES[label], "published_commit")}
                     for label, package in image["packages"].items()},
        "fixture_sha256": image["media_sha256"], "declared_trial_seconds": image["declared_trial_seconds"],
        "physical_preview_px": image["physical_preview_px"], "order": image["order"],
        "arm_environment": image["arm_environment"], "stopping_rule": image["stopping_rule"], "pairs": pairs,
    })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    setup = commands.add_parser("prepare", help="Extract a short administrative image and create a diagnostic clone")
    setup.add_argument("--frozen-msi", type=Path, required=True)
    setup.add_argument("--diagnostic-worker", type=Path, required=True)
    setup.add_argument("--media", type=Path, required=True)
    setup.add_argument("--baseline", choices=BASELINES, default="cand1")
    trial = commands.add_parser("trial", help="Run one unchanged protected workload")
    trial.add_argument("arm", choices=("frozen", "off", "on"))
    trial.add_argument("--slot", type=int, choices=range(1, MAX_ON + 1), default=1)
    trial.add_argument("--capture", action="store_true", help="Enable the recorder for a frozen trial")
    commands.add_parser("refill-build", help="Build and identify one worker using the pinned local SDK")
    commands.add_parser("decoder-attribution", help="Capture one source-first workload with bounded local GPU/API ETW")
    refill = commands.add_parser("refill-prepare", help="Prepare the pinned editor-size refill comparison")
    refill.add_argument("--latest-msi", type=Path, required=True)
    refill.add_argument("--prior-msi", type=Path, required=True)
    refill.add_argument("--diagnostic-worker", type=Path, required=True)
    refill.add_argument("--media", type=Path, required=True)
    refill.add_argument("--comparison", choices=("refill", "bounded", "poll-order", "ordinary"), default="refill")
    refill.add_argument("--hold-arm", choices=("A", "B", "D"), default="B", help="Refill behavior for the poll-order comparison")
    refill.add_argument("--candidate-poll-policy", choices=("source_first", "eager"), default="source_first",
                        help="Expected default in the ordinary candidate's native status")
    refill.add_argument("--candidate-picture-handoff", action="store_true",
                        help="Enable experimental picture handoff only in the ordinary candidate arm")
    pair = commands.add_parser("refill-pair", help="Run one declared matched pair at 958 × 539")
    pair.add_argument("--slot", type=int, choices=(1, 2), required=True)
    pair.add_argument("--reverse-reviewed", action="store_true", help="Confirm the first pair's causal review supports reversal")
    review = commands.add_parser("refill-review", help="Summarize and check a completed matched pair")
    review.add_argument("--slot", type=int, choices=(1, 2), required=True)
    evidence = commands.add_parser("refill-evidence", help="Export sanitized identities and every started pair")
    evidence.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("This campaign uses the Windows MSI and native worker")
    results = args.results.resolve()
    with serial():
        if args.command == "decoder-attribution":
            return decoder_attribution(results)
        if args.command == "refill-build":
            build_refill_worker(results)
            return 0
        if args.command == "prepare":
            prepare(results, args.frozen_msi.resolve(), args.diagnostic_worker.resolve(), args.media.resolve(), args.baseline)
            return 0
        if args.command == "refill-prepare":
            latest, prior = refill_baselines(args.comparison, args.hold_arm)
            prepare_refill(results, args.diagnostic_worker.resolve(), args.media.resolve(), {
                latest: (args.latest_msi.resolve(), None), prior: (args.prior_msi.resolve(), None),
            }, comparison=args.comparison, hold_arm=args.hold_arm, candidate_poll_policy=args.candidate_poll_policy,
                candidate_picture_handoff=args.candidate_picture_handoff)
            return 0
        if args.command == "refill-pair":
            return run_refill_pair(results, args.slot, args.reverse_reviewed)
        if args.command == "refill-review":
            return review_refill_pair(results, args.slot)
        if args.command == "refill-evidence":
            export_refill(results, args.output.resolve())
            return 0
        if args.arm == "off" and args.slot != 1:
            parser.error("The recorder-off arm has one slot")
        if args.capture and args.arm != "frozen":
            parser.error("Use --capture with a frozen trial")
        return run(results, args.arm, args.slot, capture=args.capture)


if __name__ == "__main__":
    raise SystemExit(main())
