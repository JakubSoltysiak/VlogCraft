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
BASELINES = {
    "cand1": {
        "msi_sha256": "4d82887f41389b458278056970e12a49319850b0fb13df281c1f36fe947e9bd4",
        "host_sha256": "cb09208757e396e6a808d9f9bb88312817154a3e373eb34d40a430ac315eaf93",
        "worker_sha256": "1717545bd55170d5299b524fd4a94bd12cb1564e6c31ff3f7cd3a9ab313746e0",
        "head_at_build": "893dc6e23af419a69591bdbe5386f0db3f97cceb",
    },
    "b817372": {
        "msi_sha256": "4513cef410ffe7d2fe775b0b1eec8dc86732f82dcbe9cf5d7ae30d055dd76fa0",
        "host_sha256": "e6330cc74de309c658feba9beaa58847782b30226f861836a94401ab2bbdfa90",
        "worker_sha256": "0138b285593a55aa5ac57c3448ee23e2b4c61be0dd6d80af9bf7d1014f7dcc49",
    },
}
MAX_ON = 3


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path, data):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2)
        stream.write("\n")


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
    workspace = Path(tempfile.mkdtemp(prefix="vc3b-", dir=Path(os.environ["LOCALAPPDATA"]) / "Temp"))
    control = workspace / "frozen"
    diagnostic = workspace / "recorder"
    subprocess.run(["msiexec.exe", "/a", str(msi), "/qn", "TARGETDIR=" + str(control),
                    "/L*v", str(results / "msi-admin.private.log")], check=True, cwd=ROOT)
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
    env.pop(CAPTURE_KEY, None)
    env.pop("VLOGCRAFT_NATIVE_TRACE_FILE", None)
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
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("This campaign uses the Windows MSI and native worker")
    results = args.results.resolve()
    with serial():
        if args.command == "prepare":
            prepare(results, args.frozen_msi.resolve(), args.diagnostic_worker.resolve(), args.media.resolve(), args.baseline)
            return 0
        if args.arm == "off" and args.slot != 1:
            parser.error("The recorder-off arm has one slot")
        if args.capture and args.arm != "frozen":
            parser.error("Use --capture with a frozen trial")
        return run(results, args.arm, args.slot, capture=args.capture)


if __name__ == "__main__":
    raise SystemExit(main())
