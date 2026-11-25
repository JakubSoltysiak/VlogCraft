"""Compile validated HDR project operations to the experimental D3D11 program."""
from bisect import bisect_right
from dataclasses import dataclass, field
from fractions import Fraction
import json
import math
from pathlib import Path
import struct
import subprocess
from time import monotonic

import numpy as np

import animation
import color_management
import hdr_layers
import hdr_render
import native_source_seek
import render_engine
import sequences
import timeline_transitions
import timing


LAYER_BUDGET = 8
MOTION = {**hdr_layers.GEOMETRY, "opacity": 1., "maskRadius": .5}
TRANSITIONS = {"dissolve":2, "dip-black":3, "dip-white":4}
MASKS = {"none":0, "ellipse":1, "rectangle":2}


class Ineligible(ValueError):
    """A managed project must be rendered by the existing reference path."""


@dataclass
class Source:
    path: Path
    size: tuple
    orientation: str
    fitted: tuple
    kind: str
    asset: dict | None
    interpretation: tuple
    requests: dict = field(default_factory=dict)


@dataclass
class Program:
    width: int
    height: int
    fps: Fraction
    white: float
    spans: list
    sources: list = field(default_factory=list)
    frames: list = field(default_factory=list)


def value_at(clip, name, source_time, default):
    keys = clip.get("keys",{}).get(name,())
    if not keys:
        return float(clip.get(name,default))
    stamps = [timing.rational(key["time"]) for key in keys]
    index = bisect_right(stamps,source_time)-1
    if index<0 or index==len(keys)-1:
        return float(keys[max(0,index)]["value"])
    a,b = keys[index:index+2]
    u = float((source_time-stamps[index])/(stamps[index+1]-stamps[index]))
    mode = a["mode"]
    if mode=="hold":
        u=0.
    elif mode=="ease-in":
        u=u*u
    elif mode=="ease-out":
        u=u*(2-u)
    elif mode=="ease-in-out":
        u=u*u*(3-2*u)
    elif mode=="bezier":
        x=min(63,int(u*64))
        start=animation.bezier(x/64,a["handles"]) if x else 0.
        end=animation.bezier((x+1)/64,a["handles"]) if x<63 else 1.
        u=start+(end-start)*(u*64-x)
    return a["value"]+(b["value"]-a["value"])*u


def admitted_layer(assets,clip,width,height):
    asset,size,orientation,interpretation = hdr_render.layer_contract(assets,clip,width,height)
    if timing.rational(clip.get("speed",1))!=1:
        raise Ineligible("Changing clip speed requires the managed renderer")
    if any(clip.get(key,1)!=1 or clip.get("keys",{}).get(key) for key in ("contrast","saturation")):
        raise Ineligible("Contrast and saturation require the managed renderer")
    if clip.get("crop"):
        raise Ineligible("An explicit clip crop needs managed rendering")
    if clip["kind"]=="video" and interpretation[:3] not in (
            ("bt709","bt709","bt709"),("bt2020","smpte2084","bt2020nc")):
        raise Ineligible("The source color interpretation is outside resident SDR/PQ")
    return asset,size,orientation,interpretation


def fitted_size(size,canvas,fit):
    sx,sy = size
    w,h = canvas
    ratio = (max if fit=="cover" else min)(Fraction(w,sx),Fraction(h,sy))
    return max(1,round(sx*ratio)),max(1,round(sy*ratio))


