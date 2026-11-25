"""Compare indexed and continuous D3D11 decode on generated reordered VFR pictures."""
import argparse
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

if not __package__:
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

import native_project_plan as plan


def compare_saved(folder,worker,runtime,project):
    """Hash every packed picture before x265, with identical composition in both arms."""
    import project_store
    import server
    from native_project_verification import eligible,source_snapshot
    folder=folder.resolve()
    folder.mkdir(parents=True,exist_ok=False)
    state,recovered=project_store.load(project,server.validate_document)
    if recovered or not state:
        raise ValueError("An intact saved camera-range project is required")
    pinned=source_snapshot(state)
    program=plan.compile_project(state,folder)
    eligible(state,program,camera_range=True,qualification=True)
    plan.write_plan(folder/"plan.bin",program)
    hashes=[]
    counts=[]
    for arm,indexed in (("prefix",False),("indexed",True)):
        manifest=folder/f"{arm}.bin"
        plan.write_sources(manifest,program,first_time=True,camera_range=True,keyframe_seek=indexed)
        log=folder/f"{arm}.log"
        args=[worker.resolve(),"gpu32-first-export",folder/"plan.bin","@resident:"+str(manifest),"@pq-stream","0","8","0"]
        with log.open("wb") as errors,subprocess.Popen(args,stdout=subprocess.PIPE,stderr=errors,
                env={**os.environ,"PATH":str(runtime.resolve())+os.pathsep+os.environ.get("PATH","")}) as producer:
            try:
                digest=subprocess.run(["ffmpeg","-v","error","-xerror","-f","rawvideo","-pix_fmt","yuv420p10le",
                    "-s",f"{program.width}x{program.height}","-framerate",str(program.fps),"-i","pipe:0","-c","copy",
                    "-f","framehash","-hash","sha256","-"],stdin=producer.stdout,stdout=subprocess.PIPE,
                    check=True,timeout=1800)
                if producer.wait(timeout=10):
                    raise ValueError(f"{arm} worker rejected the source or picture clock")
            finally:
                producer.stdout.close()
                if producer.poll() is None:
                    producer.kill()
        hashes.append([line for line in digest.stdout.splitlines() if line and not line.startswith(b"#")])
        receipt=json.loads(log.read_bytes().splitlines()[-1])
        counts.append(sum(src["decoded_pictures"] for src in receipt["resident_sources"]))
    if len(hashes[0])!=len(program.frames) or hashes[0]!=hashes[1] or pinned!=source_snapshot(state):
        raise ValueError("Packed pictures, source identity or timing differ")
    result=dict(matched_packed_main10_pictures=len(hashes[0]),prefix_decoded=counts[0],indexed_decoded=counts[1])
    (folder/"comparison.json").write_text(json.dumps(result,indent=2)+"\n","utf8")
    return result


def qualify(folder,worker,runtime):
    folder=folder.resolve()
    folder.mkdir(parents=True,exist_ok=False)
    size=(320,192)
    count=36
    results={}
    for codec,encoder in (("h264","libx264"),("hevc","libx265")):
        path=folder/(codec+".mp4")
        pq=codec=="hevc"
        tags=("bt2020","smpte2084","bt2020nc") if pq else ("bt709","bt709","bt709")
        params=("pools=2:frame-threads=2:open-gop=1:" if pq else "open-gop=0:")+"scenecut=0:keyint=24:min-keyint=24:bframes=4"
        color_filter=f"setparams=range=limited:color_primaries={tags[0]}:color_trc={tags[1]}:colorspace={tags[2]}"
        cmd=["ffmpeg","-v","error","-nostdin","-n","-f","lavfi","-i","testsrc2=size=320x192:rate=60:duration=5",
             "-vf","select='not(eq(mod(n,9),4))',"+color_filter,"-fps_mode","vfr","-c:v",encoder,"-threads","2",
             "-pix_fmt","yuv420p10le" if pq else "yuv420p","-tag:v","hvc1" if pq else "avc1",
             "-x265-params" if pq else "-x264-params",params,"-color_primaries",tags[0],"-color_trc",tags[1],
             "-colorspace",tags[2],"-color_range","tv","-output_ts_offset","2",path]
        subprocess.run(cmd,check=True)
        requests={n:Fraction(9,4)+Fraction(n,60) for n in range(count)}
        src=plan.Source(path,size,"",size,"video",{"codec":codec},(*tags,"limited","pq2020" if pq else "rec709"),requests)
        geo=(1.,1.,0.,0.,0.)
        packed=(*geo,1.,.5,.1,0,0,0,1.)
        program=plan.Program(*size,Fraction(60),1.,[(0,count)],[src],[(-1.,[(packed,geo)])]*count)
        plan.write_plan(folder/"plan.bin",program)
        arms=[]
        for indexed in (False,True):
            sourcefile=folder/f"{codec}-{int(indexed)}.bin"
            clocks=plan.write_sources(sourcefile,program,first_time=True,camera_range=indexed,keyframe_seek=indexed)
            base,origin,stamps,selected=clocks[0]
            args=[worker.resolve(),"gpu32-first-export",folder/"plan.bin","@resident:"+str(sourcefile),"@pq-stream","0","8","0"]
            execution=subprocess.run(args,capture_output=True,timeout=120,
                                     env={**os.environ,"PATH":str(runtime.resolve())+os.pathsep+os.environ.get("PATH","")})
            (folder/f"{codec}-{int(indexed)}.log").write_bytes(execution.stderr)
            execution.check_returncode()
            report=json.loads(execution.stderr.splitlines()[-1])["resident_sources"][0]
            if len(execution.stdout)!=count*size[0]*size[1]*3:
                raise ValueError("Incomplete packed Main10 stream")
            arms.append((hashlib.sha256(execution.stdout).hexdigest(),
                         [stamps[i]*base for i in selected],report))
        original,seek=arms
        points=seek[2]["seek_points"]
        if (original[:2]!=seek[:2] or origin==0 or len(set(b-a for a,b in zip(stamps,stamps[1:])))<2 or
            not any(p["nal_type"]==(21 if pq else 5) for p in points) or
            seek[2]["decoded_pictures"]>=original[2]["decoded_pictures"]):
            raise ValueError("Indexed decoder did not reproduce the reordered VFR control")
        results[codec]=dict(matched_packed_main10_pictures=count,matched_pts=count,format_start=str(origin),
                            prefix_decoded=original[2]["decoded_pictures"],indexed_decoded=seek[2]["decoded_pictures"],
                            seek_nal_types=[p["nal_type"] for p in points])
    (folder/"comparison.json").write_text(json.dumps(results,indent=2)+"\n","utf8")
    return results


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("folder","worker","runtime"):
        parser.add_argument(name,type=Path)
    parser.add_argument("--project",type=Path,help="Compare the two raw streams on this saved camera range")
    args=parser.parse_args()
    result=(compare_saved(args.folder,args.worker,args.runtime,args.project) if args.project
            else qualify(args.folder,args.worker,args.runtime))
    print(json.dumps(result))
