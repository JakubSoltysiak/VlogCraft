"""Matched managed export controls, including one uninterrupted x265 context."""
import argparse
from fractions import Fraction
from hashlib import file_digest, sha256
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import numpy as np

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmarks.phase3a_segment_assembly import tile_durations
from hdr10plus_bitstream import packet_records
import hdr10plus_export
import hdr10plus_master
from hdr10plus_fast import author_options
import hdr_render
from native_project_render import CREATE_FLAGS, parallel_camera_x265, raw_input, stop, PQ_TAGS
from native_project_verification import source_snapshot
import render_engine
import server
import timing


PEAK_CODE = 1023
PSNR_FLOOR_DB = 50
CHUNK_SAMPLES = 1024*1024


def read_picture(stream, buffer, frame, label):
    position = 0
    while position < len(buffer):
        length = stream.readinto(buffer[position:])
        if not length:
            raise ValueError(f"The {label} ended before a complete picture {frame}")
        position += length


def main10_errors(raw, decoded, width, height, count, expected_sha256):
    """Measure integer Y/U/V squared error and hash decoded pictures in order."""
    if min(width,height,count) < 1 or width%2 or height%2:
        raise ValueError("Main10 4:2:0 audit requires positive even picture dimensions")
    frame_bytes = width*height*3
    reference = memoryview(bytearray(frame_bytes))
    candidate = memoryview(bytearray(frame_bytes))
    original_values = np.frombuffer(reference,dtype="<u2")
    decoded_values = np.frombuffer(candidate,dtype="<u2")
    delta_buffer = np.empty(min(len(original_values),CHUNK_SAMPLES),dtype=np.int32)
    raw_digest = sha256()
    errors, hashes = [], []
    for frame in range(count):
        read_picture(raw,reference,frame,"prepared Main10 input")
        read_picture(decoded,candidate,frame,"decoded master")
        raw_digest.update(reference)
        hashes.append(sha256(candidate).digest())
        if max(original_values.max(),decoded_values.max()) > PEAK_CODE:
            raise ValueError("The Main10 audit received a sample outside the ten-bit code range")
        squared = 0
        for offset in range(0,len(original_values),len(delta_buffer)):
            stop_at = offset+len(delta_buffer)
            original_chunk = original_values[offset:stop_at]
            delta = delta_buffer[:len(original_chunk)]
            np.subtract(original_chunk,decoded_values[offset:stop_at],out=delta,dtype=np.int32)
            np.square(delta,out=delta)
            squared += int(np.sum(delta,dtype=np.uint64))
        errors.append(squared)
    if raw.read(1) or decoded.read(1):
        raise ValueError("The Main10 audit received extra bytes after the final picture")
    if raw_digest.hexdigest() != expected_sha256:
        raise ValueError("The prepared Main10 input changed before or during the audit")
    return errors, hashes


