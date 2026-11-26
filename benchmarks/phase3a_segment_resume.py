"""Qualify independently encoded HDR spans and verify private restart checkpoints."""
import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from fractions import Fraction
from hashlib import sha256
from importlib.metadata import version
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
from threading import Event
import time
from types import SimpleNamespace
import wave

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmarks.phase3a_camera_range import hdr10plus_picture_records
from benchmarks.phase3a_segment_assembly import tile_durations
from export_scratch import lease, plain
from hdr10plus_bitstream import codec_configuration, length_size, packet_records
from hdr10plus_fast import author_options
from native_project_plan import run_capture
from native_project_render import compare_project
from native_project_verification import CAMERA_RANGE_FRAMES, verify_static
import color_management
import hdr10plus_export
import hdr10plus_master
import hdr_render
import project_store
import render_engine
import sequences
import timing


TIMESCALE = 120000
MAX_PICTURES = CAMERA_RANGE_FRAMES
MAX_SPANS = 16
MIN_PSNR = 50
VERSION = 1
ENCODE_TIMEOUT = 40 * 60


def require(condition, message):
    if not condition:
        raise ValueError(message)


def check_cancelled(cancelled):
    if cancelled():
        raise RuntimeError("Segment trial cancelled")


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode("utf8")


def write_record(path, value):
    project_store.atomic_write(path, canonical(value) + b"\n")


def read_record(path):
    try:
        if plain(path) and path.is_file() and path.stat().st_size <= 1024 * 1024:
            value = json.loads(path.read_bytes())
            if isinstance(value, dict):
                return value
    except (ValueError, OSError):
        pass
    return {}


def stat_identity(path):
    stat = path.stat()
    return [stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]


def content_identity(path, cancelled):
    identity = stat_identity(path)
    digest = sha256()
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            check_cancelled(cancelled)
            digest.update(block)
    require(stat_identity(path) == identity, f"File changed while hashing {path.name}")
    return {"stat": identity, "sha256": digest.hexdigest()}


def pin(path, expected, cancelled):
    path = Path(path).resolve(strict=True)
    identity = content_identity(path, cancelled)
    require(isinstance(expected, str) and identity["sha256"] == expected.lower(),
            f"Comparison master SHA-256 does not match {path.name}")
    return path, identity


@dataclass(frozen=True)
class Span:
    first: int
    last: int
    origin: int
    rate: Fraction

    @property
    def pictures(self):
        return self.last - self.first

    @property
    def relative(self):
        return self.first - self.origin, self.last - self.origin

    @property
    def seconds(self):
        return float(self.first / self.rate), float(self.last / self.rate)

    @property
    def binding(self):
        frame_range = [self.first, self.last]
        sample_origin = timing.sample_at(self.origin, self.rate)
        return {"frame_range": frame_range, "reference_frame_range": list(self.relative),
                "audio_sample_range": [timing.sample_at(frame, self.rate) for frame in frame_range],
                "delivery_sample_range": [timing.sample_at(frame, self.rate) - sample_origin
                                          for frame in frame_range]}


def select_spans(state, first, last):
    rate = timing.rate(state["output"]["fps"])
    count = hdr10plus_master.preflight(state)
    require(0 <= first < last <= count and last-first <= MAX_PICTURES,
            f"Select a valid timeline interval of up to {MAX_PICTURES} pictures")
    require(not any(clip.get("transitionIn") or clip["kind"] not in ("video", "image", "audio")
                    for track in state["tracks"] for clip in track["clips"]),
            "Segment trials require a flat timeline with camera, still and audio clips and straight cuts")
    require("maxCLL" in state["output"]["color"], "Supply complete static HDR declarations")
    original = render_engine.frame_spans(state, rate)
    require(any(start == first for start, _ in original), "Start at an original render-span boundary")
    spans = [Span(start, min(end, last), first, rate)
             for start, end in original if first <= start < last]
    require(2 <= len(spans) <= MAX_SPANS, f"Select a range with 2–{MAX_SPANS} authored render spans")
    tile_durations([span.relative for span in spans], last-first, rate)
    return spans


def probe_frames(path, cancelled):
    output, errors = run_capture(["ffprobe", "-v", "error", "-err_detect", "explode", "-threads", "2",
                                 "-select_streams", "v:0", "-show_frames", "-show_entries",
                                 "frame=pts:frame_side_data", "-of", "json", path],
                                timeout=300, cancelled=cancelled)
    require(not errors, f"Independent HEVC decoder reported errors in {path.name}")
    return json.loads(output)["frames"]


