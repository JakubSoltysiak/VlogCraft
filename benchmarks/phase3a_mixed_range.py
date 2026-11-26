"""Create and independently audit a frame-aligned v4 mixed project excerpt."""
import argparse
from bisect import bisect_right
from collections import Counter
from copy import deepcopy
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace

if not __package__:
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

import hdr_layers
from mixed_export import MAX_FRAMES, MAX_SPANS
from native_project_plan import run_capture
from native_project_verification import source_ids, source_snapshot
import native_source_seek
import render_engine
import server
import timing


def validate_v4(document):
    if document.get("version") != 4:
        raise ValueError("Choose a v4 saved project with exact source ticks")
    if any(clip.get("transitionIn") or clip["kind"] not in ("video","image","audio")
           for track in document["tracks"] for clip in track["clips"]):
        raise ValueError("Mixed excerpt auditing requires flat camera, still and audio clips with straight cuts")
    return server.validate_document(document)


def clip_range(document, first, last):
    """Copy the saved document and rebase only the selected frames and source ticks."""
    state = validate_v4(document)
    fps = timing.rate(state["output"]["fps"])
    if not 0 <= first < last <= timing.frame_at(render_engine.sequence_duration(state),fps):
        raise ValueError("The requested range is outside the saved timeline")
    if not 2 <= last-first <= MAX_FRAMES:
        raise ValueError(f"Select between 2 and {MAX_FRAMES} output pictures")
    assets = {asset["id"]:asset for asset in document["assets"]}
    excerpt = deepcopy(document)
    for saved_track, track in zip(excerpt["tracks"],state["tracks"],strict=True):
        clips = []
        checked = {clip["id"]:clip for clip in track["clips"]}
        for saved in saved_track["clips"]:
            clip = checked[saved["id"]]
            stamp = saved["timing"]
            position = stamp["positionFrame"]
            finish = timing.frame_at(render_engine.clip_finish(clip),fps)
            start,stop = max(first,position),min(last,finish)
            if start>=stop:
                continue
            if (track.get("hidden") or clip.get("speed",1)!=1 or clip.get("keys") or clip.get("crop") or
                    any(clip.get(key,0)!=0 for key in ("fadeIn","fadeOut","bass","treble","pan")) or
                    clip.get("compress",1)!=1):
                raise ValueError("The excerpt contains a hidden, retimed, keyed, cropped or time-dependent clip")
            base = timing.rational(stamp["sourceTimeBase"])
            asset = assets[clip["assetId"]]
            if base!=timing.base_for(asset) or position+timing.nearest((stamp["outTick"]-stamp["inTick"])*base*fps)!=finish:
                raise ValueError("The saved clip clock does not match its asset or rendered frame boundary")
            start_ticks = Fraction(start-position)/fps/base
            end_ticks = Fraction(stop-position)/fps/base
            if start_ticks.denominator!=1 or (stop!=finish and end_ticks.denominator!=1):
                raise ValueError("An excerpt boundary is outside the source tick grid")
            original_in = stamp["inTick"]
            stamp.update(positionFrame=start-first,inTick=original_in+int(start_ticks))
            if stop!=finish:
                stamp["outTick"] = original_in+int(end_ticks)
            saved.update(position=float(stamp["positionFrame"]/fps),
                         start=float(stamp["inTick"]*base),end=float(stamp["outTick"]*base))
            clips.append(saved)
        saved_track["clips"] = clips
    validate_v4(excerpt)
    return excerpt


def seek(clip, first, fps):
    at = float(first/fps)
    return Fraction(render_engine.media_seek_microseconds(clip["start"]+max(0.,at-clip["position"])),1_000_000)


def audible(state, candidates):
    assets = {asset["id"]:asset for asset in state["assets"]}
    return [(track,clip) for track,clip in candidates
            if assets[clip["assetId"]].get("hasAudio") and render_engine._gain(track,clip)>0]


