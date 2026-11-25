"""Opt-in D3D11 export of validated saved HDR10+ projects with reference fallback."""
from contextlib import contextmanager,suppress
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from threading import Event, Thread
import time

import numpy as np

from native_project_plan import Ineligible, compile_project, run_capture, write_plan, write_sources
import hdr10plus_export
from hdr10plus_index import SIDE_DATA
import hdr10plus_master
import render_engine
import sequences


CREATE_FLAGS = getattr(subprocess,"CREATE_NO_WINDOW",0)
PQ_TAGS = "setparams=range=limited:color_primaries=bt2020:color_trc=smpte2084:colorspace=bt2020nc"


def raw_input(width,height,rate):
    return ["ffmpeg","-nostdin","-v","info","-y","-f","rawvideo","-pixel_format","yuv420p10le",
            "-video_size",f"{width}x{height}","-framerate",rate,"-i","pipe:0"]


def parallel_camera_x265(command):
    """Widen the WPP pool while keeping the qualified frame threads and picture settings."""
    options = command.index("-x265-params") + 1
    fields = command[options].split(":")
    if fields.count("pools=2") != 1 or "frame-threads=2" not in fields:
        raise Ineligible("Unexpected x265 threading settings for the camera-range experiment")
    fields[fields.index("pools=2")] = "pools=8"
    return [*command[:options], ":".join(fields), *command[options+1:]]


def collect(path):
    lines = path.read_text(encoding="utf8",errors="replace").splitlines()
    receipts = [line for line in lines if line.startswith('{"wall_ms":')]
    if len(receipts)!=1:
        raise NativeFailure("The worker returned no complete picture receipt")
    result = json.loads(receipts[0])
    samples = result.pop("samples")
    result["frames"] = len(samples)
    for key in ("work_ms","gpu_ms","upload_ms","readback_ms","write_ms","dispatch_ms",
                "color_gpu_ms","pq_copy_gpu_ms","source_normalization_ms"):
        values = [frame[key] for frame in samples if frame.get(key) is not None]
        if values:
            result[key] = {name:round(float(np.percentile(values,rank)),6) for name,rank in
                           (("median",50),("p95",95),("p99",99),("maximum",100))}
    return result


class NativeFailure(RuntimeError):
    """A native attempt failed before its output could be published."""


def stop(process):
    if process and process.poll() is None:
        with suppress(ProcessLookupError):
            process.kill()
        process.wait(timeout=10)


@contextmanager
def temporary_work(parent,diagnostics=None):
    temp = tempfile.TemporaryDirectory(prefix="native-project-",dir=parent)
    try:
        yield Path(temp.name)
    except Exception:
        # A qualification caller can inspect why its candidate fell back,
        # even when the producer stopped before writing a complete receipt.
        if diagnostics is not None:
            with suppress(OSError):
                diagnostics.mkdir(exist_ok=True)
                for path in Path(temp.name).glob("*.log"):
                    shutil.copyfile(path,diagnostics/path.name)
        raise
    finally:
        for attempt in range(6):
            try:
                temp.cleanup()
                break
            except PermissionError:
                if attempt==5:
                    raise
                time.sleep(.05*(attempt+1))