def verify_video(path, video, output, rate, count, cancelled):
    expected_duration = count * TIMESCALE / rate
    require((video["width"], video["height"], video["time_base"], int(video["start_pts"]),
             int(video["duration_ts"]), int(video["nb_frames"]), Fraction(video["avg_frame_rate"])) ==
            (output["width"], output["height"], f"1/{TIMESCALE}", 0, expected_duration, count, rate)
            and video.get("codec_tag_string") == "hvc1" and video.get("chroma_location") == "left",
            "Video color, chroma location, dimensions or container clock differs from the plan")
    frames = probe_frames(path, cancelled)
    require(len(frames) == count and all(int(frame["pts"]) * rate == index * TIMESCALE
                                        for index, frame in enumerate(frames)),
            "Decoded video clock differs from the plan")
    contract = output["color"]
    require(verify_static(frames, contract) and verify_static(frames[:1], contract),
            "Static mastering metadata or content-light levels differ from the plan")


def closed_idr(source, packet, width):
    """Require an IDR as the first VCL NAL of the random-access packet."""
    if b"K" not in packet[b"flags"]:
        return False
    position = int(packet[b"pos"])
    end = position + int(packet[b"size"])
    source.seek(position)
    while source.tell() < end:
        prefix = source.read(width + 2)
        size = int.from_bytes(prefix[:width], "big")
        following = source.tell() + size - 2
        require(len(prefix) == width + 2 and size >= 2 and following <= end, "Invalid HEVC NAL length")
        nal_type = (prefix[width] >> 1) & 63
        if nal_type < 32:
            return nal_type in (19, 20)
        source.seek(following)
    return False


def video_packets(path, video, rate, count, cancelled, *, independent=False):
    """Return packet payloads indexed by exact presentation frame."""
    base = Fraction(video["time_base"])
    ticks = int(Fraction(1) / rate / base)
    result = {}
    previous_dts = None
    with packet_records(path, "v:0", hashes=True) as packets, path.open("rb") as source:
        for packet in packets:
            check_cancelled(cancelled)
            frame = hdr10plus_master.picture_number(packet, base, rate, count)
            dts = int(packet[b"dts"])
            if previous_dts is None and independent:
                require(frame == 0 and closed_idr(source, packet, length_size(video)),
                        "Segment does not start with a closed HEVC IDR")
            require(frame not in result and dts <= int(packet[b"pts"]) and
                    (previous_dts is None or dts - previous_dts == ticks),
                    "Packet decoding or presentation clock is discontinuous")
            result[frame] = packet[b"data_hash"].decode("ascii")
            previous_dts = dts
    require(len(result) == count, "Video packet count differs from the plan")
    return [result[index] for index in range(count)]


def decode_hashes(path, cancelled):
    raw, _ = run_capture(["ffmpeg", "-v", "error", "-xerror", "-threads", "2", "-i", path,
                          "-map", "0:v:0", "-fps_mode", "passthrough", "-pix_fmt", "yuv420p10le",
                          "-f", "framehash", "-hash", "sha256", "-"], timeout=300, cancelled=cancelled)
    return [line.rsplit(b",", 1)[1].strip().decode("ascii") for line in raw.splitlines()
            if line and not line.startswith(b"#")]


def score_span(reference, candidate, span, work, cancelled):
    first, last = span.relative
    graph = (f"[0:v]trim=start_frame={first}:end_frame={last},setpts=PTS-STARTPTS[ref];"
             "[ref][1:v]psnr=stats_file=segment-psnr.log:shortest=1")
    _, logs = run_capture(["ffmpeg", "-v", "info", "-xerror", "-filter_complex_threads", "2",
                           "-threads", "2", "-i", reference, "-threads", "2", "-i", candidate,
                           "-filter_complex", graph, "-an", "-f", "null", "-"],
                          timeout=300, cwd=work, cancelled=cancelled)
    scores = re.findall(r"psnr_avg:([\d.]+|inf)", (work / "segment-psnr.log").read_text("ascii"))
    average = re.search(rb"average:([\d.]+|inf)", logs)
    require(average and len(scores) == span.pictures and float(average[1]) >= MIN_PSNR and
            min(map(float, scores)) >= MIN_PSNR, f"Segment {span.first}:{span.last} fails the {MIN_PSNR} dB floor")
    return {"average_psnr_db": average[1].decode(), "min_psnr_db": min(scores, key=float),
            "exact_decoded_pictures": scores.count("inf")}


