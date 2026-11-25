"""Exercise a lossless HDR10+ join at an already verified master's edit boundaries."""
import argparse
from fractions import Fraction
import json
from pathlib import Path
import subprocess
import sys
import time

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import hdr10plus_export
import render_engine
import timing
from hdr10plus_bitstream import packet_records
from native_project_plan import run_capture


def tile_durations(spans, count, rate):
    """Concat uses microseconds. Round absolute boundaries so the durations telescope."""
    previous = 0
    durations = []
    for first, last in spans:
        if first != previous or last <= first or last > count:
            raise ValueError("Picture spans do not tile the requested range")
        durations.append(timing.nearest(last * 1_000_000 / rate) -
                         timing.nearest(first * 1_000_000 / rate))
        previous = last
    if not durations or previous != count:
        raise ValueError("Incomplete picture spans")
    return durations


def decoded_hashes(path):
    data, _ = run_capture(["ffmpeg", "-v", "error", "-xerror", "-threads", "4", "-i", path,
                           "-map", "0:v:0", "-fps_mode", "passthrough", "-pix_fmt", "yuv420p10le",
                           "-f", "framemd5", "-"], timeout=1800)
    return [line.rsplit(b",", 1)[1].strip() for line in data.splitlines()
            if line and not line.startswith(b"#")]


def qualify(project, master, folder):
    import server
    state = server.validate_document(json.loads(project.read_bytes()))
    streams = hdr10plus_export.media(master)
    video = streams[0]
    rate = timing.rate(state["output"]["fps"])
    count = int(video["nb_frames"])
    base = Fraction(video["time_base"])
    if rate != 60 or len(streams) != 2 or base != Fraction(1,120000) or (
            video["width"], video["height"]) != (3840,2160):
        raise ValueError("This assembly trial requires the audited UHD60 master with audio")
    spans = render_engine.frame_spans(state, rate)
    durations = tile_durations(spans, count, rate)
    if len(spans) < 2:
        raise ValueError("No edit boundaries to qualify")
    with packet_records(master, "v:0") as packets:
        keys = {int(row[b"pts"]) * base * rate for row in packets if b"K" in row[b"flags"]}
    if any(first not in keys for first, _ in spans):
        raise ValueError("An authored render boundary has no random-access packet")
    folder.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    master = master.resolve(strict=True)
    cuts = ",".join(str(a) for a,_ in spans[1:])
    def ffmpeg(args):
        subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-n", *args], cwd=folder, check=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    ffmpeg(["-i", master, "-map", "0:v:0", "-c", "copy", "-f", "segment", "-segment_frames", cuts,
            "-reset_timestamps", "1", "-segment_format_options",
            "video_track_timescale=120000:movie_timescale=120000", "-avoid_negative_ts", "disabled",
            "part-%04d.mp4"])
    parts = sorted(folder.glob("part-*.mp4"))
    playlist = []
    for part, (first,last), us in zip(parts, spans, durations, strict=True):
        stream, = hdr10plus_export.media(part)
        if int(stream["nb_frames"]) != last-first or int(stream["start_pts"]) != 0:
            raise ValueError("Segmenter moved an edit boundary")
        playlist.extend((f"file '{part.name}'", f"duration {us//1_000_000}.{us%1_000_000:06d}"))
    (folder/"parts.txt").write_text("\n".join(playlist)+"\n", encoding="ascii")
    partial = folder/"partial.mp4"
    ffmpeg(["-f", "concat", "-safe", "1", "-auto_convert", "0", "-i", "parts.txt", "-i", master,
            "-map", "0:v:0", "-map", "1:a:0", "-c", "copy", "-tag:v", "hvc1", "-video_track_timescale",
            "120000", "-movie_timescale", "120000", "-avoid_negative_ts", "disabled", partial.name])
    assembled = time.perf_counter()-started
    hdr10plus_export.verify_copy(master, partial, streams, lambda: False)
    expected = decoded_hashes(master)
    if len(expected)!=count:
        raise ValueError("Independent master decode was incomplete")
    for part,(first,last) in zip(parts,spans,strict=True):
        if decoded_hashes(part)!=expected[first:last]:
            raise ValueError("Independent segment decode differs at an edit boundary or within a span")
    partial.replace(folder/"verified-join.mp4")
    result = dict(frames=count, spans=spans, identical_compressed_packets_and_clocks=True,
                  independent_decoded_frames_matched=count, split_and_join_seconds=assembled,
                  verification_seconds=time.perf_counter()-started-assembled)
    (folder/"assembly.json").write_text(json.dumps(result, indent=2)+"\n", encoding="utf8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("project", "master", "folder"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    print(json.dumps(qualify(args.project, args.master, args.folder)))
