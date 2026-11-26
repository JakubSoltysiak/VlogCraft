"""Qualify a mixed HDR export with one encoder context across the original cuts."""
import argparse
from contextlib import suppress
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from threading import Event, Lock, Thread
import time

from benchmarks.phase3a_encoder_matrix import picture_slices
from benchmarks.phase3a_segment_assembly import tile_durations
from benchmarks.phase3a_segment_resume import compare_master
from export_raster_options import prepare_still_command
from hdr10plus_fast import author_options
import hdr10plus_master
import hdr_render
from mixed_export import compare_mixed_samples, compile_mixed, verify_video_span
from native_project_plan import write_plan, write_sources
from native_project_render import (
    CREATE_FLAGS, PQ_TAGS, NativeFailure, ProjectVideo, camera_raster_input, collect,
    parallel_camera_x265, raw_input, temporary_work,
)
from native_project_verification import source_snapshot, verify_source_clocks
import render_engine
import sequences
import timing


RELAY_BYTES = 1024*1024


class Processes:
    """Own the encoder, raster, native decoder and analysis children on cancellation."""

    def __init__(self, timeout, cancelled):
        self.deadline = time.monotonic()+timeout
        self.cancelled = cancelled
        self.finished = Event()
        self.aborted = Event()
        self.lock = Lock()
        self.children = set()
        self.analysis = None
        self.watcher = Thread(target=self.watch, daemon=True)

    def __enter__(self):
        self.watcher.start()
        return self

    def stopping(self):
        return self.aborted.is_set() or self.cancelled() or time.monotonic() >= self.deadline

    def check(self):
        if self.stopping():
            raise NativeFailure("The continuous export was cancelled or timed out")

    def watch(self):
        while not self.finished.wait(.1):
            if self.stopping():
                self.abort()
                return

    def start(self, command, **kwargs):
        with self.lock:
            self.check()
            process = subprocess.Popen(command, creationflags=CREATE_FLAGS, **kwargs)
            self.children.add(process)
        return process

    def own_analysis(self, process):
        with self.lock:
            if self.analysis is not None:
                self.children.discard(self.analysis)
            self.analysis = process
            if process is not None:
                self.children.add(process)
                if self.stopping():
                    with suppress(ProcessLookupError):
                        process.kill()

    def wait(self, process, label):
        returncode = process.wait()
        with self.lock:
            self.children.discard(process)
        self.check()
        if returncode:
            raise NativeFailure(f"The continuous {label} process failed")

    def abort(self):
        self.aborted.set()
        with self.lock:
            for process in self.children:
                if process.poll() is None:
                    with suppress(ProcessLookupError):
                        process.kill()

    def __exit__(self, *_):
        self.finished.set()
        self.abort()
        self.watcher.join()
        for process in self.children:
            process.wait(timeout=10)
            for pipe in (process.stdin, process.stdout, process.stderr):
                if pipe is not None:
                    with suppress(OSError):
                        pipe.close()


def relay_exact(reader, writer, count, check, buffer, digest=None):
    """Transfer one bounded interval without reading into the next camera span."""
    remaining = count
    while remaining:
        check()
        chunk = buffer[:min(remaining,len(buffer))]
        read = reader.readinto(chunk)
        if not read:
            raise NativeFailure("A continuous picture source ended before the expected frame")
        chunk = chunk[:read]
        if digest is not None:
            digest.update(chunk)
        if writer.write(chunk) != read:
            raise NativeFailure("The continuous picture consumer accepted a partial write")
        remaining -= read


def file_digest(path, check):
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while data := file.read(RELAY_BYTES):
            check()
            digest.update(data)
    return digest.hexdigest()


def raw_command(prefix, count, *, managed):
    if managed:
        prefix = prefix[:prefix.index("-c:v")]
    else:
        prefix = [*prefix, "-an", "-frames:v", str(count)]
    return [prefix[0], "-xerror", *prefix[1:], "-c:v", "rawvideo", "-threads:v", "1",
            "-pix_fmt", "yuv420p10le", "-f", "rawvideo", "pipe:1"]


def encoder_command(managed, plan, target, pool):
    encoder = raw_input(plan.width, plan.height, str(plan.fps))
    encoder[1:1] = ["-xerror", "-benchmark", "-nostats"]
    suffix = managed[managed.index("-an", managed.index("-/filter_complex")):]
    suffix[suffix.index("-frames:v")+1] = str(len(plan.frames))
    suffix[-1] = str(target)
    command = encoder + ["-map", "0:v:0", "-vf", "setsar=1,"+PQ_TAGS] + suffix
    return parallel_camera_x265(command) if pool == 8 else command