def compile_project(state,work,*,camera_raster=False):
    state = sequences.playback(state)
    output = state["output"]
    contract = color_management.validate_output(output["color"])
    if contract["output"]!="hdr10" or output["encoder"]!="libx265":
        raise Ineligible("Resident project export requires managed Main10/PQ")
    width,height = output["width"],output["height"]
    fps = timing.rate(output["fps"])
    if width%4 or height%2 or not width or not height or width>7680 or height>4320:
        raise Ineligible("The project dimensions are outside packed Main10 support")
    spans = render_engine.frame_spans(state,fps)
    if not spans or not 0<spans[-1][1]<=7200:
        raise Ineligible("The native timeline is outside its current instruction budget")
    program = Program(width,height,fps,contract["sdrWhiteNits"]/100,spans)
    assets = {asset["id"]:asset for asset in state["assets"]}
    pairs = timeline_transitions.plan(state)[0]
    slots = {}

    def layer(clip,frame,span_start,operation):
        asset,size,orientation,interpretation = admitted_layer(assets,clip,width,height)
        kind = clip["kind"]
        path = (hdr_layers.title_image(clip,width,height,work) if kind=="title" else Path(asset["path"]))
        if not path.is_file():
            raise FileNotFoundError("A project source is missing")
        fit = clip.get("fit","contain")
        key = (clip["id"],) if kind=="video" else (path,orientation,fit)
        if key not in slots:
            if len(program.sources)>=LAYER_BUDGET:
                raise Ineligible("Project exceeds the experimental resident source budget")
            slots[key] = len(program.sources)
            size_fit = fitted_size(size,(width,height),fit)
            program.sources.append(Source(path,size,orientation,size_fit,kind,asset,interpretation))
        slot = slots[key]
        elapsed = (frame-timing.frame_at(clip["position"],fps))/fps
        clock = timing.rational(clip["start"])+elapsed
        if kind=="video":
            first = max(span_start,timing.frame_at(clip["position"],fps))
            seek = timing.rational(clip["start"])+(first-timing.frame_at(clip["position"],fps))/fps
            # The managed decoder requests this microsecond-rounded preroll at
            # each rendering span. Keep the selection in the original clock.
            seek = Fraction(math.ceil(seek*1000000-Fraction(1,100000000)),1000000)
            program.sources[slot].requests[frame] = seek+(frame-first)/fps
        values = {name:value_at(clip,name,clock,default) for name,default in MOTION.items()}
        opacity = values["opacity"]
        if clip.get("fadeIn"):
            opacity *= min(1.,max(0.,float(elapsed)/clip["fadeIn"]))
        if clip.get("fadeOut"):
            remaining = render_engine.clip_length(clip)-float(elapsed)
            opacity *= min(1.,max(0.,remaining/clip["fadeOut"]))
        angle = math.radians(values["rotation"])
        geo = (values["scale"],math.cos(angle),math.sin(angle),values["x"],values["y"])
        gain = 2**clip.get("hdrExposure",0)
        if interpretation[4] in ("rec709","srgb"):
            gain *= program.white
        packed = (*geo,opacity,values["maskRadius"],max(.00001,clip.get("feather",.1)),
                  slot,MASKS[clip.get("mask","none")],operation,gain)
        return packed,geo

    for start,end in spans:
        video,_ = render_engine.active_clips(state,float(start/fps),float(end/fps))
        matching = [pair for pair in pairs if pair.end>start and pair.start<end]
        if len(matching)>1:
            raise Ineligible("Overlapping picture transitions need the managed renderer")
        pair = matching[0] if matching else None
        for frame in range(start,end):
            rows = []
            weight = -1.
            for track in reversed(state["tracks"]):
                if pair and track is pair.track:
                    left,right = pair.virtual(fps)
                    rows.append(layer(left,frame,start,1))
                    rows.append(layer(right,frame,start,TRANSITIONS[pair.kind]))
                    weight = float(Fraction(frame-pair.start,pair.end-pair.start-1))
                    if pair.ease=="smooth":
                        weight = weight*weight*(3-2*weight)
                else:
                    rows.extend(layer(clip,frame,start,0) for owner,clip in video if owner is track)
            if len(rows)>LAYER_BUDGET:
                raise Ineligible("Project exceeds the experimental simultaneous layer budget")
            program.frames.append((weight,rows))
    if not program.sources or sum(src.kind=="video" for src in program.sources)>(LAYER_BUDGET if camera_raster else 4):
        raise Ineligible("The native project requires between one and eight sources, with up to four videos")
    return program


def write_plan(path,program):
    with path.open("wb") as output:
        output.write(struct.pack("<4I",program.width,program.height,len(program.sources)|0xc0000000,len(program.frames)))
        for weight,rows in program.frames:
            output.write(struct.pack("<3If",program.width,program.height,len(rows),weight))
            for packed,_ in rows:
                output.write(struct.pack("<8f3If",*packed))
            output.write(bytes(48*(LAYER_BUDGET-len(rows))))
            output.write(struct.pack("<If2I",1,program.white,0,0))
        for _,rows in program.frames:
            for _,geo in rows:
                output.write(struct.pack("<5d",*geo))
            output.write(struct.pack("<5d",1,1,0,0,0)*(LAYER_BUDGET-len(rows)))


def run_capture(command,timeout=90,*,cancelled=lambda:False,cwd=None):
    args = [str(value) for value in command]
    deadline = monotonic()+timeout
    with subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                          cwd=cwd,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0)) as process:
        try:
            while not cancelled() and monotonic()<deadline:
                try:
                    output,errors = process.communicate(timeout=.2)
                except subprocess.TimeoutExpired:
                    continue
                if process.returncode:
                    raise subprocess.CalledProcessError(process.returncode,args,output,errors)
                return output,errors
            raise RuntimeError("Project export cancelled or verification timed out")
        finally:
            if process.poll() is None:
                process.kill()


