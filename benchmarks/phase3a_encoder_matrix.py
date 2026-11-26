"""Replay one complete camera encoder span and compare both quantized inputs and HEVC pictures."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import numpy as np

if not __package__:
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from benchmarks.phase3a_segment_assembly import decoded_hashes
from hdr10plus_bitstream import length_size, packet_records, probe_streams
import hdr_render
import native_project_plan as plan
from native_project_render import CREATE_FLAGS, PQ_TAGS, raw_input
from native_project_verification import eligible, source_snapshot
import project_store
import server


def picture_slices(path, start, count):
    """Hash coded slices in presentation order, independently of authoring SEI or container bytes."""
    stream=next(s for s in probe_streams(path)["streams"] if s["codec_type"]=="video")
    width=length_size(stream)
    if stream["time_base"]!="1/120000":
        raise ValueError("Unexpected video time base")
    rows={}
    with path.open("rb") as source, packet_records(path,"v:0") as packets:
        for packet in packets:
            frame,remainder=divmod(int(packet[b"pts"]),2000)
            if remainder or frame in rows:
                raise ValueError("Ambiguous UHD60 presentation clock")
            if not start<=frame<start+count:
                continue
            source.seek(int(packet[b"pos"]))
            data=source.read(int(packet[b"size"]))
            offset=0
            slices=[]
            while offset<len(data):
                length=int.from_bytes(data[offset:offset+width],"big")
                offset+=width
                if length<2 or length>len(data)-offset:
                    raise ValueError("Incomplete HEVC NAL")
                if ((data[offset]>>1)&63)<32:
                    slices.append(data[offset-width:offset+length])
                offset+=length
            if not slices:
                raise ValueError("Packet has no coded picture")
            rows[frame]=dict(vcl_sha256=sha256(b"".join(slices)).hexdigest(),
                             bytes=sum(map(len,slices)),pts=int(packet[b"pts"]),dts=int(packet[b"dts"]),
                             key=b"K" in packet[b"flags"])
    return [rows[frame] for frame in range(start,start+count)]


def compare_inputs(managed,gpu,width,height,first,count):
    samples=width*height
    sizes=(samples,samples//4,samples//4)
    rows=[]
    with managed.open("rb") as ref,gpu.open("rb") as other:
        other.seek(first*3*samples)
        for i in range(count):
            planes=[]
            for size in sizes:
                a,b=ref.read(size*2),other.read(size*2)
                if min(len(a),len(b))!=size*2:
                    raise ValueError("Short raw picture")
                delta=np.frombuffer(a,"<u2").astype(np.int32)-np.frombuffer(b,"<u2")
                planes.append(dict(managed_sha256=sha256(a).hexdigest(),gpu_sha256=sha256(b).hexdigest(),
                                   different=int(np.count_nonzero(delta)),max_delta=int(np.abs(delta).max()),
                                   squared_error=int(np.sum(delta*delta,dtype=np.int64))))
            rows.append(planes)
        if ref.read(1):
            raise ValueError("Unexpected managed pictures after the encoder span")
    return rows


def slice_decisions(path,count):
    """Read x265's actual frame types and slice QP deltas for this single-slice profile."""
    process=subprocess.Popen(["ffmpeg","-v","info","-nostdin","-copyts","-i",path,"-map","0:v:0",
                              "-c:v","copy","-bsf:v","trace_headers","-f","null","-"],
                             stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,creationflags=CREATE_FLAGS)
    decisions={}
    current=None
    with process,process.stderr:
        for line in process.stderr:
            packet=re.search(rb"Packet: .*?pts (-?\d+),",line)
            if packet:
                frame,rem=divmod(int(packet[1]),2000)
                if rem or frame in decisions:
                    raise ValueError("Unexpected slice presentation clock")
                current=decisions[frame]={}
            field=re.search(rb"\b(slice_type|slice_qp_delta)\s+\S+ = (-?\d+)\s*$",line)
            if field and current is not None:
                key=field[1].decode("ascii")
                if key in current:
                    raise ValueError("This control requires single-slice pictures")
                current[key]=int(field[2])
    if process.returncode or len(decisions)!=count or any(len(row)!=2 for row in decisions.values()):
        raise ValueError("Incomplete HEVC slice header trace")
    return [decisions[i] for i in range(count)]