def quality_report(errors, width, height, spans):
    """Report overall PSNR from total sample error and enforce the floor without rounding."""
    count = len(errors)
    samples = width*height*3//2
    peak_sum = samples*PEAK_CODE**2
    total_error = sum(errors)

    def psnr(signal, error):
        return 10*math.log10(signal/error) if error else "inf"

    scores = [psnr(peak_sum,error) for error in errors]
    below = [frame for frame,error in enumerate(errors) if error*10**(PSNR_FLOOR_DB//10) > peak_sum]
    minimum = max(range(count),key=errors.__getitem__)
    seams = [{"boundary_frame":first,"previous_frame":first-1,
              "previous_psnr_db":scores[first-1],"first_psnr_db":scores[first]}
             for first,_ in spans[1:]]
    return {
        "passed":not below,
        "quality_floor_db":PSNR_FLOOR_DB,
        "sample_peak":PEAK_CODE,
        "samples_per_picture":samples,
        "frames":count,
        "exact_raw_pictures":errors.count(0),
        "minimum_psnr_db":scores[minimum],
        "minimum_psnr_frame":minimum,
        "overall_psnr_db":psnr(count*peak_sum,total_error),
        "per_frame_psnr_db":scores,
        "per_frame_squared_error":errors,
        "pictures_below_floor":len(below),
        "frames_below_floor":below,
        "seams":seams,
    }


def checked_master_clock(master, width, height, rate, count):
    video = hdr10plus_export.media(master)[0]
    if (video["width"],video["height"]) != (width,height):
        raise ValueError("Master dimensions differ from the prepared Main10 input")
    base = Fraction(video["time_base"])
    frames = set()
    with packet_records(master,"v:0") as packets:
        for packet in packets:
            frame = hdr10plus_master.picture_number(packet,base,rate,count)
            if frame in frames or int(packet.get(b"duration",b""))*base*rate != 1:
                raise ValueError("Master packets do not match the prepared Main10 frame clock")
            frames.add(frame)
    if len(frames) != count:
        raise ValueError("Master packet count differs from the prepared Main10 input")


def audit_raw_master(raw, master, output, rate, count, spans, expected_sha256):
    """Independently decode Main10 code values without color or cadence conversion."""
    width,height = output["width"],output["height"]
    checked_master_clock(master,width,height,rate,count)
    with master.open("rb") as file:
        master_digest = file_digest(file,"sha256").hexdigest()
    command = ["ffmpeg","-v","error","-nostdin","-xerror","-noauto_conversion_filters","-threads","4",
               "-i",str(master),"-map","0:v:0","-an","-sn","-dn","-fps_mode","passthrough",
               "-c:v","rawvideo","-pix_fmt","yuv420p10le","-threads:v","1","-f","rawvideo","pipe:1"]
    with (raw.open("rb") as source,tempfile.TemporaryFile() as log,
          subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=log,
                           creationflags=CREATE_FLAGS) as decoder):
        try:
            errors,hashes = main10_errors(source,decoder.stdout,width,height,count,expected_sha256)
            if decoder.wait(timeout=30) or log.seek(0,2):
                raise ValueError("Independent Main10 decode reported an error")
        finally:
            stop(decoder)
    with master.open("rb") as file:
        if file_digest(file,"sha256").hexdigest() != master_digest:
            raise ValueError("A master changed during the independent decode")
    return dict(master_sha256=master_digest,raw_oracle_sha256=expected_sha256,
                compression=quality_report(errors,width,height,spans)),hashes


def audit_masters(raw, uninterrupted, supplied, output, rate, count, spans, oracle_sha256, receipt):
    audits = receipt["raw_audits"] = []
    continuous_hashes = None
    for index, master in enumerate((uninterrupted,*supplied)):
        audit = {"master":"uninterrupted" if index == 0 else f"supplied-{index}"}
        audits.append(audit)
        began = time.perf_counter()
        try:
            result, hashes = audit_raw_master(raw,master,output,rate,count,spans,oracle_sha256)
            audit.update(result)
            if index == 0:
                continuous_hashes = hashes
            elif continuous_hashes is not None:
                different = [frame for frame,(a,b) in enumerate(zip(continuous_hashes,hashes,strict=True)) if a!=b]
                audit["decoded_equality_to_uninterrupted"] = {
                    "matching_pictures":count-len(different),"different_frames":different,
                }
        except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as error:
            audit["error"] = type(error).__name__
            if isinstance(error,(ValueError,RuntimeError)):
                audit["error_reason"] = str(error)
        audit["seconds"] = time.perf_counter()-began
    return all(audit.get("compression",{}).get("passed") for audit in audits)


def managed_control(project, folder, *, continuous=False, pool=2, author_dll=None,
                    audit_raw=False, compare_raw_master=()):
    if (audit_raw or compare_raw_master) and not continuous:
        raise ValueError("Prepared Main10 audits require the uninterrupted managed control")
    original = project.read_bytes()
    state = server.validate_document(json.loads(original))
    sources = source_snapshot(state)
    count = hdr10plus_master.preflight(state)
    o = state["output"]
    rate = timing.rate(o["fps"])
    if (o["preset"], o["crf"], pool in (2, 8)) != ("slow", 20, True):
        raise ValueError("This comparison requires the saved x265 Slow CRF 20 profile")
    spans = render_engine.frame_spans(state, rate)
    folder = folder.resolve()
    folder.mkdir(parents=True, exist_ok=False)
    receipt = dict(frames=count, spans=spans, pool=pool, continuous=continuous,
                   project_hash=sha256(original).hexdigest(), passed=False)
    def run(command, cwd):
        if "libx265" in command:
            if pool == 8:
                command = parallel_camera_x265(command)
            receipt.setdefault("encoder_contexts", []).append({
                key: command[command.index(key)+1]
                for key in ("-frames:v", "-preset", "-crf", "-profile:v", "-pix_fmt", "-x265-params")})
        render_engine._run(command, cwd)

    start = time.perf_counter()
    try:
        with tempfile.TemporaryDirectory(dir=folder) as temp:
            work = Path(temp)
            static = work / "static.mp4"
            if not continuous:
                render_engine.render(state, static, work/"render", popen=run)
            else:
                # This disk-backed oracle measures a single encoder over the exact
                # original per-span managed rasters, with no GOP resets at edits.
                frame_bytes = o["width"]*o["height"]*3
                if shutil.disk_usage(work).free < count*frame_bytes + 1024**3:
                    raise ValueError("Insufficient scratch for the uninterrupted reference")
                raw = work/"source.yuv"
                audio_list = []
                durations = tile_durations(spans, count, rate)
                with raw.open("xb") as writer:
                    for i, ((a, b), us) in enumerate(zip(spans, durations, strict=True)):
                        times = float(a/rate), float(b/rate)
                        command = hdr_render.command(state, *times, work/f"part-{i}.mov", work)
                        args = command[:command.index("-c:v")] + [
                            "-c:v", "rawvideo", "-threads:v", "1", "-f", "rawvideo", "-"]
                        subprocess.run(args, stdout=writer, check=True, stdin=subprocess.DEVNULL,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                        if writer.tell() != b*frame_bytes:
                            raise ValueError("Incomplete managed raster at an edit boundary")
                        audio = work/f"audio-{i}.wav"
                        run(render_engine.segment_command(state, *times, audio, work, "final", "audio"), work)
                        audio_list.append(f"file '{audio.name}'\nduration {us//1_000_000}.{us%1_000_000:06d}\n")
                with raw.open("rb") as reader:
                    receipt["prepared_main10_sha256"] = file_digest(reader, "sha256").hexdigest()
                video = work/"continuous.mov"
                encoder = raw_input(o["width"], o["height"], str(rate))
                encoder[encoder.index("pipe:0")] = str(raw)
                suffix = command[command.index("-an", command.index("-/filter_complex")):]
                suffix[suffix.index("-frames:v")+1] = str(count)
                suffix[-1] = str(video)
                run(encoder + ["-map","0:v:0","-vf","setsar=1,"+PQ_TAGS] + suffix, work)
                playlist = work/"audio.txt"
                playlist.write_text("".join(audio_list), encoding="ascii")
                run(["ffmpeg","-v","error","-nostdin","-n","-i",video,"-f","concat","-safe","1",
                     "-i",playlist,"-map","0:v:0","-map","1:a:0","-c:v","copy","-tag:v","hvc1",
                     "-c:a","aac","-b:a","192k","-video_track_timescale","120000",
                     "-movie_timescale","120000","-movflags","+faststart",static], work)
            receipt["render_seconds"] = time.perf_counter()-start
            master = work/"output.mp4"
            hdr10plus_master.author(static, master, work, rate, count, run, lambda *_:None, lambda:False,
                                    **(author_options(author_dll) if author_dll else {}))
            if source_snapshot(state) != sources or project.read_bytes() != original:
                raise ValueError("The original inputs changed during the reference export")
            os.link(master, folder/"reference.mp4")
            receipt["master_rendered"] = True
            receipt["through_master_seconds"] = time.perf_counter()-start
            if audit_raw or compare_raw_master:
                audit_start = time.perf_counter()
                receipt["raw_audit_passed"] = audit_masters(
                    raw,master,compare_raw_master,o,rate,count,spans,receipt["prepared_main10_sha256"],receipt)
                receipt["raw_audit_seconds"] = time.perf_counter()-audit_start
                if source_snapshot(state)!=sources or project.read_bytes()!=original:
                    raise ValueError("The original inputs changed during the raw quality audit")
                receipt["passed"] = receipt["raw_audit_passed"]
            else:
                receipt["passed"] = True
    finally:
        receipt["seconds"] = time.perf_counter()-start
        (folder/"control.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--continuous", action="store_true")
    parser.add_argument("--pool", type=int, choices=(2, 8), default=2)
    parser.add_argument("--author-dll", type=Path)
    parser.add_argument("--audit-raw",action="store_true",help="Audit every reconstructed picture against its Main10 input")
    parser.add_argument("--compare-raw-master",action="append",type=Path,default=[],
                        help="Also audit this independently encoded master against the same Main10 input")
    args = parser.parse_args()
    result = managed_control(**vars(args))
    print(json.dumps(result))
    if not result["passed"]:
        raise SystemExit(1)
