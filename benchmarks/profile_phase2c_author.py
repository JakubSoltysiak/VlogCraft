"""Profile frozen HDR10+ analysis on an already encoded, generated UHD master."""
import argparse
from collections import defaultdict
import json
import os
from pathlib import Path
import sys
import tempfile
from time import perf_counter, process_time
from unittest.mock import patch

from render_phase2 import ROOT, call, power

sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
import color_management
import hdr10plus_master as authoring
from hdr10plus_export import media
from performance import Resources
from test_hdr_color import CONTRACT


PQ_RGB = ("zscale=agamma=0:pin=2020:tin=smpte2084:min=2020_ncl:rin=limited:"
          "p=2020:t=smpte2084:m=gbr:r=full:filter=bilinear,format=gbrp16le")


def profile(source, results, count):
    if not power():
        raise RuntimeError("Connect AC for a comparable authoring profile")
    results.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(dir=results) as directory:
        work = Path(directory)
        static = work / "static.mp4"
        clock = ["-video_track_timescale", "120000", "-movie_timescale", "120000"]
        start = perf_counter()
        # Re-encode once to remove the prior picture-dependent SEI. The timed
        # arms all receive the same tagged Main10 intermediate.
        call(["ffmpeg", "-v", "error", "-nostdin", "-i", source, "-frames:v", str(count),
              "-vf", "sidedata=mode=delete", "-c:v", "libx265", "-profile:v", "main10",
              "-pix_fmt", "yuv420p10le", "-preset", "ultrafast", "-crf", "15",
              "-x265-params", color_management.x265_metadata(CONTRACT),
              "-color_primaries", "bt2020", "-color_trc", "smpte2084", "-colorspace", "bt2020nc",
              "-color_range", "tv", "-tag:v", "hvc1", "-c:a", "copy", *clock, static], 240)
        preparation = perf_counter() - start
        video, _ = media(static)
        first = ["ffmpeg", "-v", "error", "-nostdin", "-threads", "4", "-i", static,
                 "-map", "0:v:0", "-an", "-filter_threads", "2"]
        isolated = {}
        for name, video_filter in (("hevc_decode_to_null", []),
                                   ("decode_and_pq_reconstruction_to_null", ["-vf", PQ_RGB])):
            start = perf_counter()
            call([*first, *video_filter, "-f", "null", "-"], 240)
            isolated[name] = perf_counter() - start
        start = perf_counter()
        from hdr10plus_authoring import decoded_frames
        with decoded_frames(static, video["width"], video["height"], lambda: False) as frames:
            pictures = sum(1 for _ in frames)
        isolated["decode_reconstruct_and_drain_pipe"] = perf_counter() - start
        if pictures != count:
            raise ValueError("Unexpected profile picture count")

        samples = defaultdict(lambda: {"wall_seconds": 0., "host_cpu_seconds": 0., "calls": 0})

        def instrument(name, method):
            def timed(*args, **kwargs):
                wall, cpu = perf_counter(), process_time()
                try:
                    return method(*args, **kwargs)
                finally:
                    row = samples[name]
                    row["wall_seconds"] += perf_counter() - wall
                    row["host_cpu_seconds"] += process_time() - cpu
                    row["calls"] += 1
            return timed

        def runner(command, cwd):
            name = "remux" if command[-1] == str(authored) else "prepare_fragments"
            instrument(name, lambda: call(command, 240))()

        def phase(message, _):
            if message.startswith("Attaching"):
                samples["analysis_interval"]["wall_seconds"] = perf_counter() - author_started

        authored = work / "master.mp4"
        monitor = Resources(os.getpid(), gpu=False)
        try:
            author_started = perf_counter()
            with (patch.object(authoring, "payload", instrument("statistics_and_payload", authoring.payload)),
                  patch.object(authoring, "inject", instrument("insert_sei", authoring.inject)),
                  patch.object(authoring, "verify", instrument("verify_all_packets", authoring.verify))):
                authored_count = authoring.author(static, authored, work, 60, count, runner, phase, lambda: False)
            wall = perf_counter() - author_started
        finally:
            resources = monitor.finish()
        result = dict(width=video["width"], height=video["height"], pictures=authored_count,
                      prepared_seconds=preparation, isolated_wall_seconds=isolated,
                      author_wall_seconds=wall, operations=samples, resources=resources, ac_at_finish=power())
        # Both contain generated media only. Retain the identical intermediate
        # for matched authoring benchmarks without repeating the encode.
        static.replace(results / "static.mp4")
        authored.replace(results / "reference.mp4")
        (results / "profile.json").write_text(json.dumps(result, indent=2)+"\n", encoding="utf-8")
        return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("results", type=Path)
    parser.add_argument("--frames", type=int, required=True)
    args = parser.parse_args()
    print(json.dumps(profile(args.source.resolve(), args.results.resolve(), args.frames), indent=2))