def source_bindings(pairs):
    return [(track["id"],clip["id"],clip["assetId"]) for track,clip in pairs]


def camera_floors(path, original, rebased, fps, cancelled):
    fields = "stream=time_base,codec_name,nb_frames,start_pts,duration_ts"
    index = native_source_seek.probe(path,max(original[-1],rebased[-1])+2,fields,run_capture,cancelled)
    if index is None:
        raise ValueError("The original camera has no verified H.264 or HEVC packet clock")
    info,stamps,_ = index
    stream, = info["streams"]
    base = Fraction(stream["time_base"])
    origin = Fraction(info["format"].get("start_time","0"))
    terminal = None
    def picture(at):
        nonlocal terminal
        tick = (at+origin)/base
        if tick>=stamps[-1]:
            start,duration = stream.get("start_pts",0),stream.get("duration_ts")
            if (str(len(stamps))!=stream.get("nb_frames") or type(start) is not int or
                    type(duration) is not int or start+duration<=stamps[-1] or
                    (tick-start-duration)*base>=6/fps):
                raise ValueError("Camera trim crosses an unverified packet endpoint")
            terminal = stamps[-1]
        return stamps[max(0,bisect_right(stamps,tick)-1)]
    reference = [picture(at) for at in original]
    if reference != [picture(at) for at in rebased]:
        raise ValueError("Rebasing changes the source camera packet floor")
    software = source_ids(SimpleNamespace(path=path),rebased[0],fps,len(rebased),base,origin,cancelled,
                          terminal_pts=terminal)
    if reference!=software:
        raise ValueError("The managed decoder disagrees with the source camera packet floor")
    return reference,base


def audio_clock(path, cancelled):
    output,_ = run_capture(["ffprobe","-v","error","-select_streams","a:0","-show_entries",
                            "stream=sample_rate,time_base,start_pts,duration_ts:format=start_time",
                            "-of","json",path],cancelled=cancelled)
    data = json.loads(output)
    stream, = data["streams"]
    rate = int(stream["sample_rate"])
    base = Fraction(stream["time_base"])
    origin = Fraction(data.get("format",{}).get("start_time","0"))
    start = int(stream.get("start_pts",0))*base
    length = int(stream["duration_ts"])*base*rate
    if rate<=0 or length.denominator!=1 or length<=0:
        raise ValueError("The source audio has an ambiguous sample clock")
    return rate,origin-start,int(length)


def audio_offset(clock, base, rebased, duration):
    rate,origin,length = clock
    exact,trim = (base+origin)*rate,(rebased+origin)*rate
    sample = timing.nearest(exact)
    if (sample!=timing.nearest(trim) or sample<0 or
            max(abs(exact-sample),abs(trim-sample))>Fraction(rate,1_000_000)):
        raise ValueError("Rebasing changes the audio source sample or resampling phase")
    requested = timing.nearest(duration*rate)
    return {"native_rate":rate,"source_sample_first":sample,
            "source_sample_last":max(sample,min(length,sample+requested)),
            "requested_native_samples":requested}


def pcm_slice(state, start, stop, skip, samples, work, label, cancelled):
    """Render the original audio context and select its exact output-sample interval."""
    command = render_engine.segment_command(state,start,stop,work/f"{label}.wav",work,"final","audio")
    graph = Path(command[command.index("-/filter_complex")+1])
    original = graph.read_text(encoding="utf8").rstrip()
    graph.write_text(original+f";\n[mixed]atrim=start_sample={skip}:end_sample={skip+samples},"
                     "asetpts=PTS-STARTPTS[audit]\n",encoding="utf8")
    command[command.index("[mixed]")] = "[audit]"
    duration = command.index("-t")
    del command[duration:duration+2]
    raw, _ = run_capture([*command[:-1],"-f","s16le","pipe:1"],timeout=max(90,int(stop-start)*2),
                         cancelled=cancelled)
    if len(raw)!=samples*4:
        raise ValueError("One audio graph returned an incomplete source-sample interval")
    return raw


