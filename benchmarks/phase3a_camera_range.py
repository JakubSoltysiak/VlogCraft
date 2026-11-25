"""Qualify a bounded first export against a reference rendered after it."""
import argparse
from copy import deepcopy
from fractions import Fraction
from hashlib import sha256
import json
import math
from pathlib import Path
import sys
import time

if not __package__:
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from benchmarks.phase2b_project_export import export_project
from hdr10plus_bitstream import conformance_issues, length_size, packet_records, sample_metadata
from hdr10plus_export import media
from hdr10plus_fast import author_options
from native_project_plan import compile_project
from native_project_render import compare_project, export_native
from native_project_verification import eligible, source_snapshot
import hdr10plus_master
import project_store
import render_engine
import timing


def camera_range(state,first,last):
    """Rebase a frame-aligned straight-cut section without rewriting its sources."""
    fps=timing.rate(state["output"]["fps"])
    if fps!=60 or first<0 or not 2<=last-first<=120:
        raise ValueError("Select a 2–120-picture range from a 60 FPS project")
    if any(clip.get("transitionIn") or clip["kind"]=="sequence" for track in state["tracks"] for clip in track["clips"]):
        raise ValueError("The range tool requires a flat timeline with straight cuts")
    if not any(start==first for start,_ in render_engine.frame_spans(state,fps)):
        raise ValueError("Start the range at an original render-span boundary")
    result=deepcopy(state)
    assets={asset["id"]:asset for asset in state["assets"]}
    for track in result["tracks"]:
        clips=[]
        for clip in track["clips"]:
            clip_first=timing.frame_at(clip["position"],fps)
            clip_last=timing.frame_at(render_engine.clip_finish(clip),fps)
            start,end=max(first,clip_first),min(last,clip_last)
            if start>=end:
                continue
            if start!=clip_first:
                raise ValueError("Start at an existing clip boundary to preserve original audio and video preroll")
            if (clip["kind"] not in ("video","audio") or clip.get("speed",1)!=1 or clip.get("keys") or
                any(clip.get(key,0)!=0 for key in ("fadeIn","fadeOut","bass","treble","pan")) or
                clip.get("compress",1)!=1):
                raise ValueError("The range tool requires video and audio with unchanged trim behavior")
            base=timing.base_for(assets[clip["assetId"]])
            if end<clip_last:
                origin=timing.nearest(timing.rational(clip["start"])/base)*base
                source_end=origin+(end-clip_first)/fps
                if (source_end/base).denominator!=1:
                    raise ValueError("The range endpoint is outside the original source tick grid")
                clip["end"]=float(source_end)
            clip["position"]=float((start-first)/fps)
            clips.append(clip)
        track["clips"]=clips
    return result


def verify_original_requests(full,program,first,last):
    """Map every GPU request to the unchanged FFmpeg seek of the original span."""
    fps=program.fps
    spans=[(start,min(last,end)) for start,end in render_engine.frame_spans(full,fps) if first<=start<last]
    if program.spans!=[(start-first,end-first) for start,end in spans]:
        raise ValueError("The range changed an original render-span boundary")
    checked=0
    for start,end in spans:
        video,_=render_engine.active_clips(full,float(start/fps),float(end/fps))
        if len(video)!=1:
            raise ValueError("The original span requires one unambiguous source camera")
        _,clip=video[0]
        at=max(float(start/fps),float(timing.frame_at(clip["position"],fps)/fps))
        seek=clip["start"]+max(0,at-float(clip["position"]))
        # This is the same microsecond seek that the original managed graph passes to FFmpeg.
        anchor=Fraction(math.ceil(seek*1_000_000-1e-8),1_000_000)
        for original in range(start,end):
            index=original-first
            matches=[src for src in program.sources if index in src.requests]
            expected=anchor+(original-start)/fps
            if (len(matches)!=1 or matches[0].asset["id"]!=clip["assetId"] or
                matches[0].requests[index]!=expected):
                raise ValueError(f"Picture {original} changed the original camera source request")
            checked+=1
    if checked!=last-first:
        raise ValueError("The source mapping did not account for every requested frame")
    return checked