def reusable(part, receipt, binding, pictures, cancelled):
    saved = read_record(receipt)
    result = saved.get("verification")
    if (saved.get("binding") != binding or not isinstance(result, dict) or
            result.get("state") != "passed" or result.get("picture_count") != pictures or
            result.get("closed_idr") is not True or result.get("exact_video_pts") is not True or
            result.get("static_hdr_matches") is not True or result.get("min_psnr_db") != "inf" or
            result.get("exact_decoded_pictures") != pictures or not part.is_file() or not plain(part)):
        return None
    if not all(key in result for key in ("encode_seconds", "verify_seconds", "codec_configuration_sha256")):
        return None
    for metric in ("packet_sha256", "decoded_sha256"):
        hashes = result.get(metric)
        if not isinstance(hashes, list) or len(hashes) != pictures:
            return None
    return result if saved.get("artifact") == content_identity(part, cancelled)["sha256"] else None


def build_segment(state, span, index, lane, spec_digest, reference, workers, cancelled, mixed=None):
    part = lane / f"video-{index:03d}.mp4"
    receipt = part.with_suffix(".json")
    binding = {"spec_sha256": spec_digest, "workers": workers, **span.binding}
    existing = reusable(part, receipt, binding, span.pictures, cancelled)
    if existing:
        return part, existing, True

    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix=f"video-{index:03d}-", dir=lane, ignore_cleanup_errors=True) as directory:
        work = Path(directory)
        pending = work / "candidate.mp4"
        command = render_engine.segment_command(state, *span.seconds, pending, work, "final", "video")
        if mixed:
            from benchmarks.phase3a_segment_provider import encode
            # Keep x265's hvcC user-data string identical across FFmpeg log levels.
            # This preserves the complete byte-for-byte codec configuration gate.
            params = command.index("-x265-params") + 1
            command[params] += ":log-level=0"
            logs, provider = encode(state,span,command,work,*mixed,ENCODE_TIMEOUT,cancelled)
        else:
            _, logs = run_capture(command, timeout=ENCODE_TIMEOUT, cancelled=cancelled, cwd=work)
            provider = {"provider":"managed"}
        encoded = time.perf_counter()
        video, = hdr10plus_export.media(pending)
        verify_video(pending, video, state["output"], span.rate, span.pictures, cancelled)
        packets = video_packets(pending, video, span.rate, span.pictures, cancelled, independent=True)
        quality = score_span(reference, pending, span, work, cancelled)
        require(quality["exact_decoded_pictures"] == span.pictures,
                f"Segment {span.first}:{span.last} differs from the matched authored-span encode")
        pictures = decode_hashes(pending, cancelled)
        require(len(pictures) == span.pictures, "Independent segment decode was incomplete")
        result = {"state": "passed", "picture_count": span.pictures, "closed_idr": True,
                  "exact_video_pts": True, "static_hdr_matches": True,
                  "codec_configuration_sha256": sha256(codec_configuration(video)).hexdigest(),
                  "packet_sha256": packets, "decoded_sha256": pictures, **quality, **provider,
                  "encode_seconds": encoded - started,
                  "verify_seconds": time.perf_counter() - encoded}
        digest = content_identity(pending, cancelled)["sha256"]
        check_cancelled(cancelled)
        with pending.open("r+b") as artifact:
            os.fsync(artifact.fileno())
        os.replace(pending, part)
        write_record(receipt, {"binding": binding, "artifact": digest, "verification": result,
                               "encoder_options": [str(value) for value in command[command.index("-c:v"):-1]],
                               "encoder_log": logs.decode("utf8", errors="replace")[-8000:],
                               "verified_at_unix": time.time()})
        return part, result, False


def process_spans(spans, workers, segment, stop_after, cancelled, stop):
    if workers == 1:
        results = []
        for index, span in enumerate(spans):
            check_cancelled(cancelled)
            results.append(segment(span, index))
            if stop_after and sum(not reused for _, _, reused in results) == stop_after:
                break
        return results

    results = {}
    remaining = iter(enumerate(spans))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        active = {}

        def admit():
            item = next(remaining, None)
            if item is not None:
                index, span = item
                active[pool.submit(segment, span, index)] = index

        for _ in range(workers):
            admit()
        try:
            while active:
                check_cancelled(cancelled)
                completed, _ = wait(active, timeout=.2, return_when=FIRST_COMPLETED)
                for task in completed:
                    results[active.pop(task)] = task.result()
                for _ in completed:
                    admit()
        except BaseException:
            stop.set()
            raise
    return [results[index] for index in range(len(spans))]