def audit_range(original, excerpt, first, last, *, cancelled=lambda:False):
    """Compare saved bindings, per-picture source floors and original rendered audio samples."""
    planned = validate_v4(clip_range(original,first,last))
    full, trimmed = validate_v4(original),validate_v4(excerpt)
    for key in ("assets","tracks","output"):
        if planned[key]!=trimmed[key]:
            raise ValueError("The supplied excerpt differs from the immutable range's media, clips or output")
    fps = timing.rate(full["output"]["fps"])
    spans = [(a,max(a,first),min(b,last)) for a,b in render_engine.frame_spans(full,fps) if a<last and b>first]
    if (len(spans)>MAX_SPANS or
            [(a-first,b-first) for _,a,b in spans]!=render_engine.frame_spans(trimmed,fps)):
        raise ValueError("The excerpt moved an original render-span boundary")
    for frame in range(first,last+1):
        if timing.sample_at(frame,fps)-timing.sample_at(first,fps)!=timing.sample_at(frame-first,fps):
            raise ValueError("Rebasing changes the original timeline's 48 kHz rounding")
    assets = {asset["id"]:asset for asset in trimmed["assets"]}
    sources = source_snapshot(trimmed,include_hidden_audio=True)
    source_numbers = {}
    audio_clocks,still_hashes = {},{}
    mapping = hashlib.sha256()
    summary = dict(original_first=first,original_last_exclusive=last,frames=last-first,fps=str(fps),
                   verified_pcm_samples_per_channel=0,silent_spans=[],spans=[])
    counts = Counter()
    with tempfile.TemporaryDirectory(prefix="mixed-range-audit-") as directory:
        work = Path(directory)
        for number,(context,start,end) in enumerate(spans):
            local,stop = start-first,end-first
            count = end-start
            old_video,old_audio = render_engine.active_clips(full,float(context/fps),float(end/fps))
            new_video,new_audio = render_engine.active_clips(trimmed,float(local/fps),float(stop/fps))
            old_audio,new_audio = audible(full,old_audio),audible(trimmed,new_audio)
            if (source_bindings(old_video)!=source_bindings(new_video) or
                    source_bindings(old_audio)!=source_bindings(new_audio)):
                raise ValueError("Rebasing changes active source identity or layer order")
            row = dict(original=[start,end],excerpt=[local,stop],picture_sources=[],audio_sources=[])
            pictures = [[] for _ in range(count)]
            for (_,old),(_,new) in zip(old_video,new_video,strict=True):
                asset = assets[new["assetId"]]
                path = Path(asset["path"])
                ordinal = source_numbers.setdefault(new["assetId"],len(source_numbers)+1)
                if new["kind"]=="image":
                    w,h,orientation = hdr_layers.photo_info(path)
                    if path not in still_hashes:
                        with path.open("rb") as image:
                            still_hashes[path] = hashlib.file_digest(image,"sha256").hexdigest()
                    row["picture_sources"].append(dict(source=ordinal,kind="still",pictures=count,
                                                       oriented_dimensions=[w,h],orientation=orientation or "upright"))
                    for layers in pictures:
                        layers.append((ordinal,"still"))
                    counts["still"] += count
                else:
                    original_times = [seek(old,context,fps)+Fraction(frame-context)/fps for frame in range(start,end)]
                    new_times = [seek(new,local,fps)+Fraction(frame)/fps for frame in range(count)]
                    floors,base = camera_floors(path,original_times,new_times,fps,cancelled)
                    row["picture_sources"].append(dict(source=ordinal,kind="camera",pictures=count,
                                                       time_base=str(base),first_pts=floors[0],last_pts=floors[-1],
                                                       repeated=sum(a==b for a,b in zip(floors,floors[1:]))))
                    for layers,pts in zip(pictures,floors,strict=True):
                        layers.append((ordinal,"camera",pts))
                    counts["camera"] += count
            for frame,layers in enumerate(pictures,start):
                mapping.update(json.dumps([frame,layers],separators=(",",":")).encode()+b"\n")
            samples = timing.sample_at(stop,fps)-timing.sample_at(local,fps)
            source_skip = timing.sample_at(start,fps)-timing.sample_at(context,fps)
            for (_,old),(_,new) in zip(old_audio,new_audio,strict=True):
                path = Path(assets[new["assetId"]]["path"])
                if path not in audio_clocks:
                    audio_clocks[path] = audio_clock(path,cancelled)
                offset = audio_offset(audio_clocks[path],seek(old,context,fps)+Fraction(start-context)/fps,
                                      seek(new,local,fps),Fraction(count)/fps)
                ordinal = source_numbers.setdefault(new["assetId"],len(source_numbers)+1)
                row["audio_sources"].append(dict(source=ordinal,kind=new["kind"],**offset))
            pcm = pcm_slice(full,float(context/fps),float(end/fps),source_skip,samples,work,f"original-{number}",cancelled)
            if pcm!=pcm_slice(trimmed,float(local/fps),float(stop/fps),0,samples,work,f"excerpt-{number}",cancelled):
                raise ValueError("Rebasing changes the original audio graph's PCM samples")
            if not new_audio:
                if any(pcm):
                    raise ValueError("A reported silent audio interval produced nonzero samples")
                summary["silent_spans"].append(dict(original=[start,end],samples_per_channel=samples))
            summary["verified_pcm_samples_per_channel"] += samples
            summary["spans"].append(row)
    if source_snapshot(trimmed,include_hidden_audio=True)!=sources:
        raise ValueError("An original media file changed during the audit")
    for path,digest in still_hashes.items():
        with path.open("rb") as image:
            if hashlib.file_digest(image,"sha256").hexdigest()!=digest:
                raise ValueError("An original still image changed during the audit")
    summary.update(camera_source_picture_selections=counts["camera"],still_source_picture_selections=counts["still"],
                   verified_still_sources=len(still_hashes),picture_mapping_sha256=mapping.hexdigest(),
                   source_media_unchanged=True)
    return summary