def verify_hdr10plus_packets(path,program):
    video,_=media(path)
    width=length_size(video)
    time_base=Fraction(video["time_base"])
    count=len(program.frames)
    seen=set()
    with packet_records(path,"v:0") as packets,path.open("rb") as source:
        for packet in packets:
            frame=hdr10plus_master.picture_number(packet,time_base,program.fps,count)
            block=sample_metadata(source,int(packet[b"pos"]),int(packet[b"size"]),width)
            if frame in seen or block is None or conformance_issues(block):
                raise ValueError("The final master contains an invalid or duplicate HDR10+ picture record")
            seen.add(frame)
    if len(seen)!=count:
        raise ValueError("The final master is missing HDR10+ picture records")
    return count


def retained_reference(folder,project_copy,receipt,originals,pin,expected_hash):
    folder=folder.resolve(strict=True)
    prior=json.loads((folder/"qualification.json").read_bytes())
    signatures=json.loads(pin.read_bytes())["source_signatures"]
    if (not prior.get("original_files_match") or
        any(prior.get(key)!=receipt[key] for key in ("source_project_sha256","range","frames","output")) or
        any(signatures.get(str(path))!=list(identity) for path,identity in originals.items()) or
        (folder/"range.vlogcraft").read_bytes()!=project_copy.read_bytes()):
        raise ValueError("The retained reference does not match the pinned sources, range, or profile")
    backend=prior.get("first_export",{}).get("delivered_backend")
    if backend=="reference":
        master,timing_record=folder/"first-export.mp4",prior["fallback"]
    elif backend=="d3d11" and prior.get("passed") and prior.get("independent_comparison",{}).get("passed"):
        master,timing_record=folder/"reference.mp4",prior["reference"]
    else:
        raise ValueError("The prior run has no verified managed reference for this range")
    if sha256(master.read_bytes()).hexdigest()!=expected_hash.lower():
        raise ValueError("The retained reference differs from the recorded master hash")
    return master,timing_record


