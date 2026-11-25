"""Build and run the two-format independent-picture hardware probes serially."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "benchmarks"))
from phase3b_stall_campaign import serial


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("media", type=Path)
    parser.add_argument("out", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--memory-only", action="store_true", help="Measure the two populated slots without draw-verification allocations")
    mode.add_argument("--scheduler", action="store_true", help="Exercise scheduling with real hardware producers and a stalled peer")
    mode.add_argument("--publication", action="store_true", help="Compare a producer-local fence with legacy publication under a controlled decoder lock")
    mode.add_argument("--fenced", action="store_true", help="Verify fenced publication, pixel parity and resource retirement under a controlled decoder lock")
    args = parser.parse_args()
    out = args.out.resolve()
    sdk = ROOT / "build/tools/architecture/ffmpeg-shared/ffmpeg-9.0.2-full_build-shared"
    zig = ROOT / "build/tools/architecture/zig/zig-x86_64-windows-0.17.1/zig.exe"
    with serial():
        out.mkdir(parents=True, exist_ok=False)
        source = ROOT / ("tests/native_handoff_scheduler.cpp" if args.scheduler else "benchmarks/windows/completed-picture.cpp")
        worker = out / f"{source.stem}.exe"
        subprocess.run([zig, "c++", "-std=c++17", "-O2", "-target", "x86_64-windows-gnu", source,
                        "-I" + str(sdk / "include"), "-L" + str(sdk / "lib"), "-lavformat", "-lavcodec",
                        "-lavutil", "-lswscale", "-ld3d11", "-ldxgi", "-o", worker], check=True)
        inputs = [source, *sorted((ROOT / "native").glob("*.h"))]
        if not args.scheduler:
            inputs.append(source.with_name("handoff-pixels.h"))
        receipt = {"source_head": subprocess.check_output(["git","rev-parse","HEAD"], cwd=ROOT, text=True).strip(),
                   "source_sha256": {p.relative_to(ROOT).as_posix():digest(p) for p in inputs},
                   "binary_sha256": digest(worker)}
        (out / "build.json").write_text(json.dumps(receipt, indent=2), encoding="utf8")
        failed = False
        env = dict(os.environ, PATH=str(sdk / "bin") + os.pathsep + os.environ["PATH"])
        worker_args = [flag for enabled, flag in (
            (args.memory_only, "--memory-only"), (args.publication, "--publication"), (args.fenced, "--fenced")
        ) if enabled]
        for label, name in (("nv12","h264-4k60-0.mp4"), ("p010","hevc10-4k5994.mp4")):
            fixture = args.media.resolve() / name
            result = subprocess.run([sys.executable, ROOT / "benchmarks/run_qa.py", "--timeout","60",
                "--results",out / label, "--status",out / "status.json","--",worker,fixture,
                *worker_args], env=env)
            print((out / label / "supervisor.log").read_text(encoding="utf8",errors="replace"),flush=True)
            failed |= result.returncode != 0
        return int(failed)


if __name__ == "__main__":
    sys.exit(main())