def append_video(output,slot,src,frame_count,cancelled,*,first_time=False,camera_range=False,keyframe_seek=False,camera_raster=False):
    limit = max(src.requests.values())+2
    stream_fields = ("stream=width,height,time_base,codec_name,profile,pix_fmt,color_primaries,color_transfer,"
                     "color_space,color_range,field_order,nb_frames,start_pts,duration_ts")
    indexed = None
    if keyframe_seek and src.path.suffix.lower() in (".mp4",".mov",".m4v"):
        indexed = native_source_seek.probe(src.path,limit,stream_fields,run_capture,cancelled)
    # The resident decoder checks this index against every decoded PTS in its
    # prefix. An independent software trace still checks the selected pictures.
    packet_index = False
    access_points = []
    if indexed is not None:
        info,stamps,access_points=indexed
    else:
        if limit>122:
            raise Ineligible("Source selection exceeds the qualified resident preroll window")
        packet_index = (not keyframe_seek and camera_range and (src.asset or {}).get("codec")=="hevc" and
                        src.path.suffix.lower()==".mp4" and min(src.requests.values())>0)
        clock_fields = "packet=pts,flags" if packet_index else "frame=best_effort_timestamp"
        format_fields = "start_time,format_name" if packet_index else "start_time"
        fields = f"{stream_fields}:{clock_fields}:format={format_fields}"
        if camera_range:
            fields += ":stream_side_data=rotation"
        info = json.loads(run_capture(["ffprobe","-v","error","-read_intervals",f"%+{float(limit):.8f}",
                                       "-select_streams","v:0","-show_entries",fields,"-of","json",src.path],
                                      cancelled=cancelled)[0])
    streams = info.get("streams",())
    if len(streams)!=1:
        raise Ineligible("The resident probe found no unambiguous video stream")
    video = streams[0]
    if packet_index and (video.get("codec_name")!="hevc" or
                         "mp4" not in info.get("format",{}).get("format_name","").split(",")):
        raise Ineligible("Camera packet indexing requires a probed HEVC MP4 stream")
    if camera_range:
        coded_size=src.size[::-1] if src.orientation else src.size
        rotation=90 if src.orientation=="transpose=clock" else 0
        actual_angles=[(-row["rotation"])%360 for row in video.get("side_data_list",()) if "rotation" in row]
        if ((video.get("width"),video.get("height"))!=coded_size or (actual_angles or [0])!=[rotation]):
            raise Ineligible("The camera stream dimensions or orientation differ from the project")
    tags = tuple(video.get(key) for key in ("color_primaries","color_transfer","color_space"))
    pq = tags==("bt2020","smpte2084","bt2020nc")
    codec=(video.get("codec_name"),video.get("pix_fmt"),pq)
    camera_sdr=(camera_range and src.orientation=="" and video.get("profile")=="Main" and
                codec==("hevc","yuv420p",False))
    if first_time and not camera_sdr and codec not in (("h264","yuv420p",False),("hevc","yuv420p10le",True)):
        detail="the selected H.264 SDR or HEVC SDR/PQ scope" if camera_range else "qualified H.264 SDR or HEVC Main10 PQ video"
        raise Ineligible("First export requires "+detail)
    if first_time and pq and video.get("profile")!="Main 10":
        raise Ineligible("First export requires the qualified HEVC Main10 profile")
    if (video.get("codec_name") not in ("h264","hevc") or video.get("pix_fmt") not in ("yuv420p","yuv420p10le") or
            video.get("field_order") not in (None,"unknown","progressive") or
            (not pq and tags!=("bt709","bt709","bt709")) or
            video.get("color_range")!=({"limited":"tv","full":"pc"}.get(src.interpretation[3])) or
            pq!=(src.interpretation[4]=="pq2020")):
        raise Ineligible("Resident codec, range or source metadata differs from the managed color contract")
    if packet_index:
        packets=info.get("packets",())
        if any(not isinstance(row.get("flags"),str) or "D" in row["flags"] for row in packets):
            raise Ineligible("Camera trim has ambiguous or discarded packets outside the packet-index experiment")
        stamps=[row.get("pts") for row in packets]
    elif indexed is None:
        stamps=[row.get("best_effort_timestamp") for row in info.get("frames",())]
    if not stamps or any(type(stamp) is not int for stamp in stamps):
        raise Ineligible("The resident probe did not return integer source presentation timestamps")
    if packet_index:
        stamps.sort()
    base = Fraction(video.get("time_base") or 0)
    origin = Fraction(info.get("format",{}).get("start_time","0"))
    if packet_index and (origin<0 or stamps[0]<0):
        raise Ineligible("Camera packet indexing requires a nonnegative source clock")
    if any(a>=b for a,b in zip(stamps,stamps[1:])) or base<=0:
        raise Ineligible("Resident source has an ambiguous presentation clock")
    selected = [-1]*frame_count
    terminal=0
    for frame,target in src.requests.items():
        tick = (target+origin)/base
        if tick>=stamps[-1]:
            end_pts=video.get("start_pts",0)
            duration=video.get("duration_ts")
            if not (camera_raster and indexed is not None and str(len(stamps))==video.get("nb_frames")
                    and type(end_pts) is int and type(duration) is int and duration>0 and end_pts+duration>stamps[-1]):
                raise Ineligible("The selected range extends beyond the available source pictures")
            if tick>=end_pts+duration:
                terminal+=1
                if terminal>6 or (tick-end_pts-duration)*base>=Fraction(6,60):
                    raise Ineligible("The camera hold exceeds the qualified video endpoint")
        selected[frame] = max(0,bisect_right(stamps,tick)-1)
    last = max(selected)+1
    access_points = [point for point in access_points if 0 < point.picture < last]
    if limit>122:
        first = min(picture for picture in selected if picture>=0)
        if not any(point.picture<=first for point in access_points):
            raise Ineligible("A late source range requires a verified preceding random-access picture")
    angle = next(code for code,orientation in hdr_layers.VIDEO_ORIENTATION.items() if orientation==src.orientation)
    name = str(src.path.resolve()).encode("utf-8")
    output.write(struct.pack("<11I",slot,len(name),video["width"],video["height"],*src.fitted,
                             angle,int(pq),last,base.numerator,base.denominator))
    output.write(name)
    np.asarray(stamps[:last],dtype="<i8").tofile(output)
    np.asarray(selected,dtype="<i4").tofile(output)
    if keyframe_seek:
        output.write(struct.pack("<I",len(access_points)))
        for point in access_points:
            output.write(struct.pack("<qqII",point.dts,point.position,point.picture,point.kind))
            output.write(struct.pack("<I",len(point.decodable_leading)))
            np.asarray(point.decodable_leading,dtype="<i8").tofile(output)
    return base,origin,stamps[:last],selected


