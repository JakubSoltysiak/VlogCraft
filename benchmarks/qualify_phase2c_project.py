"""Benchmark identical authoring arms on a saved UHD60 editing project."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from time import perf_counter

from conditions import Conditions
from phase2b_live import generated_sources
from render_phase2 import ROOT, Scenario, call, power
from studio357_hdr_sequence import state_for

sys.path[:0] = [str(ROOT), str(ROOT/"tests")]
from hdr10plus_export import media
from hdr10plus_master import author, preflight
from hdr10plus_index import SIDE_DATA
from phase2b_project_export import ProjectConverter
from phase2c_author import author_options
from profile_hdr_render import metadata_by_picture
from performance import Resources
from render_phase2_export import decoded
import project_store
import render_engine
import server
import timing


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream,"sha256").digest()


def qualify(result, library, count, camera=None, *, exact_still_clock=False):
    if not power():
        raise RuntimeError("Connect AC before timing a saved project")
    result.mkdir(parents=True,exist_ok=False)
    preparation_started = perf_counter()
    scenario = Scenario("saved-project",3840,2160)
    sources = generated_sources(result,scenario,count,only_sdr=bool(camera),extra_frames=60)
    if camera:
        sources.append(camera)
    state, inputs = state_for(result,(3840,2160),"3840x2160",count,True,video_inputs=sources)
    if exact_still_clock:
        # The image demuxer's nominal time base does not describe the hold
        # duration of an untimed photograph on the editing timeline.
        for asset in state["assets"]:
            if asset["kind"]=="image":
                asset["timeBase"]="1/120000"
        # Hold the transition width within the real camera's existing
        # incoming preroll as the surrounding timeline is extended.
        for track in state["tracks"]:
            for clip in track["clips"]:
                if clip.get("transitionIn"):
                    clip["transitionIn"]["frames"]=min(16,clip["transitionIn"]["frames"])
    video_assets={asset["id"]:asset for asset in state["assets"] if asset["kind"]=="video"}
    square_overrides=0
    for track in state["tracks"]:
        for clip in track["clips"]:
            asset=video_assets.get(clip.get("assetId"))
            if asset and asset.get("sampleAspectRatio") in (None,"","unknown","N/A","0:1"):
                clip["inputColor"]={**clip.get("inputColor",{}),"profile":"source","pixelAspect":"square"}
                square_overrides+=1
    overlay=state["tracks"][0]["clips"][0]
    overlay.update(mask="ellipse",maskRadius=.48,feather=.22,rotation=9)
    saved = result/"generated-project.json"
    project_store.save(saved,timing.encode(state),server.validate_document)
    state, recovered = project_store.load(saved,server.validate_document)
    if recovered or preflight(state)!=count:
        raise ValueError("The saved project does not reopen at the requested frame length")
    protected = {path:digest(path) for path in [saved,*inputs]}
    preparation = perf_counter()-preparation_started
    static = result/"static.mp4"
    converter = ProjectConverter(3840,2160,3,300,lambda label:print(label,flush=True))
    conditions = Conditions()
    arms = {}
    try:
        monitor=Resources(os.getpid(),gpu=False)
        started=perf_counter()
        try:
            render_engine.render(state,static,result/"timeline",popen=converter,
                                 on_progress=lambda t,stage:print(t,stage,flush=True))
            base_seconds=perf_counter()-started
        finally:
            render_resources=monitor.finish()
        for mode in ("fast","frozen"):
            folder=result/mode
            folder.mkdir()
            master=folder/"verified.mp4"
            monitor=Resources(os.getpid(),gpu=False)
            started=perf_counter()
            try:
                authored=author(static,master,folder,60,count,render_engine._run,
                                lambda stage,_:print(stage,flush=True),lambda:False,
                                **(author_options(library,3) if mode=="fast" else {}))
                seconds=perf_counter()-started
            finally:
                resources=monitor.finish()
            arms[mode]=dict(author_seconds=seconds,shared_render_and_author_seconds=base_seconds+seconds,
                            author_frames=authored,resources=resources)
    finally:
        observed=conditions.finish()
    fast=result/"fast/verified.mp4"
    frozen=result/"frozen/verified.mp4"
    record=metadata_by_picture(lambda *args:call(args).stdout,fast,SIDE_DATA)
    before=media(static)
    after=media(fast)
    pictures = decoded(static,"0:v:0","framemd5")==decoded(fast,"0:v:0","framemd5")
    pcm = decoded(static,"0:a:0","s16le")==decoded(fast,"0:a:0","s16le")
    exact = digest(frozen)==digest(fast)
    unchanged = all(digest(path)==expected for path,expected in protected.items())
    if (not pictures or not pcm or not exact or not unchanged or int(after[1]["duration_ts"])!=800*count or
            before[0]["time_base"]!="1/120000" or len(record)!=count or
            any(int(pts)!=2000*i or not tags for i,(pts,tags) in enumerate(record))):
        raise ValueError("The project delivery failed independent HDR10+ verification")
    values=dict(frames=count, private_pq_media=bool(camera), source_integrity=unchanged,
                explicit_square_pixel_overrides=square_overrides,
                saved_project_reopened=True, prepared_seconds=preparation, shared_render_seconds=base_seconds,
                render_resources=render_resources, parallel_segments=converter.completed,
                fallback_segments=converter.fallbacks, exact_authored_master=exact,
                exact_decoded_pictures=pictures, exact_pcm=pcm, audio_endpoint_samples=800*count,
                metadata_associations=len(record), arms=arms,power=observed)
    (result/"report.json").write_text(json.dumps(values,indent=2)+"\n",encoding="utf-8")
    return values


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result",type=Path)
    parser.add_argument("--library",type=Path,required=True)
    parser.add_argument("--frames",type=int,default=24)
    parser.add_argument("--camera",type=Path)
    parser.add_argument("--exact-still-clock",action="store_true")
    args=parser.parse_args()
    if args.frames<24 or args.frames%3:
        parser.error("Use at least 24 pictures, divisible by three")
    print(json.dumps(qualify(args.result.resolve(),args.library,args.frames,
                             args.camera.resolve() if args.camera else None,
                             exact_still_clock=args.exact_still_clock),indent=2))