def drain_raster(owner, command, log_path, encoder, count, frame_bytes, buffer, digest, *,
                 producer=None, source_bytes=None):
    with log_path.open("wb") as log:
        raster = owner.start(command, stdin=subprocess.PIPE if producer else subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=log, cwd=log_path.parent)
    source_errors = []
    feeder = None
    if producer is not None:
        def feed():
            try:
                with raster.stdin:
                    relay_exact(producer.stdout, raster.stdin, count*source_bytes, owner.check,
                                memoryview(bytearray(RELAY_BYTES)))
            except (OSError, RuntimeError) as error:
                source_errors.append(error)
                owner.abort()

        feeder = Thread(target=feed, daemon=True)
        feeder.start()
    complete = False
    try:
        with raster.stdout:
            relay_exact(raster.stdout, encoder.stdin, count*frame_bytes, owner.check, buffer, digest)
            if raster.stdout.read(1):
                raise NativeFailure("A continuous raster produced more than its planned pictures")
        owner.wait(raster, "picture raster")
        complete = True
    except (OSError, RuntimeError) as error:
        if source_errors:
            raise NativeFailure("The indexed camera relay failed during continuous export") from source_errors[0]
        raise NativeFailure("The picture raster or encoder pipe failed during continuous export") from error
    finally:
        if not complete:
            owner.abort()
        if feeder:
            feeder.join()
    if source_errors:
        raise NativeFailure("The indexed camera relay failed during continuous export") from source_errors[0]


def render_pictures(flat, plan, scratch, owner, worker, runtime, pool, fast_raster, progress, receipt):
    native = ProjectVideo(plan.camera, scratch, worker, runtime, 0, owner.stopping,
                          "gpu32-camera-raster", None)
    _, first_end = plan.spans[0]
    initial = hdr_render.command(flat, 0., float(first_end/plan.fps), scratch/"encoder-graph.mov", scratch)
    video = scratch/"continuous.mov"
    encoder_args = encoder_command(initial, plan, video, pool)
    receipt["encoder"] = {
        key: encoder_args[encoder_args.index(key)+1]
        for key in ("-frames:v", "-preset", "-crf", "-profile:v", "-pix_fmt", "-x265-params")
    }
    picture_bytes = plan.width*plan.height*3
    receipt["main10_bytes_relayed"] = picture_bytes*len(plan.frames)
    receipt["relay_chunk_bytes"] = RELAY_BYTES
    buffer = memoryview(bytearray(RELAY_BYTES))
    digest = hashlib.sha256()
    producer = None
    camera_spans = iter(plan.camera.spans)
    stages = receipt["spans"] = []
    with (scratch/"continuous-encoder.log").open("wb") as log:
        encoder = owner.start(encoder_args, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                              stderr=log, cwd=scratch)
    began = time.perf_counter()
    for (first, last), provider in zip(plan.spans, plan.routes, strict=True):
        owner.check()
        count = last-first
        start = time.perf_counter()
        held = False
        log_path = scratch/f"raster-{first:06d}.log"
        if provider == "camera":
            if producer is None:
                with (scratch/"native.log").open("wb") as log:
                    producer = owner.start(native.command, env=native.environment, stdin=subprocess.DEVNULL,
                                           stdout=subprocess.PIPE, stderr=log, cwd=scratch)
            camera_first, camera_last = next(camera_spans)
            if camera_last-camera_first != count:
                raise NativeFailure("A continuous camera span disagrees with the output clock")
            prefix, source_bytes = camera_raster_input(plan.camera,camera_first,camera_last,fast=fast_raster)
            drain_raster(owner,raw_command(prefix,count,managed=False),log_path,encoder,count,
                         picture_bytes,buffer,digest,producer=producer,source_bytes=source_bytes)
        else:
            start_time, end_time = float(first/plan.fps), float(last/plan.fps)
            managed = hdr_render.command(flat,start_time,end_time,scratch/f"managed-{first:06d}.mov",scratch)
            if fast_raster:
                command = prepare_still_command(managed,flat,start_time,end_time,scratch)
                held = command != managed
                managed = command
            drain_raster(owner,raw_command(managed,count,managed=True),log_path,encoder,count,
                         picture_bytes,buffer,digest)
        stages.append(dict(first=first,last=last,provider=provider,held=held,
                           raster_feed_and_wait_seconds=time.perf_counter()-start))
        progress(round(2+78*last/len(plan.frames)),f"Fed {last} of {len(plan.frames)} pictures to the encoder")
    if producer is None:
        raise NativeFailure("Continuous mixed export did not use its indexed decoder")
    with producer.stdout:
        if producer.stdout.read(1):
            raise NativeFailure("The indexed decoder returned extra continuous pictures")
    owner.wait(producer,"indexed decoder")
    receipt["native"] = collect(scratch/"native.log")
    if receipt["native"]["frames"] != len(plan.camera.frames):
        raise NativeFailure("The indexed worker receipt has the wrong camera picture count")
    drained = time.perf_counter()
    encoder.stdin.close()
    owner.wait(encoder,"x265 encoder")
    receipt["encoder_drain_seconds"] = time.perf_counter()-drained
    receipt["raster_encoder_seconds"] = time.perf_counter()-began
    receipt["prepared_main10_sha256"] = digest.hexdigest()
    benchmark = re.search(rb"utime=([\d.]+)s stime=([\d.]+)s",(scratch/"continuous-encoder.log").read_bytes())
    if benchmark:
        receipt["encoder_process_cpu_seconds"] = sum(map(float,benchmark.groups()))
    verify_video_span(video,len(plan.frames),owner.stopping)
    return video