def playlist(path, parts, durations):
    lines = [f"file '{part.name}'\nduration {us//1_000_000}.{us%1_000_000:06d}\n"
             for part, us in zip(parts, durations, strict=True)]
    project_store.atomic_write(path, "".join(lines).encode("ascii"))


def verify_audio(path, audio, samples, cancelled):
    require((audio["time_base"], int(audio["start_pts"]), int(audio["duration_ts"]), audio["sample_rate"],
             audio["channels"], audio["channel_layout"]) == ("1/48000", 0, samples, "48000", 2, "stereo"),
            "AAC declarations or sample endpoint differ from the plan")
    pcm, _ = run_capture(["ffmpeg", "-v", "error", "-xerror", "-threads", "2", "-i", path,
                          "-map", "0:a:0", "-f", "s16le", "-"], timeout=300, cancelled=cancelled)
    # AAC packets contain complete coded blocks. The MP4 presentation ends
    # at duration_ts, so compare the available decoded PCM through that sample.
    require(samples*4 <= len(pcm) < (samples+1024)*4 and len(pcm) % 4 == 0,
            "Decoded AAC does not cover the declared PCM endpoint")
    return len(pcm)//4


def assemble(state, spans, results, lane, work, authoring, cancelled, report, progress):
    rate = spans[0].rate
    count = spans[-1].last - spans[0].first
    samples = spans[-1].binding["delivery_sample_range"][-1]
    durations = tile_durations([span.relative for span in spans], count, rate)
    parts = [part for part, _, _ in results]
    checks = [check for _, check, _ in results]
    require(len({check["codec_configuration_sha256"] for check in checks}) == 1,
            "Encoded spans have incompatible HEVC codec configurations")

    def runner(command, cwd):
        return run_capture(command, timeout=ENCODE_TIMEOUT, cancelled=cancelled, cwd=cwd)

    began = time.perf_counter()
    audio_parts = []
    for index, span in enumerate(spans):
        audio = work / f"audio-{index:03d}.wav"
        runner(render_engine.segment_command(state, *span.seconds, audio, work, "final", "audio"), work)
        first_sample, last_sample = span.binding["audio_sample_range"]
        with wave.open(str(audio)) as source:
            require((source.getframerate(), source.getnchannels(), source.getsampwidth(), source.getnframes()) ==
                    (48000, 2, 2, last_sample - first_sample), "Managed PCM interval differs from the audio plan")
        audio_parts.append(audio)
    audio_list = work / "audio.txt"
    playlist(audio_list, audio_parts, durations)
    report["audio_graph_seconds"] = time.perf_counter() - began

    began = time.perf_counter()
    video_list = lane / "picture-concat.txt"
    playlist(video_list, parts, durations)
    clock = hdr_render.final_clock(video_list, rate, count, cancelled)
    static = work / "static.mp4"
    runner(["ffmpeg", "-v", "error", "-nostdin", "-n", "-f", "concat", "-safe", "1", "-auto_convert", "0",
            "-i", video_list, "-f", "concat", "-safe", "1", "-i", audio_list, "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "copy", *clock, "-c:a", "aac", "-b:a", "192k", "-tag:v", "hvc1",
            "-video_track_timescale", str(TIMESCALE), "-movie_timescale", str(TIMESCALE),
            "-movflags", "+faststart", static], work)
    report["join_and_audio_encode_seconds"] = time.perf_counter() - began
    video, _ = hdr10plus_export.media(static)
    packets = video_packets(static, video, rate, count, cancelled)
    require(packets == [digest for check in checks for digest in check["packet_sha256"]],
            "Assembly changed video packet payloads or their presentation positions")

    began = time.perf_counter()
    candidate = work / "candidate.mp4"
    hdr10plus_master.author(static, candidate, work, rate, count, runner,
                            lambda message, _: progress(message), cancelled, **authoring)
    report["hdr10plus_author_and_verify_seconds"] = time.perf_counter() - began
    video, audio = hdr10plus_export.media(candidate)
    verify_video(candidate, video, state["output"], rate, count, cancelled)
    require(sha256(codec_configuration(video)).hexdigest() == checks[0]["codec_configuration_sha256"],
            "Final HDR10+ master has different HEVC codec configuration")
    report["decoded_audio_samples_including_padding"] = verify_audio(candidate, audio, samples, cancelled)
    report["audio_endpoint_samples"] = samples
    pictures = decode_hashes(candidate, cancelled)
    require(pictures == [digest for check in checks for digest in check["decoded_sha256"]],
            "Final decode differs from isolated segment pictures")
    report["isolated_and_joined_decode_match"] = len(pictures)
    report["exact_assembled_video_packets"] = len(packets)
    report["seams"] = [span.first for span in spans[1:]]
    return candidate


