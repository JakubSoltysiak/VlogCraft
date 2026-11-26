"""Compare x265 presets on identical managed PQ input from a saved camera range."""
import argparse
import json
from pathlib import Path
import re
import sys
import tempfile
import time

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmarks.phase3a_camera_range import camera_range
from benchmarks.phase3a_encoder_probe import format_raw, run_to_file
import hdr_render
from native_project_plan import run_capture
from native_project_render import PQ_TAGS, parallel_camera_x265, raw_input
from native_project_verification import source_snapshot
import server


def profile(project, first, last, output):
    original = project.read_bytes()
    state = server.validate_document(json.loads(original))
    sources = source_snapshot(state)
    section = camera_range(state, first, last)
    settings = section["output"]
    width, height = settings["width"], settings["height"]
    frames = last - first
    if (width, height) != (3840, 2160) or settings.get("preset") != "slow":
        raise ValueError("This comparison requires the saved UHD Slow delivery profile")
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = {"frames": frames, "range": [first, last], "crf": settings["crf"], "encodes": {}}
    with tempfile.TemporaryDirectory(dir=output) as directory:
        work = Path(directory)
        raw = work / "input.yuv"
        command = hdr_render.command(section, 0, frames / 60, work / "static.mov", work)
        report["managed_to_raw_seconds"] = run_to_file(format_raw(command), raw, work)
        if raw.stat().st_size != frames * width * height * 3:
            raise ValueError("Unexpected planar Main10 byte count")
        raw_args = raw_input(width, height, "60")
        raw_args[raw_args.index("pipe:0")] = str(raw)
        for label, preset, pool in (("saved_slow", "slow", 2), ("slow_8_workers", "slow", 8),
                                    ("medium", "medium", 2)):
            movie = work / (label + ".mov")
            encode = [*raw_args, "-vf", "setsar=1," + PQ_TAGS, *command[command.index("-c:v"):-1], str(movie)]
            encode[encode.index("-preset") + 1] = preset
            if pool == 8:
                encode = parallel_camera_x265(encode)
            started = time.perf_counter()
            run_capture(encode, timeout=240, cwd=work)
            seconds = time.perf_counter() - started
            # Reconstruct each encoded picture and compare all three 10-bit planes to graph output.
            psnr = label + ".txt"
            run_capture([*raw_args, "-i", movie, "-filter_complex",
                         f"[1:v][0:v]psnr=stats_file={psnr}:shortest=1", "-f", "null", "-"],
                        timeout=120, cwd=work)
            scores = [float(v) for v in re.findall(r"psnr_avg:([\d.]+|inf)", (work / psnr).read_text())]
            if len(scores) != frames:
                raise ValueError("Incomplete decoded picture comparison")
            digest, _ = run_capture(["ffmpeg", "-v", "error", "-i", movie, "-map", "0:v:0",
                                     "-pix_fmt", "yuv420p10le", "-f", "hash", "-hash", "sha256", "-"])
            report["encodes"][label] = {
                "seconds": seconds, "bytes": movie.stat().st_size, "pool_workers": pool,
                "frame_threads": 2, "minimum_decoded_to_raw_psnr_db": min(scores),
                "decoded_picture_hash": digest.decode("ascii").strip(),
            }
    if project.read_bytes() != original or sources != source_snapshot(state):
        raise ValueError("Input identity changed during profiling")
    (output / "profile.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf8")
    return report


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("project", type=Path)
    cli.add_argument("output", type=Path)
    cli.add_argument("--frames", type=int, nargs=2, required=True, metavar=("FIRST", "LAST"))
    args = cli.parse_args()
    print(json.dumps(profile(args.project, *args.frames, args.output)))
