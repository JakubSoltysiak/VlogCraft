"""Reproduce one complete HDR GOP with identical x265 settings and count its errors."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import numpy as np

if not __package__:
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

import color_management
import hdr_render
from native_project_plan import run_capture
from native_project_render import CREATE_FLAGS, PQ_TAGS, raw_input
import project_store
import render_engine
import server
import timing


def run_to_file(command,output,work,env=None):
    started=time.perf_counter()
    with output.open("xb") as destination:
        subprocess.run([str(item) for item in command],stdout=destination,stderr=subprocess.PIPE,
                       stdin=subprocess.DEVNULL,check=True,cwd=work,env=env,timeout=240,
                       creationflags=CREATE_FLAGS)
    return time.perf_counter()-started


def format_raw(command):
    return [*command[:command.index("-c:v")],"-c:v","rawvideo","-threads:v","1","-f","rawvideo","-"]


def measure(a,b,width,height):
    y=width*height
    ranges=(slice(0,y),slice(y,y+y//4),slice(y+y//4,None))
    rows=[]
    for left,right in zip(a,b,strict=True):
        error=left.astype(np.float32)-right
        mse=float(np.mean(error**2))
        planes=[float(np.mean(np.abs(error[region]))) for region in ranges]
        # Convert PQ luma code values as a scalar signal. This is a luminance
        # proxy for encoded luma, not an RGB/BT.2020 linear-light reconstruction.
        nits=[color_management.pq_to_nits(np.clip((values[:y].astype(np.float32)-64)/876,0,1))
              for values in (left,right)]
        rows.append(dict(psnr_db=float(10*np.log10(1023**2/mse)) if mse else None,
                         mae_codes_yuv=planes,peak_abs_code_error=float(np.max(np.abs(error))),
                         pq_luma_proxy_mae_cd_m2=float(np.mean(np.abs(nits[0]-nits[1])))))
    return rows


def hash_file(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle,"sha256").hexdigest()


def probe(args):
    work=args.results.resolve()
    work.mkdir(parents=True)
    state,recovered=project_store.load(args.project,server.validate_document)
    if state is None or recovered:
        raise ValueError("Use the intact saved qualification project")
    output=state["output"]
    width,height=output["width"],output["height"]
    rate=timing.rate(output["fps"])
    first,last=args.span
    if (first,last) not in render_engine.frame_spans(state,rate):
        raise ValueError("The diagnostic must reproduce a complete managed GOP")
    command=hdr_render.command(state,float(first/rate),float(last/rate),work/"baseline.mov",work)
    script=command.index("-/filter_complex")+1
    encoder=raw_input(width,height,str(rate))
    encoder[encoder.index("pipe:0")]="INPUT"
    encoder += ["-map","0:v:0","-vf","setsar=1,"+PQ_TAGS,*command[command.index("-an",script+1):]]
    original=work/"managed.yuv"
    resident=work/"resident.yuv"
    preparation={"managed_seconds":run_to_file(format_raw(command),original,work)}
    environment=dict(os.environ)
    environment["PATH"]=str(args.runtime.resolve())+os.pathsep+environment.get("PATH","")
    native=[str(args.worker.resolve()),"gpu32",str(args.plan.resolve()),"@resident:"+str(args.sources.resolve())]
    preparation["resident_seconds"]=run_to_file([*native,"@pq-stream","0","8","0"],resident,work,environment)
    linear=work/"resident.gbr"
    preparation["resident_linear_seconds"]=run_to_file([*native,"@gbr-stream","0","8","0"],linear,work,environment)
    exact=work/"resident-zimg.yuv"
    tail=Path(command[script]).read_text("utf8").rsplit(",sidedata=mode=delete,",1)[1].split("[finished]")[0]
    preparation["resident_zimg_seconds"]=run_to_file(
        ["ffmpeg","-hide_banner","-v","error","-nostdin","-f","rawvideo","-pixel_format","gbrpf32le",
         "-video_size",f"{width}x{height}","-framerate",str(rate),"-i",linear,"-vf",tail,
         "-c:v","rawvideo","-threads:v","1","-f","rawvideo","-"],exact,work)
    shape=(last-first,width*height*3//2)
    pics=lambda path:np.memmap(path,dtype="<u2",mode="r",shape=shape)
    raw={name:pics(path) for name,path in (("managed",original),("resident",resident),("resident_zimg",exact))}
    cases={}
    for label,path in (("managed",original),("managed_repeat",original),("resident",resident),
                       ("resident_repeat",resident),("resident_zimg",exact)):
        encoded=work/(label+".mov")
        cmd=encoder.copy()
        cmd[cmd.index("INPUT")]=str(path)
        options=cmd.index("-x265-params")+1
        cmd[options]+=f":csv={label}.csv:csv-log-level=2"
        cmd[-1]=str(encoded)
        started=time.perf_counter()
        run_capture(cmd,cwd=work)
        elapsed=time.perf_counter()-started
        decoded=work/(label+".yuv10")
        run_to_file(["ffmpeg","-v","error","-threads","2","-i",encoded,"-map","0:v","-an","-f","rawvideo","-"],decoded,work)
        packets=json.loads(run_capture(["ffprobe","-v","error","-show_packets","-select_streams","v:0",
                                        "-show_entries","packet=pts,size,flags","-of","json",encoded])[0])["packets"]
        with (work/(label+".csv")).open(newline="") as log:
            quantizers=[{"picture_order":int(row["POC"]),"qp":float(row["QP"]),"bits":int(row["Bits"])}
                        for item in csv.DictReader(log,skipinitialspace=True)
                        if (row:={key.strip():value.strip() for key,value in item.items() if key and value}) and
                        row.get("POC","").isdigit()]
        cases[label]={"seconds":elapsed,"bytes":encoded.stat().st_size,"packets":packets,"picture_qp":quantizers,
                      "decoded_sha256":hash_file(decoded),
                      "encoded_vs_own_raw":measure(raw[label.removesuffix("_repeat")],pics(decoded),width,height)}
    comparison={}
    for label in ("resident","resident_zimg"):
        comparison[label]={"unencoded":measure(raw["managed"],raw[label],width,height),
                           "decoded":measure(pics(work/"managed.yuv10"),pics(work/(label+".yuv10")),width,height)}
    result={"span":[first,last],"profile":{"fps":str(rate),"preset":output["preset"],"crf":output["crf"],
                                          "x265_options":encoder[encoder.index("-x265-params")+1]},
            "preparation":preparation,"cases":cases,"comparison":comparison,
            "deterministic":all(cases[name]["decoded_sha256"]==cases[name+"_repeat"]["decoded_sha256"]
                                for name in ("managed","resident"))}
    (work/"report.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf8")
    return result


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    for field in ("project","results","worker","runtime","plan","sources"):
        parser.add_argument(field,type=Path)
    parser.add_argument("--span",nargs=2,type=int,required=True)
    arguments=parser.parse_args()
    report=probe(arguments)
    print(json.dumps({"deterministic":report["deterministic"],"decoded_psnr_db":{
          label:[row["psnr_db"] for row in entries["decoded"]]
          for label,entries in report["comparison"].items()}}))
