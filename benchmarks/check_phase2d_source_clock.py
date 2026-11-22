"""Compare the native plan's original picture IDs with FFmpeg's cadence filter."""
import argparse
from fractions import Fraction
import json
from pathlib import Path
import re
import struct
import sys
import tempfile

if not __package__:
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

import native_project_plan as plan
import project_store
import render_engine
import server
import timing


READ = re.compile(rb"Read frame with in pts (-?\d+), out pts (-?\d+)")
WRITE = re.compile(rb"Writing frame with pts (-?\d+) to pts (-?\d+)")


def selection(src,seek,rate,count,base):
    command = ["ffmpeg","-hide_banner","-loglevel","debug","-nostdin","-noautorotate"]
    render_engine._media_input(command,src.path,"video",float(seek),1,count/rate,rate,"video")
    command += ["-map","0:v:0","-vf",f"setpts=PTS/1,fps={rate}:start_time=0:round=up",
                "-frames:v",str(count),"-f","null","-"]
    _,logs = plan.run_capture(command,timeout=120)
    origin = Fraction(src.asset.get("formatStart") or 0)
    offset = timing.nearest((origin+seek)/base)
    seen,selected = {},{}
    for line in logs.splitlines():
        if event:=READ.search(line):
            seen[int(event[2])] = int(event[1])+offset
        if event:=WRITE.search(line):
            selected[int(event[2])] = seen[int(event[1])]
    return [selected[index] for index in range(count)]


def qualify(project):
    state,recovered = project_store.load(project,server.validate_document)
    if recovered or state is None:
        raise ValueError("A valid saved project is required")
    with tempfile.TemporaryDirectory() as folder:
        program = plan.compile_project(state,Path(folder))
    reports = []
    for slot,src in enumerate(program.sources):
        if src.kind!="video":
            continue
        with tempfile.TemporaryFile() as manifest:
            plan.append_video(manifest,slot,src,len(program.frames),lambda:False)
            manifest.seek(0)
            _,name_bytes,*_,pictures,num,den = struct.unpack("<11I",manifest.read(44))
            manifest.seek(name_bytes,1)
            stamps = struct.unpack(f"<{pictures}q",manifest.read(pictures*8))
            native = struct.unpack(f"<{len(program.frames)}i",manifest.read())
        reports.append({"selected_frames":0,"pts_mismatches":0,"mismatched_output_frames":[],"spans":0})
        report=reports[-1]
        for start,end in program.spans:
            indices=[index for index in range(start,end) if native[index]>=0]
            if not indices:
                continue
            if len(indices)!=indices[-1]-indices[0]+1:
                raise ValueError("The source does not continuously cover this managed span")
            expected=selection(src,src.requests[indices[0]],program.fps,len(indices),Fraction(num,den))
            report["selected_frames"]+=len(indices)
            mismatches=[index for index,pts in zip(indices,expected,strict=True) if stamps[native[index]]!=pts]
            report["pts_mismatches"]+=len(mismatches)
            report["mismatched_output_frames"].extend(mismatches)
            report["spans"]+=1
    return {"output_frames":len(program.frames),"sources":reports,
            "exact":bool(reports) and all(row["pts_mismatches"]==0 for row in reports)}


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project",type=Path)
    parser.add_argument("report",type=Path)
    args=parser.parse_args()
    result=qualify(args.project)
    args.report.write_text(json.dumps(result,indent=2)+"\n",encoding="utf8")
    print(json.dumps(result))
    raise SystemExit(0 if result["exact"] else 1)