def append_still(output,slot,src,program,cancelled):
    width,height = program.width,program.height
    filters = []
    chain = hdr_layers.linear_still(filters,0,hdr_layers.luma_linear(*hdr_layers.SRGB[:4]))
    if src.orientation:
        chain += ","+src.orientation
    chain += ",setsar=1,premultiply=inplace=1"
    # The actual canvas choice was resolved from the same contain/cover rule.
    fit = "cover" if any(a>b for a,b in zip(src.fitted,(width,height))) else "contain"
    chain = hdr_layers.canvas_fit(filters,chain,"still",source=src.size,canvas=(width,height),
                                  fit=fit,fps=program.fps)
    filters.append(chain+"[prepared]")
    raw = run_capture(["ffmpeg","-v","error","-nostdin","-noauto_conversion_filters","-filter_complex_threads","1",
                       "-f","image2","-pattern_type","none","-framerate",program.fps,"-i",src.path,
                       "-filter_complex",";".join(filters),"-map","[prepared]","-frames:v","1",
                       "-c:v","rawvideo","-threads:v","1","-f","rawvideo","pipe:1"],cancelled=cancelled)[0]
    if len(raw)!=width*height*16:
        raise ValueError("Invalid managed still-picture size")
    planes = np.frombuffer(raw,dtype="<f4").reshape(4,height,width)
    rgba = np.empty((height,width,4),dtype="<f4")
    for index,plane in enumerate((2,0,1,3)):
        rgba[...,index] = planes[plane]
    output.write(struct.pack("<I",slot))
    rgba.tofile(output)


def write_sources(path,program,cancelled=lambda:False,*,first_time=False,camera_range=False,keyframe_seek=False,camera_raster=False):
    clocks={}
    with path.open("wb") as output:
        videos = [(n,src) for n,src in enumerate(program.sources) if src.kind=="video"]
        stills = [(n,src) for n,src in enumerate(program.sources) if src.kind!="video"]
        output.write(struct.pack("<4s2I",b"VSD3" if keyframe_seek else b"VSD2",len(videos),len(stills)))
        for slot,src in videos:
            clocks[slot]=append_video(output,slot,src,len(program.frames),cancelled,
                                      first_time=first_time,camera_range=camera_range,keyframe_seek=keyframe_seek,
                                      camera_raster=camera_raster)
        for slot,src in stills:
            append_still(output,slot,src,program,cancelled)
    return clocks