class ProjectVideo:
    """Supply picture segments as requested by the existing timeline exporter."""

    def __init__(self, program, work, executable, runtime, timeout, cancelled, mode, fault, *, direct_pipe=False, parallel_x265=False):
        self.program = program
        self.work = work
        self.cancelled = cancelled
        self.finished = Event()
        self.deadline = time.monotonic()+timeout
        self.step = 0
        self.producer = self.active = None
        self.encoder_seconds = 0.
        self.encoder_cpu_seconds = 0.
        self.fault_requested = fault is not None
        self.fault_injected = False
        self.reason = None
        self.thread = Thread(target=self.watch, daemon=True)
        self.parallel_x265 = parallel_x265
        self.direct_pipe = direct_pipe and len(program.spans)==1
        self.buffer = None if self.direct_pipe else memoryview(bytearray(1024*1024))
        self.environment = dict(os.environ)
        if runtime:
            self.environment["PATH"] = str(runtime.resolve(strict=True))+os.pathsep+self.environment.get("PATH","")
        self.command = [str(executable.resolve(strict=True)),mode,str(work/"plan.bin"),
                        "@resident:"+str(work/"sources.bin"),"@pq-stream","0","8","0"]
        if fault is not None:
            self.command.append(str(fault))

    def __enter__(self):
        self.thread.start()
        return self

    def watch(self):
        while not self.finished.wait(.1):
            if self.cancelled() or time.monotonic()>=self.deadline:
                self.reason = "The native export was cancelled or timed out"
                stop(self.active)
                stop(self.producer)
                return

    def check(self):
        if self.reason or self.cancelled() or time.monotonic()>=self.deadline:
            raise NativeFailure(self.reason or "The native export was cancelled or timed out")

    def __exit__(self, *_):
        self.finished.set()
        self.thread.join()
        stop(self.active)
        stop(self.producer)
        if self.producer:
            self.producer.stdout.close()
            log=self.work/"native.log"
            if self.fault_requested and log.is_file():
                self.fault_injected = b"Injected D3D11 device removal" in log.read_bytes()

    def __call__(self, command, cwd):
        self.check()
        if "-/filter_complex" not in command or "libx265" not in command or "[finished]" not in command:
            return self.run(command,cwd)
        script = command.index("-/filter_complex")+1
        if not Path(command[script]).name.startswith("hdr_graph_"):
            raise NativeFailure("Unexpected managed picture graph")
        if self.step>=len(self.program.spans):
            raise NativeFailure("The managed renderer requested an unexpected picture segment")
        start,end = self.program.spans[self.step]
        count = int(command[command.index("-frames:v")+1])
        if count!=end-start:
            raise NativeFailure("The managed segment and native program clocks disagree")
        if self.producer is None:
            with (self.work/"native.log").open("wb") as log:
                self.producer = subprocess.Popen(self.command,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
                                                 stderr=log,env=self.environment,creationflags=CREATE_FLAGS)
        width,height = self.program.width,self.program.height
        encoder = raw_input(width,height,str(self.program.fps))
        encoder[1:1] = ["-benchmark","-nostats"]
        if self.direct_pipe:
            encoder.insert(1,"-xerror")
        encoder += ["-map","0:v:0","-vf","setsar=1,"+PQ_TAGS,*command[command.index("-an",script+1):]]
        if self.parallel_x265:
            encoder = parallel_camera_x265(encoder)
        log_path = self.work/f"encoder-{self.step}.log"
        began = time.perf_counter()
        with log_path.open("wb") as log:
            # A single encoder can consume the worker's pipe to EOF. Multiple
            # encoders still need the relay to enforce their segment boundaries.
            source = self.producer.stdout if self.direct_pipe else subprocess.PIPE
            self.active = subprocess.Popen(encoder,stdin=source,stdout=subprocess.DEVNULL,
                                           stderr=log,cwd=cwd,creationflags=CREATE_FLAGS)
            try:
                self.check()
                if not self.direct_pipe:
                    remaining = width*height*3*count
                    while remaining:
                        self.check()
                        read = self.producer.stdout.readinto(self.buffer[:min(len(self.buffer),remaining)])
                        if not read:
                            raise NativeFailure("The native worker stopped before delivering all pictures")
                        self.active.stdin.write(self.buffer[:read])
                        remaining -= read
                    self.active.stdin.close()
                if self.active.wait():
                    raise NativeFailure("The qualified x265 encoder rejected the native segment")
            finally:
                stop(self.active)
                if self.active.stdin is not None:
                    with suppress(BrokenPipeError):
                        self.active.stdin.close()
                self.active = None
        self.encoder_seconds += time.perf_counter()-began
        stats = re.search(rb"utime=([\d.]+)s stime=([\d.]+)s",log_path.read_bytes())
        if stats:
            self.encoder_cpu_seconds += sum(map(float,stats.groups()))
        self.step += 1

    def run(self,command,cwd):
        self.check()
        self.active = subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
                                       stderr=subprocess.PIPE,cwd=cwd,creationflags=CREATE_FLAGS)
        try:
            self.active.communicate()
            if self.active.returncode:
                raise NativeFailure("The managed audio, mux or authoring process failed")
        finally:
            stop(self.active)
            self.active = None

    def own_analysis(self,process):
        self.active = process
        if process and (self.reason or self.cancelled()):
            stop(process)

    def receipt(self):
        self.check()
        if (self.producer is None or self.step!=len(self.program.spans) or
            self.producer.stdout.read(1) or self.producer.wait()):
            raise NativeFailure("The native worker failed its end-of-stream contract")
        receipt = collect(self.work/"native.log")
        if receipt["frames"]!=len(self.program.frames):
            raise NativeFailure("The native worker returned the wrong picture count")
        return receipt


