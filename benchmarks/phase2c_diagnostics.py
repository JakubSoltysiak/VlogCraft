"""Separate source decode costs and test the pre-encode metadata assumption."""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from time import perf_counter

import numpy as np

from render_phase2 import ROOT, SCENARIOS, clips_for, power, write_plan
from render_phase2_stream import normalized_loops

sys.path[:0] = [str(ROOT),str(ROOT/"tests")]
from hdr10plus_authoring import decoded_frames
from phase2c_author import NativeStatistics, windows_output_pipe
from profile_phase2c_author import PQ_RGB


FLAGS = getattr(subprocess,"CREATE_NO_WINDOW",0)


def profile_decode(sources, count):
    profiles=[]
    for source in sources:
        rows={}
        for route, device, output in (
            ("demux_packet_copy",[],["-c:v","copy"]),
            ("software_decode",[],["-c:v","wrapped_avframe"]),
            ("d3d11_decode",["-hwaccel","d3d11va","-hwaccel_output_format","d3d11"],["-c:v","wrapped_avframe"]),
        ):
            start=perf_counter()
            process=subprocess.run(["ffmpeg","-v","info","-nostats","-benchmark","-nostdin","-threads","4",
                *device,"-i",str(source),"-map","0:v:0","-an","-frames:v",str(count),*output,"-f","null","-"],
                capture_output=True,timeout=120,creationflags=FLAGS)
            seconds=perf_counter()-start
            cpu=re.search(rb"utime=([\d.]+)s stime=([\d.]+)s",process.stderr)
            frames=re.findall(rb"frame=\s*(\d+)",process.stderr)
            rows[route]=dict(exit_code=process.returncode,wall_seconds=seconds,
                             cpu_seconds=sum(map(float,cpu.groups())) if cpu else None,
                             output_count=int(frames[-1]) if frames else None,
                             resident_format_reported=b"Video: wrapped_avframe, d3d11" in process.stderr)
        profiles.append(rows)
    return dict(frames=count,profiles=profiles)


def preencode(executable, master, library, parent):
    """Compare raw compositor input to the actual encoded picture contract."""
    fixture=replace(next(case for case in SCENARIOS if case.name=="uhd-mixed"),dissolve=True)
    count=24
    w,h=fixture.width,fixture.height
    analyze=NativeStatistics(library).payload
    with tempfile.TemporaryDirectory(dir=parent) as folder:
        root=Path(folder)
        source,slots,_=normalized_loops(root,fixture)
        plan=root/"plan.bin"
        write_plan(plan,fixture,clips_for(fixture,count),count,precise_edges=True,
                   source_slots=slots,dissolve_window=(count//3,count//3+count//6))
        raw=root/"gpu-main10.yuv"
        with raw.open("wb") as output:
            subprocess.run([str(executable),"gpu32",str(plan),str(source),"@pq-stream","0","8","0"],
                           stdout=output,stderr=subprocess.PIPE,timeout=90,check=True,creationflags=FLAGS)
        if raw.stat().st_size!=w*h*3*count:
            raise ValueError("Unexpected packed pre-encode frame count")
        pre=[]
        args=["ffmpeg","-v","error","-nostdin","-f","rawvideo","-pixel_format","yuv420p10le",
              "-video_size",f"{w}x{h}","-framerate","60","-i",str(raw),"-vf",PQ_RGB,
              "-c:v","rawvideo","-threads","1","-f","rawvideo","pipe:1"]
        with windows_output_pipe() as (source_pipe,sink):
            with subprocess.Popen(args,stdout=sink,stderr=subprocess.DEVNULL,creationflags=FLAGS) as child:
                sink.close()
                try:
                    for _ in range(count):
                        data=source_pipe.read(w*h*6)
                        if len(data)!=w*h*6:
                            raise ValueError("Incomplete pre-encode picture")
                        pre.append(analyze(np.frombuffer(data,dtype="<u2").reshape(3,h,w)))
                    if source_pipe.read(1) or child.wait(timeout=10):
                        raise ValueError("Unexpected pre-encode decoder output")
                finally:
                    if child.poll() is None:
                        child.kill()
                        child.wait()
        with decoded_frames(master,w,h,lambda:False,output_pipe=windows_output_pipe) as pictures:
            final=[analyze(picture) for picture in pictures]
    if len(final)!=count:
        raise ValueError("The encoded oracle has a different frame count")
    return dict(frames=count,metadata_differences=sum(a!=b for a,b in zip(pre,final,strict=True)))


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output",type=Path)
    methods=parser.add_subparsers(dest="method",required=True)
    decode_parser=methods.add_parser("decode")
    decode_parser.add_argument("sources",nargs="+",type=Path)
    decode_parser.add_argument("--frames",type=int,default=24)
    gpu_parser=methods.add_parser("preencode")
    for name in ("worker","master","library"):
        gpu_parser.add_argument(name,type=Path)
    args=parser.parse_args()
    if not power():
        parser.error("Connect AC before running diagnostics")
    if args.method=="decode":
        result=profile_decode(args.sources,args.frames)
    else:
        result=preencode(args.worker.resolve(),args.master.resolve(),args.library,args.output.parent)
    result["ac_at_finish"]=power()
    args.output.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result,indent=2))