def mux_audio(flat, plan, video, static, work, runner):
    """Render each original audio interval and AAC encode the joined PCM once."""
    playlist = work/"audio.txt"
    durations = tile_durations(plan.spans,len(plan.frames),plan.fps)
    entries = []
    for index, ((first,last), duration) in enumerate(zip(plan.spans,durations,strict=True)):
        wav = work/f"audio-{index}.wav"
        runner(render_engine.segment_command(flat,float(first/plan.fps),float(last/plan.fps),
                                             wav,work,"final","audio"),work)
        entries.append(f"file '{wav.name}'\nduration {duration//1_000_000}.{duration%1_000_000:06d}\n")
    playlist.write_text("".join(entries),encoding="ascii")
    runner(["ffmpeg","-v","error","-nostdin","-n","-i",video,"-f","concat","-safe","1",
            "-i",playlist,"-map","0:v:0","-map","1:a:0","-c:v","copy","-tag:v","hvc1",
            "-c:a","aac","-b:a","192k","-video_track_timescale","120000","-movie_timescale","120000",
            "-movflags","+faststart",static],work)


def export_continuous(state, destination, work, worker, runtime, *, reference, reference_sha256,
                      prepared_main10_sha256, pool=2, author_dll=None, progress=lambda *_:None,
                      cancelled=lambda:False, timeout=18000, fast_raster=True, record=None,
                      project_pin=None):
    """Publish only after the exact managed continuous encoder input and master match."""
    if pool not in (2,8) or timeout <= 0:
        raise ValueError("Continuous qualification needs a supported encoder pool and positive timeout")
    destination, work = Path(destination).resolve(), Path(work).resolve()
    reference = Path(reference).resolve(strict=True)
    if destination.exists():
        raise FileExistsError("Choose a new continuous export destination")
    if cancelled():
        raise NativeFailure("The continuous export was cancelled")
    if destination.parent != work and not destination.parent.is_dir():
        raise ValueError("Choose an existing continuous export destination directory")
    flat = sequences.playback(deepcopy(state))
    if any(destination == Path(asset["path"]).resolve() for asset in flat["assets"]):
        raise ValueError("Choose a continuous export path different from the sources")
    sources = source_snapshot(flat,include_hidden_audio=True)
    work.mkdir(parents=True,exist_ok=False)
    if destination.parent.stat().st_dev != work.stat().st_dev:
        raise ValueError("Continuous export scratch and destination must share a volume for publication")
    receipt = record if record is not None else {}
    receipt.update(passed=False,pool=pool,fast_raster=fast_raster)
    began = time.perf_counter()
    try:
        with temporary_work(work,work/"diagnostics") as scratch, Processes(timeout,cancelled) as owner:
            if file_digest(reference,owner.check) != reference_sha256:
                raise ValueError("The pinned uninterrupted reference master changed")
            count = hdr10plus_master.preflight(flat)
            plan = compile_mixed(flat,scratch)
            if len(plan.frames) != count:
                raise NativeFailure("The continuous project has inconsistent frame clocks")
            receipt.update(frames=count, reference_sha256=reference_sha256)
            write_plan(scratch/"plan.bin",plan.camera)
            clocks = write_sources(scratch/"sources.bin",plan.camera,owner.stopping,
                                   first_time=True,camera_range=True,keyframe_seek=True,camera_raster=True)
            receipt["prepare_seconds"] = time.perf_counter()-began

            def run(command,cwd):
                with (scratch/"managed-process.log").open("ab") as errors:
                    process = owner.start(command,cwd=cwd,stdin=subprocess.DEVNULL,
                                          stdout=subprocess.DEVNULL,stderr=errors)
                owner.wait(process,"audio, mux or HDR10+ authoring")

            video = render_pictures(flat,plan,scratch,owner,worker,runtime,pool,fast_raster,progress,receipt)
            if receipt["prepared_main10_sha256"] != prepared_main10_sha256:
                raise NativeFailure("The uninterrupted Main10 encoder input differed from the managed reference")
            stage = time.perf_counter()
            progress(81,"Rendering the original audio graph")
            static, candidate = scratch/"static.mp4", scratch/"master.mp4"
            mux_audio(flat,plan,video,static,scratch,run)
            receipt["audio_mux_seconds"] = time.perf_counter()-stage
            stage = time.perf_counter()
            receipt["authored_pictures"] = hdr10plus_master.author(
                static,candidate,scratch,plan.fps,count,run,lambda m,p:progress(p,m),owner.stopping,
                owner.own_analysis,**(author_options(author_dll) if author_dll else {}))
            receipt["author_seconds"] = time.perf_counter()-stage
            receipt["through_master_seconds"] = time.perf_counter()-began

            stage = time.perf_counter()
            progress(99,"Checking the uninterrupted master against the pinned reference")
            receipt["verified_camera_pictures"] = verify_source_clocks(
                plan.camera,clocks,owner.stopping,camera_raster=True)
            receipt["raw_quality_samples"] = compare_mixed_samples(
                flat,candidate,plan,scratch,owner.stopping,clocks,sample_static_stills=fast_raster)
            comparison = receipt["independent"] = compare_master(reference,candidate,plan,scratch,owner.stopping)
            receipt["equal_coded_pictures"] = sum(
                a == b for a,b in zip(picture_slices(reference,0,count),picture_slices(candidate,0,count),strict=True))
            samples = receipt["raw_quality_samples"]
            receipt["verification_seconds"] = time.perf_counter()-stage
            if (not comparison["passed"] or comparison["exact_decoded_pictures"] != count or
                    comparison["hdr10plus_records_matching_reference"] != count or
                    comparison["audio_endpoint_samples"] != timing.sample_at(count,plan.fps) or
                    receipt["equal_coded_pictures"] != count or not samples or
                    any(row["decoded_to_managed_raw_psnr_db"] is not None and
                        row["decoded_to_managed_raw_psnr_db"] < 50 for row in samples)):
                raise NativeFailure("The uninterrupted master failed its picture, HDR10+ or PCM gate")
            if (source_snapshot(flat,include_hidden_audio=True) != sources or
                    file_digest(reference,owner.check) != reference_sha256 or
                    (project_pin and file_digest(project_pin[0],owner.check) != project_pin[1])):
                raise NativeFailure("A pinned media, project or reference identity changed during export")
            receipt["sources_unchanged"] = True
            receipt["output_sha256"] = file_digest(candidate,owner.check)
            owner.check()
            os.link(candidate,destination)
            receipt["passed"] = True
            progress(100,"Published the verified uninterrupted master")
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as error:
        receipt["failure"] = type(error).__name__
        raise
    finally:
        receipt["wall_seconds"] = time.perf_counter()-began
        (work/"qualification.json").write_text(json.dumps(receipt,indent=2)+"\n",encoding="utf8")
    return receipt