def measure(work,program,first,last,reference,previous):
    count=last-first
    raw=compare_inputs(work/"managed.yuv",work/"gpu.yuv",program.width,program.height,first,count)
    arms={arm:(work/(arm+".mov"),0) for arm in "ABCD"}
    arms.update(reference=(reference,first),previous=(previous,first))
    records={}
    for arm,(path,start) in arms.items():
        hashes=decoded_hashes(path)[start:start+count]
        if len(hashes)!=count:
            raise ValueError("Independent decode returned too few pictures")
        records[arm]=[dict(**packet,decoded_md5=digest.decode("ascii")) for packet,digest in
                      zip(picture_slices(path,start,count),hashes,strict=True)]
        if arm in ("A","D"):
            for record,decision in zip(records[arm],slice_decisions(path,count),strict=True):
                record.update(decision)
    return dict(span=[first,last],raw_planes_yuv=raw,pictures=records)


def run(command,work,name,*,env=None,stdout=subprocess.DEVNULL):
    with (work/(name+".log")).open("xb") as log:
        subprocess.run(command,stdout=stdout,stderr=log,cwd=work,env=env,check=True,
                       stdin=subprocess.DEVNULL,creationflags=CREATE_FLAGS)


def capture(state,program,first,last,work,worker,runtime):
    w,h,rate=program.width,program.height,program.fps
    size=w*h*3
    if shutil.disk_usage(work).free < size*(last-first+len(program.frames))+1024**3:
        raise ValueError("Insufficient space for both local raw captures")
    cmd=hdr_render.command(state,float(first/rate),float(last/rate),work/"A.mov",work)
    script=Path(cmd[cmd.index("-/filter_complex")+1])
    script.write_text(script.read_text("utf8").rstrip()+";[finished]split=2[toencoder][capture]\n",encoding="utf8")
    canonical=cmd[cmd.index("-an",cmd.index("-/filter_complex")):]
    cmd[cmd.index("[finished]")]="[toencoder]"
    run(cmd+["-map","[capture]","-frames:v",str(last-first),"-an","-c:v","rawvideo","-pix_fmt","yuv420p10le",
             "-threads:v","1","-f","rawvideo",work/"managed.yuv"],work,"capture-A")
    plan.write_plan(work/"plan.bin",program)
    plan.write_sources(work/"sources.bin",program,first_time=True,camera_range=True,keyframe_seek=True)
    env={**os.environ,"PATH":str(runtime.resolve(strict=True))+os.pathsep+os.environ.get("PATH","")}
    # Keep the entire worker output, including preceding trims and decoded cursor state.
    gpu=work/"gpu.yuv"
    with gpu.open("xb") as target:
        run([worker.resolve(strict=True),"gpu32-first-export",work/"plan.bin","@resident:"+str(work/"sources.bin"),
             "@pq-stream","0","8","0"],work,"capture-native",env=env,stdout=target)
    if gpu.stat().st_size!=len(program.frames)*size:
        raise ValueError("Incorrect GPU capture length")
    for arm in "BCD":
        cmd=raw_input(w,h,str(rate))
        if arm!="B":
            index=cmd.index("-i")
            cmd[index:index]=["-skip_initial_bytes",str(first*size)]
        cmd[cmd.index("pipe:0")]=str(work/"managed.yuv" if arm=="B" else gpu)
        if arm=="C":
            ingress=work/"managed-input.ffgraph"
            ingress.write_text("[0:v]setsar=1,"+PQ_TAGS+"[finished]\n",encoding="utf8")
            cmd+=["-/filter_complex",ingress,"-map","[finished]"]
        else:
            cmd+=["-map","0:v:0","-vf","setsar=1,"+PQ_TAGS]
        run([*cmd,*canonical[:-1],work/(arm+".mov")],work,arm)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    for field in ("project","folder","worker","runtime","reference","previous"):
        parser.add_argument(field,type=Path)
    parser.add_argument("--span",required=True,nargs=2,type=int)
    args=parser.parse_args()
    state,recovered=project_store.load(args.project,server.validate_document)
    if recovered or state is None:
        parser.error("Use an intact saved range")
    before=source_snapshot(state)
    work=args.folder.resolve()
    work.mkdir(parents=True,exist_ok=False)
    program=plan.compile_project(state,work)
    eligible(state,program,camera_range=True,qualification=True)
    if tuple(args.span) not in program.spans:
        parser.error("Use a complete existing encoder span")
    capture(state,program,*args.span,work,args.worker,args.runtime)
    result=measure(work,program,*args.span,args.reference,args.previous)
    if before!=source_snapshot(state):
        raise ValueError("Source identities changed during the experiment")
    (work/"matrix.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf8")