def qualify(project,folder,first,last,worker,runtime,author_dll,*,plan_only=False,fault=None,retained=None,parallel_x265=False):
    import server

    original=project.read_bytes()
    document=json.loads(original)
    if document.get("version")!=4:
        raise ValueError("Use a frame-aligned v4 saved project with the verified color contract")
    full=server.validate_document(document)
    originals=source_snapshot(full)
    state=camera_range(full,first,last)
    folder=folder.resolve()
    folder.mkdir(parents=True,exist_ok=False)
    receipt={"source_project_sha256":sha256(original).hexdigest(),"range":[first,last],
             "frames":last-first,"passed":False}
    try:
        path=folder/"range.vlogcraft"
        project_store.save(path,timing.encode(state),server.validate_document)
        state,recovered=project_store.load(path,server.validate_document)
        if recovered or state is None or hdr10plus_master.preflight(state)!=last-first:
            raise ValueError("Saved range did not reopen at the requested picture count")
        program=compile_project(state,folder)
        eligible(state,program,camera_range=True)
        original_clock=verify_original_requests(full,program,first,last)
        receipt.update(planned=True,spans=program.spans,
                       selected_source_count=len(program.sources),original_source_requests_matched=original_clock,
                       output=state["output"])
        if plan_only:
            return receipt

        options=author_options(author_dll) if author_dll else None
        candidate=folder/"first-export.mp4"
        reference=folder/"reference.mp4"
        diagnostics=folder/"native"
        record=receipt["first_export"]={}

        def report(percent,message):
            print(f"{percent}% {message}",flush=True)

        def fallback():
            began=time.perf_counter()
            receipt["fallback"]=export_project(state,candidate,authoring=options)
            receipt["fallback"]["seconds"]=time.perf_counter()-began

        export_native(state,candidate,None,worker,runtime,first_time=True,camera_range=True,parallel_x265=parallel_x265,
                      authoring=options,record=record,fallback=fallback,fault=fault,progress=report,
                      diagnostics=diagnostics)
        if record["delivered_backend"]=="reference" and fault is None:
            # A rejected encode can be compared with the managed fallback that
            # just rendered. If it failed earlier, there is no encode to compare.
            reference,candidate=candidate,diagnostics/"master.mp4"
            if not candidate.is_file():
                return receipt
            receipt["reference"]=receipt["fallback"]
        elif retained:
            reference,receipt["reference"]=retained_reference(retained[0],path,receipt,originals,*retained[1:])
            receipt["reused_verified_reference"]=True
        else:
            began=time.perf_counter()
            receipt["reference"]=export_project(state,reference,authoring=options)
            receipt["reference"]["seconds"]=time.perf_counter()-began
        began=time.perf_counter()
        comparison=compare_project(reference,candidate,program,folder)
        checks={label:verify_hdr10plus_packets(path,program)
                for label,path in (("reference",reference),("first_export",candidate))}
        receipt.update(independent_comparison=comparison,comparison_seconds=time.perf_counter()-began,
                       file_bytes={"reference":reference.stat().st_size,"first_export":candidate.stat().st_size},
                       conforming_hdr10plus_blocks=checks)
        expected=record["delivered_backend"]==("d3d11" if fault is None else "reference")
        if fault is not None:
            expected=expected and record.get("native_fault_injected") is True
        receipt["passed"]=expected and comparison["passed"]
        return receipt
    finally:
        unchanged=original==project.read_bytes() and originals==source_snapshot(full)
        receipt["original_files_match"]=unchanged
        receipt["passed"]=receipt["passed"] and unchanged
        (folder/"qualification.json").write_text(json.dumps(receipt,indent=2)+"\n",encoding="utf8")


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project",type=Path)
    parser.add_argument("output",type=Path)
    parser.add_argument("--frames",type=int,nargs=2,metavar=("FIRST","LAST"),required=True,
                        help="Zero-based half-open range on the supplied project's timeline")
    parser.add_argument("--worker",type=Path)
    parser.add_argument("--runtime",type=Path)
    parser.add_argument("--author-dll",type=Path)
    parser.add_argument("--plan-only",action="store_true")
    parser.add_argument("--parallel-x265",action="store_true",
                        help="Use eight x265 pool workers with the saved Slow preset and two frame threads")
    parser.add_argument("--fault-frame",type=int)
    parser.add_argument("--retained-reference",type=Path,metavar="RUN",
                        help="Use the matching managed baseline from a previous run after the native attempt")
    parser.add_argument("--pinned-sources",type=Path,metavar="RECEIPT")
    parser.add_argument("--reference-sha256")
    args=parser.parse_args()
    if not args.plan_only and (not args.worker or not args.runtime):
        parser.error("Qualification requires the D3D11 project worker and its DLL directory")
    if args.fault_frame is not None and (args.plan_only or not 1<=args.fault_frame<args.frames[1]-args.frames[0]):
        parser.error("The fault must be injected after the first picture and within the rendered range")
    retained=(args.retained_reference,args.pinned_sources,args.reference_sha256)
    if any(retained) and (not all(retained) or args.fault_frame is not None or args.plan_only):
        parser.error("Reference reuse requires its run directory, pinned source receipt and SHA-256")
    result=qualify(args.project,args.output,*args.frames,args.worker,args.runtime,args.author_dll,
                   plan_only=args.plan_only,fault=args.fault_frame,parallel_x265=args.parallel_x265,retained=retained if all(retained) else None)
    print(json.dumps(result))
    sys.exit(0 if result["original_files_match"] and (args.plan_only or result["passed"]) else 1)
