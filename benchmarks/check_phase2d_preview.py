"""Measure managed SDR monitor stills against the GPU master's tone-mapped pictures."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile

import numpy as np
from PIL import Image

if not __package__:
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from native_project_plan import run_capture
import project_store
import render_engine
import server
import timing


def compare(project,master,frames):
    saved,recovered=project_store.load(project,server.validate_document)
    if saved is None or recovered:
        raise ValueError("A valid saved project is required")
    monitor=deepcopy(saved)
    out=monitor["output"]
    scale=min(1,960/max(out["width"],out["height"]))
    width,height=(max(2,round(out[key]*scale/2)*2) for key in ("width","height"))
    out.update(width=width,height=height)
    fps=timing.rate(out["fps"])
    expr="+".join(f"eq(n,{frame})" for frame in frames)
    filters=(
        f"select='{expr}',zscale=threads=1:agamma=0:pin=2020:tin=smpte2084:min=2020_ncl:rin=limited:"
        f"p=709:t=linear:m=gbr:r=full:npl=100:w={width}:h={height}:filter=bilinear,format=gbrpf32le,"
        "tonemap=hable:desat=0:peak=100,zscale=threads=1:agamma=0:pin=709:tin=linear:min=gbr:rin=full:"
        "p=709:t=709:m=709:r=limited:npl=100:dither=error_diffusion,format=yuv420p,format=rgb24"
    )
    raw,_=run_capture(["ffmpeg","-v","error","-threads","2","-i",master,"-vf",filters,
                       "-fps_mode","passthrough","-threads:v","1","-f","rawvideo","-"],timeout=120)
    pictures=np.frombuffer(raw,np.uint8).reshape(len(frames),height,width,3)
    scores=[]
    with tempfile.TemporaryDirectory() as temp:
        work=Path(temp)
        for index,frame in enumerate(frames):
            target=work/f"monitor-{index}.png"
            command=render_engine.segment_command(monitor,float(frame/fps),float((frame+1)/fps),target,work,"frame")
            run_capture(command,timeout=120)
            with Image.open(target) as image:
                difference=np.asarray(image.convert("RGB"),dtype=np.float32)-pictures[index]
            scores.append({"frame":frame,"rgb_mae":float(np.mean(np.abs(difference))),
                           "rgb_psnr_db":float(20*np.log10(255/max(1e-10,np.sqrt(np.mean(difference**2)))))})
    return {"monitor":[width,height],"mode":"Managed SDR program still versus SDR diagnostic of PQ export",
            "checks":scores}


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project",type=Path)
    parser.add_argument("master",type=Path)
    parser.add_argument("report",type=Path)
    parser.add_argument("--frames",type=int,nargs="+",required=True)
    args=parser.parse_args()
    if args.frames!=sorted(set(args.frames)) or args.frames[0]<0:
        parser.error("Use distinct increasing frame numbers")
    report=compare(args.project,args.master,args.frames)
    args.report.write_text(json.dumps(report,indent=2)+"\n",encoding="utf8")
    print(json.dumps(report))