def compare_master(reference, candidate, program, work, cancelled):
    result = compare_project(reference, candidate, program, work, cancelled)
    records = hdr10plus_picture_records(candidate, program)
    expected = hdr10plus_picture_records(reference, program)
    result["hdr10plus_records_matching_reference"] = sum(records[index] == expected[index] for index in records)
    scores = result["per_frame_psnr_db"]
    result["exact_decoded_pictures"] = scores.count("inf")
    result["minimum_psnr_db"] = min(scores, key=float)
    if result["exact_decoded_pictures"] == len(program.frames):
        result["passed"] &= records == expected
    return result


def published(lane, spec_digest, cancelled):
    if not lane.is_dir() or not plain(lane):
        return None
    path, receipt = lane / "verified.mp4", read_record(lane / "run.json")
    if (receipt.get("state") == "passed" and receipt.get("spec_sha256") == spec_digest and
            path.is_file() and plain(path) and receipt.get("output_sha256") == content_identity(path, cancelled)["sha256"]):
        return receipt
    return None


def qualify(project, folder, first, last, reference, reference_sha256, *, continuous_reference=None,
            continuous_sha256=None, author_dll=None, workers=1, stop_after=None, cancelled=lambda: False,
            progress=print, mixed_worker=None, runtime=None):
    import server

    require(workers in (1, 2), "Select one or two segment workers")
    require(bool(mixed_worker)==bool(runtime), "Select both the mixed camera worker and its runtime")
    require(stop_after is None or (workers == 1 and stop_after > 0), "A stop point requires serial workers")
    require(bool(continuous_reference) == bool(continuous_sha256), "Pin the continuous comparison master SHA-256")
    require(workers == 1 or continuous_reference, "Two workers require an independently encoded continuous master")
    stop = Event()

    def stopping():
        return stop.is_set() or cancelled()

    started = time.perf_counter()
    project = Path(project).resolve(strict=True)
    original = content_identity(project, stopping)
    project_bytes = project.read_bytes()
    document = json.loads(project_bytes)
    require(document.get("version") == 4 and sha256(project_bytes).hexdigest() == original["sha256"],
            "Use a pinned v4 saved project with exact source ticks")
    state = sequences.playback(server.validate_document(document))
    spans = select_spans(state, first, last)
    require(stop_after is None or stop_after <= len(spans), "The stop point exceeds the number of spans")
    assets = {clip["assetId"] for track in state["tracks"] for clip in track["clips"] if clip.get("assetId")}
    dependencies = set()
    for asset in state["assets"]:
        if asset["id"] in assets:
            path = Path(asset["path"]).resolve(strict=True)
            # Read the file whose identity is pinned even if a directory
            # junction or symbolic link is retargeted while a worker runs.
            asset["path"] = str(path)
            dependencies.add(path)
    reference, archived = pin(reference, reference_sha256, stopping)
    pins = {project: original, reference: archived}
    continuous = None
    if continuous_reference:
        continuous, identity = pin(continuous_reference, continuous_sha256, stopping)
        require(continuous != reference and not continuous.samefile(reference),
                "Use an independently produced uninterrupted comparison encode")
        receipt_path = continuous.parent / "control.json"
        control = read_record(receipt_path)
        contexts = control.get("encoder_contexts", [])
        require(control.get("passed") and control.get("continuous") and control.get("pool") == 2 and
                control.get("project_hash") == original["sha256"] and control.get("frames") == last-first and
                len(contexts) == 1 and int(contexts[0].get("-frames:v", 0)) == last-first and
                contexts[0].get("-preset") == state["output"]["preset"] and
                contexts[0].get("-crf") == str(state["output"]["crf"]) and
                len(control.get("prepared_main10_sha256","")) == 64,
                "The uninterrupted encoder receipt does not match the saved edit and range")
        pins[receipt_path] = content_identity(receipt_path, stopping)
        pins[continuous] = identity
    if author_dll:
        dependencies.add(Path(author_dll).resolve(strict=True))
    mixed = None
    if mixed_worker:
        mixed = (Path(mixed_worker).resolve(strict=True), Path(runtime).resolve(strict=True))
        dependencies.add(mixed[0])
        dependencies.update(mixed[1].glob("*.dll"))
    tools = [Path(shutil.which(tool) or tool).resolve(strict=True) for tool in ("ffmpeg", "ffprobe")]
    sources = {path: content_identity(path, stopping) for path in sorted(dependencies | set(tools))}
    pins.update(sources)
    tool_versions = [run_capture([tool, "-version"], cancelled=stopping)[0].decode().splitlines()[0] for tool in tools]
    root = Path(__file__).resolve().parents[1]
    implementation = {name: sha256((root / name).read_bytes()).hexdigest() for name in
                      ("benchmarks/phase3a_segment_resume.py", "benchmarks/phase3a_segment_assembly.py",
                       "benchmarks/phase3a_camera_range.py", "animation.py", "color_management.py", "hdr_render.py",
                       "hdr_layers.py", "hdr10plus_authoring.py", "hdr10plus_bitstream.py", "hdr10plus_export.py",
                       "hdr10plus_fast.py", "hdr10plus_master.py", "native_project_plan.py", "native_project_render.py",
                       "native_project_verification.py", "render_engine.py", "sequences.py", "timeline_transitions.py",
                       "timing.py", "video_effects.py","mixed_export.py","export_raster_options.py",
                       "benchmarks/phase3a_segment_provider.py")}
    spec = {"version": VERSION, "project": str(project), "pins": {str(path): value for path, value in pins.items()},
            "reference": str(reference), "continuous_reference": str(continuous) if continuous else None,
            "picture_provider": "indexed-camera-and-prepared-stills" if mixed else "managed",
            "output": state["output"], "frame_rate": str(spans[0].rate), "time_base": f"1/{TIMESCALE}",
            "spans": [span.binding for span in spans], "tool_versions": tool_versions,
            "x265_parameters": color_management.x265_metadata(state["output"]["color"]),
            "filter_threads_per_worker": min(4, os.cpu_count() or 1), "pillow_version": version("pillow"),
            "implementation": implementation, "quality_floor_db": MIN_PSNR}
    spec_digest = sha256(canonical(spec)).hexdigest()
    program = SimpleNamespace(fps=spans[0].rate, frames=range(last-first))
    folder = Path(folder).absolute()
    require(all(not path.is_relative_to(folder.resolve()) for path in pins),
            "Keep the project, source media, tools and masters outside the trial directory")
    folder.mkdir(parents=True, exist_ok=True)
    require(plain(folder) and folder.is_dir(), "Use a local trial directory")
    lock = folder / ".lease"
    require((not lock.exists() and not lock.is_symlink()) or
            (plain(lock) and lock.is_file() and lock.stat().st_nlink == 1),
            "Invalid trial lock")
    with lease(lock) as owned:
        require(owned, "The segment trial already has an active owner")
        settings = folder / "session.json"
        if not settings.exists():
            require(set(folder.iterdir()) == {lock}, "Use an empty directory for a new trial")
            write_record(settings, spec)
        require(read_record(settings) == spec, "The trial's pinned identities or configuration changed")
        serial = folder / "serial"
        if workers == 2:
            receipt = published(serial, spec_digest, stopping)
            require(receipt and receipt.get("continuous_comparison", {}).get("passed"),
                    "The matching serial trial must pass the uninterrupted comparison before enabling two workers")
            import psutil
            peak = receipt.get("sampled_peak_tree_bytes",0)
            require(peak>0 and psutil.virtual_memory().available >= 2*peak,
                    "Insufficient available memory for two measured serial working sets")
        lane = serial if workers == 1 else folder / "two-workers"
        lane.mkdir(exist_ok=True)
        require(plain(lane) and lane.is_dir(), "Use a local checkpoint directory")
        if receipt := published(lane, spec_digest, stopping):
            return receipt
        require(not (lane / "verified.mp4").exists(), "The existing qualified artifact failed its receipt")
        report = {"state": "running", "spec_sha256": spec_digest, "workers": workers, "frames": last-first,
                  "pinning_seconds": time.perf_counter() - started}
        write_record(lane / "run.json", report)

        def process(span, index):
            check_cancelled(stopping)
            value = build_segment(state, span, index, lane, spec_digest, reference, workers, stopping, mixed)
            progress(f"{span.first}:{span.last} {'reused' if value[2] else 'verified'}")
            return value

        try:
            video, audio = hdr10plus_export.media(reference)
            verify_video(reference, video, state["output"], program.fps, last-first, stopping)
            verify_audio(reference, audio, spans[-1].binding["delivery_sample_range"][-1], stopping)
            began = time.perf_counter()
            from benchmarks.phase3a_segment_provider import measure_tree
            with measure_tree(report):
                results = process_spans(spans, workers, process, stop_after, stopping, stop)
            report["segment_seconds"] = time.perf_counter() - began
            report["segments"] = [{"frames": span.binding["frame_range"], "reused": reused, **{
                key: info[key] for key in ("encode_seconds", "verify_seconds", "min_psnr_db",
                                           "exact_decoded_pictures","provider","verified_source_pictures",
                                           "peak_gpu_local_bytes") if key in info}}
                for span, (_, info, reused) in zip(spans, results)]
            if stop_after and sum(not reused for _, _, reused in results) == stop_after:
                report["state"] = "stopped"
                return report
            with tempfile.TemporaryDirectory(prefix="assembly-", dir=lane, ignore_cleanup_errors=True) as directory:
                work = Path(directory)
                authoring = author_options(author_dll) if author_dll else {}
                candidate = assemble(state, spans, results, lane, work, authoring, stopping, report, progress)
                began = time.perf_counter()
                report["authored_span_comparison"] = compare_master(reference, candidate, program, work, stopping)
                report["authored_span_comparison_seconds"] = time.perf_counter() - began
                require(report["authored_span_comparison"]["passed"] and
                        report["authored_span_comparison"]["exact_decoded_pictures"] == last-first,
                        "Final output differs from the authored-span oracle")
                if continuous:
                    began = time.perf_counter()
                    report["continuous_comparison"] = compare_master(continuous, candidate, program, work, stopping)
                    report["continuous_comparison_seconds"] = time.perf_counter() - began
                    require(report["continuous_comparison"]["passed"],
                            "Final output fails the uninterrupted encoder comparison")
                began = time.perf_counter()
                require(all(content_identity(path, stopping) == value for path, value in pins.items()),
                        "A pinned project, source, comparison master or tool changed during qualification")
                report["source_recheck_seconds"] = time.perf_counter() - began
                check_cancelled(stopping)
                report["output_sha256"] = content_identity(candidate, stopping)["sha256"]
                with candidate.open("r+b") as artifact:
                    os.fsync(artifact.fileno())
                report["state"] = "passed"
                report["total_seconds"] = time.perf_counter() - started
                write_record(lane / "run.json", report)
                check_cancelled(stopping)
                os.link(candidate, lane / "verified.mp4")
            return report
        except BaseException as error:
            report.update(state="cancelled" if cancelled() or isinstance(error, KeyboardInterrupt) else "rejected",
                          error=str(error))
            raise
        finally:
            if report["state"] != "passed":
                report["total_seconds"] = time.perf_counter() - started
                write_record(lane / "run.json", report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("work", type=Path)
    parser.add_argument("--frames", type=int, nargs=2, metavar=("FIRST", "LAST"), required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--reference-sha256", required=True)
    parser.add_argument("--continuous-reference", type=Path)
    parser.add_argument("--continuous-sha256")
    parser.add_argument("--author-dll", type=Path)
    parser.add_argument("--mixed-worker", type=Path)
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--workers", type=int, choices=(1, 2), default=1)
    parser.add_argument("--stop-after", type=int, help="Pause after writing this many new serial checkpoints")
    args = parser.parse_args()
    result = qualify(args.project, args.work, *args.frames, args.reference, args.reference_sha256,
                     continuous_reference=args.continuous_reference, continuous_sha256=args.continuous_sha256,
                     author_dll=args.author_dll, workers=args.workers, stop_after=args.stop_after,
                     progress=lambda message: print(message, flush=True),mixed_worker=args.mixed_worker,runtime=args.runtime)
    print(json.dumps(result))