def qualify(project, destination, work, worker, runtime, continuous_control, *, reference_sha256,
            pool=2, author_dll=None, fast_raster=True, timeout=18000):
    import server

    project = project.resolve(strict=True)
    original = project.read_bytes()
    project_hash = hashlib.sha256(original).hexdigest()
    state = server.validate_document(json.loads(original))
    control = json.loads((continuous_control/"control.json").read_bytes())
    fps = timing.rate(state["output"]["fps"])
    expected_spans = [list(span) for span in render_engine.frame_spans(sequences.playback(state),fps)]
    if (not control.get("passed") or not control.get("continuous") or
            control.get("project_hash") != project_hash or control.get("pool") != pool or
            control.get("spans") != expected_spans):
        raise ValueError("The managed continuous control does not match the exact edit or pool")
    return export_continuous(state,destination,work,worker,runtime,reference=continuous_control/"reference.mp4",
                             reference_sha256=reference_sha256,prepared_main10_sha256=control["prepared_main10_sha256"],
                             pool=pool,author_dll=author_dll,fast_raster=fast_raster,timeout=timeout,
                             progress=lambda p,m:print(f"{p}% {m}",flush=True),project_pin=(project,project_hash))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ("project","destination","work","worker","runtime","continuous_control"):
        parser.add_argument(argument,type=Path)
    parser.add_argument("--reference-sha256",required=True)
    parser.add_argument("--pool",type=int,choices=(2,8),default=2)
    parser.add_argument("--author-dll",type=Path)
    parser.add_argument("--timeout",type=float,default=18000)
    parser.add_argument("--reference-raster",dest="fast_raster",action="store_false")
    result = qualify(**vars(parser.parse_args()))
    print(json.dumps({key:result[key] for key in ("frames","passed","wall_seconds")}))
