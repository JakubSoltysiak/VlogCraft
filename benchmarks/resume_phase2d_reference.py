"""Recover verified completed spans from the interrupted Phase 2D reference run."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time

if not __package__:
    root = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(root),str(root/"tests")]

from benchmarks.phase2b_project_export import ProjectConverter
from hdr10plus_fast import author_options
import hdr10plus_master
import native_project_plan
from performance import Resources
import project_store
import render_engine
import server
import timing


VIDEO = re.compile(r"segment_(\d{5})(?:_video|_audio)?\.(?:mov|wav)")


def digest(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file,"sha256").digest()


def verified_span(path,first,last,fps):
    fields = "stream=codec_name,time_base,duration_ts:frame=pts"
    probe = json.loads(native_project_plan.run_capture(
        ["ffprobe","-v","error","-show_entries",fields,"-show_frames","-show_streams","-of","json",
         "-select_streams","v:0",path],timeout=90)[0])
    video, = probe["streams"]
    frames = [int(frame["pts"]) for frame in probe["frames"]]
    if (len(frames)!=last-first or video["codec_name"]!="hevc" or video["time_base"]!="1/120000" or
        any(pts*fps!=index*120000 for index,pts in enumerate(frames))):
        raise ValueError("A saved video span does not have the original exact picture clock")
    audio, = json.loads(native_project_plan.run_capture(
        ["ffprobe","-v","error","-show_entries","stream=codec_name,time_base,duration_ts","-show_streams",
         "-of","json","-select_streams","a:0",path])[0])["streams"]
    samples = timing.sample_at(last,fps)-timing.sample_at(first,fps)
    if (audio["codec_name"],audio["time_base"],audio.get("duration_ts"))!=("pcm_s16le","1/48000",samples):
        raise ValueError("A saved audio span does not have the original sample endpoint")


def recover(project,original,result,author_dll):
    state,recovered = project_store.load(project,server.validate_document)
    if state is None or recovered:
        raise ValueError("Use the intact original qualification project")
    fps = timing.rate(state["output"]["fps"])
    spans = render_engine.frame_spans(state,fps)
    count = hdr10plus_master.preflight(state)
    if count!=300 or len(spans)!=7:
        raise ValueError("The recovery must use the interrupted 300-picture fixture")
    work = result/"timeline"
    work.mkdir(parents=True,exist_ok=False)
    saved = {}
    for index,(first,last) in enumerate(spans):
        source = original/f"segment_{index:05d}.mov"
        if not source.exists():
            continue
        verified_span(source,first,last,fps)
        saved[index] = source
        shutil.copy2(source,work/source.name)
    if set(saved)!=set(range(len(spans)-1)):
        raise ValueError("The interrupted run must contain the six completed spans")
    assembly_start = original/"hdr_graph_segment_00000_video.txt"
    interrupted_start = original/f"hdr_graph_segment_{len(saved):05d}_video.txt"
    completed_elapsed = (interrupted_start.stat().st_ctime_ns-assembly_start.stat().st_ctime_ns)/1e9
    protected = {path:digest(path) for path in [project,*saved.values(),
                                                *[Path(asset["path"]) for asset in state["assets"]]]}
    converter = ProjectConverter(state["output"]["width"],state["output"]["height"],3,1050,
                                 lambda text:print(text,flush=True))
    def run(command,cwd):
        target = Path(command[-1])
        match = VIDEO.fullmatch(target.name)
        if match and int(match[1]) in saved:
            if "-/filter_complex" in command:
                graph = Path(command[command.index("-/filter_complex")+1])
                if graph.read_bytes()!=(original/graph.name).read_bytes():
                    raise ValueError("The saved span graph differs from the current reference")
            return
        converter(command,cwd)
    monitor = Resources(os.getpid(),gpu=False)
    try:
        started=time.perf_counter()
        static = result/"static.mp4"
        render_engine.render(state,static,work,popen=run,on_progress=lambda p,m:print(p,m,flush=True))
        finished=time.perf_counter()
        output = result/"fast"
        output.mkdir()
        authored = hdr10plus_master.author(static,output/"verified.mp4",output,fps,count,render_engine._run,
                                           lambda m,p:print(p,m,flush=True),lambda:False,
                                           **author_options(author_dll,3))
        author_seconds = time.perf_counter()-finished
    finally:
        resources=monitor.finish()
    unchanged = all(digest(path)==expected for path,expected in protected.items())
    if authored!=count or not unchanged:
        raise ValueError("The recovered master did not preserve its input contract")
    elapsed=finished-started
    values=dict(frames=count,resumed_render_seconds=elapsed,author_seconds=author_seconds,
                completed_prefix_pictures=spans[len(saved)][0],completed_prefix_elapsed_from_file_times=completed_elapsed,
                combined_stage_estimate_seconds=completed_elapsed+elapsed+author_seconds,
                resumed_resources=resources,source_integrity=unchanged,resumed_parallel_segments=converter.completed,
                resumed_fallback_segments=converter.fallbacks)
    (result/"report.json").write_text(json.dumps(values,indent=2)+"\n",encoding="utf8")
    print(json.dumps(values))


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project",type=Path)
    parser.add_argument("original_timeline",type=Path)
    parser.add_argument("results",type=Path)
    parser.add_argument("--author-dll",type=Path,required=True)
    args=parser.parse_args()
    recover(args.project.resolve(),args.original_timeline.resolve(),args.results.resolve(),args.author_dll.resolve())