def probe_frames(path,cancelled=lambda:False,timeout=90):
    return json.loads(run_capture(["ffprobe","-v","error","-select_streams","v:0","-show_frames",
                                   "-show_entries","frame=pts:frame_side_data","-of","json",path],
                                  timeout=timeout,cancelled=cancelled)[0])["frames"]


def compare_project(reference, candidate, program, work, cancelled=lambda:False):
    """Compare delivered masters independently of the GPU worker and encoder."""
    baseline = hdr10plus_export.media(reference)
    output = hdr10plus_export.media(candidate)
    probe_timeout=max(90,len(program.frames)//4)
    reference_frames = probe_frames(reference,cancelled,probe_timeout)
    candidate_frames = probe_frames(candidate,cancelled,probe_timeout)
    video_clock = [int(frame["pts"]) for frame in candidate_frames]
    exact_pts = (len(video_clock)==len(program.frames) and video_clock==[int(f["pts"]) for f in reference_frames]
                 and all(pts*program.fps==index*120000 for index,pts in enumerate(video_clock)))
    def declarations(frames):
        return {json.dumps(row,sort_keys=True) for frame in frames for row in hdr10plus_export.static_metadata(frame)}
    static = declarations(reference_frames)
    static_matches = bool(static) and static==declarations(candidate_frames)
    dynamic_count = sum(sum(row["side_data_type"]==SIDE_DATA for row in frame.get("side_data_list",[]))==1
                        for frame in candidate_frames)
    video_keys = ("width","height","time_base","duration_ts","sample_aspect_ratio","chroma_location")
    video_declared = all(baseline[0].get(key)==output[0].get(key) for key in video_keys)
    audio_keys = ("time_base","start_pts","duration_ts","sample_rate","channels","channel_layout")
    audio_declared = len(baseline)==len(output)==2 and all(baseline[1].get(key)==output[1].get(key) for key in audio_keys)
    def pcm(path):
        return run_capture(["ffmpeg","-v","error","-threads","2","-i",path,"-map","0:a:0","-f","s16le","-"],
                           cancelled=cancelled)[0]
    audio_exact = audio_declared and pcm(reference)==pcm(candidate)
    _,errors = run_capture(["ffmpeg","-v","info","-threads","2","-i",reference,"-threads","2","-i",
                            candidate,"-lavfi","psnr=stats_file=psnr.log","-an","-f","null","-"],
                           cwd=work,timeout=max(180,len(program.frames)//2),cancelled=cancelled)
    average = re.search(rb"average:([\d.]+|inf)",errors)
    scores = re.findall(r"psnr_avg:([\d.]+|inf)",(work/"psnr.log").read_text(encoding="ascii"))
    if not average or not scores:
        raise NativeFailure("The independent picture comparison did not produce a score")
    quality = float(average[1])>=50 and len(scores)==len(program.frames) and min(map(float,scores))>=50
    return dict(passed=all((exact_pts,static_matches,video_declared,audio_exact,quality,
                            dynamic_count==len(program.frames))),
                exact_video_pts=exact_pts,static_hdr_matches=static_matches,video_declaration_matches=video_declared,
                hdr10plus_picture_associations=dynamic_count,
                exact_decoded_pcm=audio_exact,audio_endpoint_samples=int(output[1]["duration_ts"]) if audio_declared else None,
                decoded_pq_psnr_db=average[1].decode(),per_frame_psnr_db=scores)


def failed_gop(program,comparison):
    """Allow one bounded picture-only repair after the delivery checks passed."""
    if comparison["passed"]:
        return None
    scores=comparison["per_frame_psnr_db"]
    structural=("exact_video_pts","static_hdr_matches","video_declaration_matches","exact_decoded_pcm")
    if (not all(comparison[key] for key in structural) or
        comparison["hdr10plus_picture_associations"]!=len(program.frames) or
        float(comparison["decoded_pq_psnr_db"])<50 or len(scores)!=len(program.frames)):
        return None
    failures=[index for index,value in enumerate(scores) if float(value)<50]
    for index,(start,end) in enumerate(program.spans):
        if failures and all(start<=frame<end for frame in failures) and end-start<=min(16,len(scores)//4):
            return index
    return None


def repair_gop(state,program,work,index,static,native,cancelled):
    """Replace one closed GOP with managed pictures and rebuild the original clocks."""
    flat=sequences.playback(state)
    render_work=work/"render"
    segments=[(float(start/program.fps),float(end/program.fps)) for start,end in program.spans]
    parts=[render_work/f"segment_{number:05d}.mov" for number in range(len(segments))]
    if not all(part.is_file() for part in parts):
        raise NativeFailure("The original segment set is incomplete")
    start,end=segments[index]
    render_engine.render_range(flat,start,end,parts[index],render_work,runner=native.run)
    render_engine.finish_segments(flat,static,render_work,segments,parts,cancelled=cancelled,runner=native.run)


def export_native(state,destination,reference,executable,runtime,*,authoring=None,timeout=240,
                  cancelled=lambda:False,progress=lambda *_:None,mode="gpu32",fault=None,diagnostics=None,
                  fallback=None,record=None,scratch=None,publish=os.link,repair=True,first_time=False,
                  camera_range=False,parallel_x265=False,keyframe_seek=True):
    destination = destination.resolve()
    if publish is os.link and destination.exists():
        raise FileExistsError("Choose a new output path")
    if cancelled():
        raise RuntimeError("Export cancelled")
    destination.parent.mkdir(parents=True,exist_ok=True)
    if parallel_x265 and not camera_range:
        raise ValueError("The wider x265 pool requires the explicit camera-range policy")
    if first_time != (reference is None) or (camera_range and not first_time):
        raise ValueError("Select either first-export verification or a comparison master")
    if reference is not None:
        reference=reference.resolve(strict=True)
        if reference==destination or (destination.exists() and reference.samefile(destination)):
            raise ValueError("Choose a destination different from the comparison master")
    result = record if record is not None else {}
    result["requested_backend"] = "d3d11"
    result["verification_policy"] = "first-export-sampled" if first_time else "full-master"
    if camera_range:
        result["camera_range_experiment"] = True
        result["keyframe_seek"] = keyframe_seek
        result["requested_x265_pool_workers"] = 8 if parallel_x265 else 2
    started = time.perf_counter()
    publishing = False
    native = None
    try:
        with temporary_work(scratch or destination.parent,diagnostics) as work:
            count = hdr10plus_master.preflight(state)
            program = compile_project(state,work)
            if count!=len(program.frames):
                raise NativeFailure("The planned frame count differs from the HDR10+ contract")
            if first_time:
                from native_project_verification import eligible, source_snapshot, verify_delivery
                flat,contract=eligible(state,program,camera_range=camera_range)
                original_sources=source_snapshot(flat)
                if destination in original_sources or (destination.exists() and
                    any(destination.samefile(source) for source in original_sources)):
                    raise ValueError("Choose a destination different from source media")
            write_plan(work/"plan.bin",program)
            clocks=write_sources(work/"sources.bin",program,cancelled,first_time=first_time,camera_range=camera_range,
                                 keyframe_seek=camera_range and keyframe_seek)
            result.update(frames=count,prepare_seconds=time.perf_counter()-started)
            static,master = work/"static.mp4",work/"master.mp4"
            worker_mode="gpu32-first-export" if first_time else mode
            with ProjectVideo(program,work,executable,runtime,timeout,cancelled,worker_mode,fault,
                              direct_pipe=camera_range,parallel_x265=parallel_x265) as native:
                if camera_range:
                    result["picture_transport"] = "direct" if native.direct_pipe else "python-relay"
                render_started = time.perf_counter()
                render_engine.render(state,static,work/"render",popen=native,cancelled=cancelled,
                                     on_progress=lambda p,m:progress(round(p*.8),m))
                result["native"] = native.receipt()
                result.update(render_seconds=time.perf_counter()-render_started,
                              encoder_feed_and_wait_seconds=native.encoder_seconds,
                              encoder_cpu_seconds=native.encoder_cpu_seconds)
                def author_master():
                    began=time.perf_counter()
                    authored=hdr10plus_master.author(static,master,work,program.fps,count,native.run,
                                                      lambda m,p:progress(p,m),cancelled,native.own_analysis,
                                                      **(authoring or {}))
                    if authored!=count:
                        raise NativeFailure("Unexpected number of authored HDR10+ pictures")
                    result["authored_pictures"]=authored
                    return time.perf_counter()-began

                result["author_seconds"]=author_master()
                result["through_master_seconds"] = time.perf_counter()-started
                verify_started = time.perf_counter()
                if first_time:
                    progress(99,"Checking first-export source clocks, audio, HDR and sampled pictures")
                    result["comparison"]=verify_delivery(flat,contract,master,program,clocks,result["native"],
                                                         work,native.run,cancelled)
                else:
                    progress(99,"Comparing decoded picture, audio and HDR declarations")
                    result["comparison"]=compare_project(reference,master,program,work,cancelled)
                result["verification_seconds"] = time.perf_counter()-verify_started
                index=failed_gop(program,result["comparison"]) if repair and not first_time else None
                if index is not None:
                    result["initial_comparison"]=result["comparison"]
                    began=time.perf_counter()
                    progress(99,"Rebuilding one rejected picture segment with the reference engine")
                    repair_gop(state,program,work,index,static,native,cancelled)
                    result["repair"]={"span":program.spans[index],"render_and_join_seconds":time.perf_counter()-began,
                                      "author_seconds":author_master()}
                    began=time.perf_counter()
                    result["comparison"]=compare_project(reference,master,program,work,cancelled)
                    result["repair"]["verification_seconds"]=time.perf_counter()-began
                if diagnostics:
                    diagnostics.mkdir(exist_ok=True)
                    logs=[work/"native.log",master]
                    if camera_range:
                        logs.extend(sorted(work.glob("encoder-*.log")))
                    if not first_time:
                        logs.append(work/"psnr.log")
                    for path in logs:
                        os.replace(path,diagnostics/path.name)
                    master = diagnostics/"master.mp4"
                if not result["comparison"]["passed"]:
                    raise NativeFailure("The delivered candidate did not match the reference acceptance contract")
                if first_time and source_snapshot(flat)!=original_sources:
                    raise NativeFailure("An original media file changed during the export")
                native.check()
                publishing = True
                publish(master,destination)
                result["delivered_backend"] = "hybrid" if "repair" in result else "d3d11"
    except (OSError,ValueError,AssertionError,RuntimeError,MemoryError,subprocess.SubprocessError) as error:
        if result.get("delivered_backend") in ("d3d11","hybrid"):
            result["scratch_cleanup_failure"] = type(error).__name__
        else:
            result["native_failure"] = type(error).__name__
            if camera_range and isinstance(error,(Ineligible,RuntimeError)):
                result["native_rejection"] = str(error)
            if camera_range and fault is not None:
                result["native_fault_injected"] = native is not None and native.fault_injected
            if publishing or not fallback or cancelled():
                raise
            fallback()
            result["delivered_backend"] = "reference"
    finally:
        result["total_seconds"] = time.perf_counter()-started
    return result
