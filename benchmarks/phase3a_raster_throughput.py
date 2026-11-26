"""Time exact camera rasterization and x265 separately on matching, local Main10 pictures."""
import argparse
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import hdr_render
import native_project_plan as plan
from native_project_render import camera_raster_input, raw_input, parallel_camera_x265, CREATE_FLAGS, PQ_TAGS
from native_project_verification import source_snapshot
import server


def isolate(program, first, last):
    if first < 0 or first >= last or not any(a <= first < last <= b for a,b in program.spans):
        raise ValueError("Select a nonempty range inside one original camera span")
    frames = []
    slot = program.frames[first][1][0][0][8]
    for weight, layers in program.frames[first:last]:
        if weight != -1 or len(layers) != 1 or layers[0][0][8] != slot:
            raise ValueError("This measurement requires one opaque camera")
        packed, geometry = layers[0]
        frames.append((weight, [(packed[:8]+(0,)+packed[9:], geometry)]))
    src = program.sources[slot]
    source = replace(src, requests={i-first:src.requests[i] for i in range(first,last)})
    return replace(program, frames=frames, spans=[(0,len(frames))], sources=[source])


def profile(project, folder, worker, runtime, first, last):
    document = project.read_bytes()
    state = server.validate_document(json.loads(document))
    sources = source_snapshot(state)
    folder = folder.resolve()
    folder.mkdir(parents=True, exist_ok=False)
    if state["output"]["preset"]!="slow" or state["output"]["crf"]!=20:
        raise ValueError("Retain the saved Slow CRF 20 camera settings")
    rows = {}
    def run(label, command, **options):
        start = time.perf_counter()
        with (folder/(label+".log")).open("xb") as log:
            subprocess.run(command, stderr=log, stdin=subprocess.DEVNULL, check=True,
                           creationflags=CREATE_FLAGS, **options)
        rows[label] = {"seconds":time.perf_counter()-start}

    with tempfile.TemporaryDirectory(dir=folder) as temp:
        work = Path(temp)
        prog = isolate(plan.compile_project(state,work,camera_raster=True),first,last)
        n = len(prog.frames)
        rate = prog.fps
        pixels = prog.width*prog.height
        if shutil.disk_usage(work).free < n*pixels*9 + 1024**3:
            raise ValueError("Insufficient scratch for the three diagnostic rasters")
        plan.write_plan(work/"plan.bin",prog)
        plan.write_sources(work/"sources.bin",prog,first_time=True,camera_range=True,keyframe_seek=True,camera_raster=True)
        planes = work/"planes.bin"
        with planes.open("xb") as output:
            run("decode_download",[worker.resolve(strict=True),"gpu32-camera-raster",work/"plan.bin",
                "@resident:"+str(work/"sources.bin"),"@camera-stream","0","8","0"],stdout=output,
                env={**os.environ,"PATH":str(runtime.resolve(strict=True))+os.pathsep+os.environ.get("PATH","")})
        for label,fast in (("control",False),("prepared",True)):
            command, size = camera_raster_input(prog,0,n,fast=fast)
            if planes.stat().st_size != size*n:
                raise ValueError("Unexpected captured camera-plane length")
            command[command.index("pipe:0")] = str(planes)
            path = work/(label+".yuv")
            run(label,command+["-frames:v",str(n),"-an","-c:v","rawvideo","-threads:v","1","-f","rawvideo",path])
            if path.stat().st_size != n*pixels*3:
                raise ValueError("Incomplete Main10 raster")
            with path.open("rb") as stream:
                rows[label]["sha256"] = hashlib.file_digest(stream,"sha256").hexdigest()
        if rows["control"]["sha256"] != rows["prepared"]["sha256"]:
            raise ValueError("Optimized raster changed Main10 encoder input")
        base = hdr_render.command(state,float(first/rate),float(last/rate),work/"out.mov",work)
        command = raw_input(prog.width,prog.height,str(rate))
        command[command.index("pipe:0")] = str(work/"control.yuv")
        command += ["-map","0:v:0","-vf","setsar=1,"+PQ_TAGS,*base[base.index("-an",base.index("-/filter_complex")):]]
        for workers in (2,8):
            args = parallel_camera_x265(command) if workers==8 else command.copy()
            label = f"encoder_pool_{workers}"
            args[-1] = work/(label+".mov")
            run(label,args)
            rows[label]["x265_params"] = args[args.index("-x265-params")+1]
    if source_snapshot(state)!=sources or project.read_bytes()!=document:
        raise ValueError("Original inputs changed during profiling")
    (folder/"stages.json").write_text(json.dumps(dict(frames=n,range=[first,last],stages=rows),indent=2),encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("project","folder","worker","runtime"):
        parser.add_argument(name,type=Path)
    parser.add_argument("--frames",nargs=2,type=int,required=True)
    args = parser.parse_args()
    profile(args.project,args.folder,args.worker,args.runtime,*args.frames)