def prepare(project, destination, first, last, *, check=False):
    project,destination = project.resolve(strict=True),destination.resolve()
    if (destination==project or (destination.exists() and destination.samefile(project))):
        raise ValueError("Choose a separate excerpt project")
    original_bytes = project.read_bytes()
    original = json.loads(original_bytes)
    if any(destination==Path(asset["path"]).resolve() for asset in original["assets"]):
        raise ValueError("Choose a destination different from the linked media")
    if not check and destination.exists():
        raise FileExistsError("Choose a new excerpt destination")
    excerpt_bytes = destination.read_bytes() if check else None
    excerpt = json.loads(excerpt_bytes) if check else clip_range(original,first,last)
    result = audit_range(original,excerpt,first,last)
    if project.read_bytes()!=original_bytes or (check and destination.read_bytes()!=excerpt_bytes):
        raise ValueError("The original or audited excerpt document changed")
    if not check:
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=destination.parent,delete=False) as file:
                temporary = Path(file.name)
                file.write((json.dumps(excerpt,indent=2,ensure_ascii=False)+"\n").encode("utf8"))
                file.flush()
                os.fsync(file.fileno())
            os.link(temporary,destination)
        finally:
            if temporary is not None:
                temporary.unlink()
    return result


if __name__=="__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project",type=Path)
    parser.add_argument("destination",type=Path)
    parser.add_argument("first",type=int)
    parser.add_argument("last",type=int)
    parser.add_argument("--check",action="store_true",help="Audit an existing excerpt without writing a new file")
    print(json.dumps(prepare(**vars(parser.parse_args())),indent=2))
