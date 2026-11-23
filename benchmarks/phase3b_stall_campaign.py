"""Repeat the bounded three-layer native recorder campaign with a frozen MSI and a diagnostic worker."""

import argparse
from contextlib import contextmanager
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
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
REFILL_IMAGE = "refill-image.private.json"
EDITOR_PREVIEW = [958, 539]
REFILL_ORDER = (("A", "B"), ("B", "A"))
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
    "b817372": {
        "msi_sha256": "4513cef410ffe7d2fe775b0b1eec8dc86732f82dcbe9cf5d7ae30d055dd76fa0",
        "host_sha256": "e6330cc74de309c658feba9beaa58847782b30226f861836a94401ab2bbdfa90",
        "worker_sha256": "0138b285593a55aa5ac57c3448ee23e2b4c61be0dd6d80af9bf7d1014f7dcc49",
    },
}
PUBLISHED = {
    "cand1": "28c0abf221c87e1b7c673a36abe70fac594cdc27",
    "cand3": "59008494539a3a622ebc92f85fd072c39f527dcc",
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


def refill_plan(comparison, hold_arm, legacy_refill_supported):
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
    return ((hold_arm, "C"),), {
        hold_arm: {REFILL_KEY: refill_value, LEGACY_POLL_KEY: None, **legacy_refill},
        "C": {REFILL_KEY: refill_value, LEGACY_POLL_KEY: "1", **legacy_refill},
    }


def prepare_refill(results, worker, media, packages, *, comparison="refill", hold_arm="B"):
    results.mkdir(parents=True, exist_ok=True)
    if (results / REFILL_IMAGE).exists():
        raise FileExistsError("Use a fresh refill campaign name")
    worker_sha = digest(worker)
    worker_bytes = worker.read_bytes()
    legacy_refill_supported = LEGACY_REFILL_KEY.encode() in worker_bytes
    required = {"refill": REFILL_KEY, "bounded": LEGACY_REFILL_KEY, "poll-order": LEGACY_POLL_KEY}
    if required[comparison].encode() not in worker_bytes:
        raise ValueError(f"Supply an instrumented worker with support for the {comparison} comparison")
    order, arm_environment = refill_plan(comparison, hold_arm, legacy_refill_supported)
    build_path = worker.with_name("build-diagnostic.json")
    build = read(build_path) if build_path.is_file() else None
    if build is not None and build["worker"]["sha256"] != worker_sha:
        raise ValueError("Diagnostic worker differs from its build receipt")
    fixtures = media_hashes(media)
    snapshots = media_stats(media)
    workspace = image_workspace()
    package_receipts = {}
    for label in PUBLISHED:
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
    latest = package_receipts["cand3"]
    if worker_sha in {package["worker_sha256"] for package in package_receipts.values()}:
        raise ValueError("Supply the separately built instrumented worker")
    diagnostic = workspace / "refill"
    shutil.copytree(Path(latest["executable"]).parents[2], diagnostic)
    exe = diagnostic / HOST
    verify(exe, latest["host_sha256"], latest["worker_sha256"])
    shutil.copyfile(worker, exe.parent / WORKER)
    verify(exe, latest["host_sha256"], worker_sha)
    save(results / REFILL_IMAGE, {
        "packages": package_receipts,
        "diagnostic_host_baseline": "cand3", "diagnostic_executable": str(exe),
        "diagnostic_worker_sha256": worker_sha, "diagnostic_build": build,
        "media": str(media), "media_sha256": fixtures, "media_stats": snapshots,
        "declared_trial_seconds": 60, "physical_preview_px": EDITOR_PREVIEW,
        "comparison": comparison, "reference_hold_arm": hold_arm,
        "order": order, "arm_environment": arm_environment,
        "stopping_rule": ("Review pair one before pair two. Stop after the two declared pairs, or stop if controls fail. "
                          "Retain all attempts." if comparison == "refill" else
                          "Stop after the single declared pair. Retain both attempts."),
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
    for key in (CAPTURE_KEY, COMPLETION_KEY, "VLOGCRAFT_NATIVE_TRACE_FILE", *DIAGNOSTIC_KEYS):
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


def run_refill_trial(results, image, label, slot, position, arm):
    exe = Path(image["diagnostic_executable"])
    worker_sha = image["diagnostic_worker_sha256"]
    baseline = BASELINES["cand3"]
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
    for key in (COMPLETION_KEY, "VLOGCRAFT_NATIVE_TRACE_FILE", *DIAGNOSTIC_KEYS):
        env.pop(key, None)
    env[CAPTURE_KEY] = str(capture)
    requested_env = image["arm_environment"][arm]
    env.update({key: value for key, value in requested_env.items() if value is not None})
    options = ["--seconds", "60", "--width", "3840", "--rate", "60/1", "--cut", ".5", "--layers", "3",
               "--window-mode", "visible", "--trace", "--actual-display"]
    save(results / (label + "-conditions.json"), {
        "case": "composition", "pair": slot, "position": position, "arm": arm,
        "surface_requested": "editor", "physical_preview_required_px": EDITOR_PREVIEW,
        "native_stall_recorder": True, "native_miss_trace": False, "runtime_observer": True, "pdh_enabled": True,
        "UTC_start": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "baseline_label": "cand3", "baseline_msi_sha256": baseline["msi_sha256"],
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
    return {"trial": label, "arm": arm, "supervisor_exit": returncode}


def run_refill_pair(results, slot):
    image = read(results / REFILL_IMAGE)
    if slot > len(image["order"]):
        raise ValueError("The requested pair is outside the declared comparison")
    if slot == 2:
        review = results / "pair-1-review.json"
        if not review.is_file() or not read(review)["comparison_valid"]:
            raise ValueError("Pair one must have a valid review before pair two may run")
    for label in PUBLISHED:
        package = image["packages"][label]
        if (package["published_commit"] != PUBLISHED[label] or
                any(package[key] != value for key, value in BASELINES[label].items())):
            raise ValueError(f"{label} package receipt changed")
        verify_package(label, Path(package["msi"]), Path(package["executable"]))
    order = image["order"][slot - 1]
    save(results / f"pair-{slot}-start.json", {"pair": slot, "order": order})
    attempts = []
    try:
        for position, arm in enumerate(order, 1):
            label = f"pair-{slot}-{position}-{arm.lower()}"
            try:
                attempts.append(run_refill_trial(results, image, label, slot, position, arm))
            except Exception as error:
                attempts.append({"trial": label, "arm": arm, "supervisor_exit": None, "launcher_error": type(error).__name__})
                raise
    finally:
        save(results / f"pair-{slot}-exits.json", {"pair": slot, "attempts": attempts})
    return int(any(row["supervisor_exit"] for row in attempts))


def summarize_refill_attempt(results, attempt, image):
    from phase3b_stall_evidence import reduce_record

    name = attempt["trial"]
    playback = results / name / "native-playback.json"
    supervisor = results / (name + "-supervisor") / "supervisor.json"
    capture = results / (name + "-stall.private.jsonl")
    live = capture.with_suffix(capture.suffix + ".live")
    receipt_path = results / (name + "-conditions.json")
    receipt = read(receipt_path) if receipt_path.is_file() else {}
    raw = read(playback) if playback.is_file() else {}
    kept = capture if capture.is_file() else live if live.is_file() else None
    recorded = read(kept) if kept is not None else {}
    last = raw.get("last", {})
    drained = raw.get("drained_last") or last
    completed_frame = drained.get("completed_sequence_frame")
    physical = raw.get("physical_alignment", {}).get("actual_client_pixels", [None] * 4)[2:]
    native = [last.get("surface_width"), last.get("surface_height")]
    power = raw.get("conditions", {}).get("samples", [])
    ac = bool(power) and all(row["ac_power"] is True for row in power)
    window = raw.get("window_condition", {})
    visible = window.get("mode") == "visible" and window.get("condition_held") is True
    owned = read(supervisor).get("process_ownership", {}) if supervisor.is_file() else {}
    clean = bool(owned) and all(owned.get(key) == 0 for key in (
        "job_members_at_cleanup", "remaining_owned_processes", "unrelated_processes_targeted",
        "new_visible_terminal_windows_after"))
    deferred = [row.get("deferred_refills") for row in last.get("decoder_statistics", [])]
    requested = image["arm_environment"][attempt["arm"]]
    correct_hold_counters = bool(deferred) and all(type(count) is int for count in deferred) and (
        (not any(deferred)) if requested[REFILL_KEY] == "1" else any(deferred))
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
        "instrumented_capture_complete": kept == capture and "pacing_schema" in recorded,
        "expected_hold_counters": bool(correct_hold_counters),
        "matched_binary_and_flag": (
            receipt.get("native_worker_sha256") == image["diagnostic_worker_sha256"] and
            receipt.get("executable_sha256") == image["packages"]["cand3"]["host_sha256"] and
            receipt.get("diagnostic_flag") == requested
        ),
    }
    return {
        **attempt, "controls": controls, "valid_comparison_arm": all(controls.values()),
        "physical_preview_px": physical, "native_surface_px": native,
        "host_sha256": receipt.get("executable_sha256"), "worker_sha256": receipt.get("native_worker_sha256"),
        "diagnostic_flag": receipt.get("diagnostic_flag"),
        "measured_seconds": raw.get("measured_seconds"), "distinct_sequence_fps": raw.get("distinct_sequence_fps"),
        "frames": {key: last.get(key) for key in (
            "distinct_sequence_submissions", "skipped_sequence_frames", "source_wait_iterations", "gpu_wait_iterations",
            "skipped_after_source_wait", "skipped_after_gpu_wait", "skipped_without_queue_wait",
            "peak_source_queue_frames", "peak_inflight_gpu_frames")},
        "timings": {key: last.get("timings", {}).get(key) for key in ("playback_present_interval", "present_call")},
        "deferred_refills_by_decoder": deferred,
        "completed_sequence_frame": completed_frame,
        "samples": raw.get("samples"), "expected_samples": raw.get("expected_samples"), "underruns": raw.get("underruns"),
        "capture_sha256": digest(kept) if kept is not None else None,
        "capture_finalized": kept == capture,
        "recorder": reduce_record(recorded) if recorded else None,
    }


def review_refill_pair(results, slot):
    image = read(results / REFILL_IMAGE)
    report_path = results / f"pair-{slot}-review.json"
    if not report_path.is_file():
        exits_path = results / f"pair-{slot}-exits.json"
        attempts = read(exits_path)["attempts"]
        arms = [summarize_refill_attempt(results, attempt, image) for attempt in attempts]
        valid = [arm["arm"] for arm in arms if arm["valid_comparison_arm"]]
        save(report_path, {"pair": slot, "attempts": arms, "comparison_valid": valid == image["order"][slot - 1]})
    report = read(report_path)
    print(json.dumps({
        "pair": slot, "comparison_valid": report["comparison_valid"],
        "attempts": [{key: arm[key] for key in (
            "trial", "arm", "controls", "distinct_sequence_fps", "frames", "timings", "deferred_refills_by_decoder"
        )} for arm in report["attempts"]],
    }, indent=2))
    return int(not report["comparison_valid"])


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
    refill = commands.add_parser("refill-prepare", help="Prepare the pinned editor-size refill comparison")
    refill.add_argument("--latest-msi", type=Path, required=True)
    refill.add_argument("--prior-msi", type=Path, required=True)
    refill.add_argument("--diagnostic-worker", type=Path, required=True)
    refill.add_argument("--media", type=Path, required=True)
    refill.add_argument("--comparison", choices=("refill", "bounded", "poll-order"), default="refill")
    refill.add_argument("--hold-arm", choices=("A", "B", "D"), default="B", help="Refill behavior for the poll-order comparison")
    pair = commands.add_parser("refill-pair", help="Run one declared matched pair at 958 × 539")
    pair.add_argument("--slot", type=int, choices=(1, 2), required=True)
    review = commands.add_parser("refill-review", help="Summarize and check a completed matched pair")
    review.add_argument("--slot", type=int, choices=(1, 2), required=True)
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("This campaign uses the Windows MSI and native worker")
    results = args.results.resolve()
    with serial():
        if args.command == "prepare":
            prepare(results, args.frozen_msi.resolve(), args.diagnostic_worker.resolve(), args.media.resolve(), args.baseline)
            return 0
        if args.command == "refill-prepare":
            prepare_refill(results, args.diagnostic_worker.resolve(), args.media.resolve(), {
                "cand3": (args.latest_msi.resolve(), None), "cand1": (args.prior_msi.resolve(), None),
            }, comparison=args.comparison, hold_arm=args.hold_arm)
            return 0
        if args.command == "refill-pair":
            return run_refill_pair(results, args.slot)
        if args.command == "refill-review":
            return review_refill_pair(results, args.slot)
        if args.arm == "off" and args.slot != 1:
            parser.error("The recorder-off arm has one slot")
        if args.capture and args.arm != "frozen":
            parser.error("Use --capture with a frozen trial")
        return run(results, args.arm, args.slot, capture=args.capture)


if __name__ == "__main__":
    raise SystemExit(main())
