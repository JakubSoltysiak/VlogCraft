"""Independent first-export checks for the bounded Radeon 890M straight-cut subset."""
from fractions import Fraction
from pathlib import Path
import json
import re

import numpy as np

import color_management
import hdr10plus_export
from hdr10plus_index import SIDE_DATA
import hdr_render
from native_project_plan import Ineligible, run_capture
import render_engine
import sequences
import timing


READ = re.compile(rb"Read frame with in pts (-?\d+), out pts (-?\d+)")
WRITE = re.compile(rb"Writing frame with pts (-?\d+) to pts (-?\d+)")

# The physical camera-range qualification tool opts in to longer trials.
# Application admission retains the original 120-picture fixture contract.
CAMERA_RANGE_FRAMES = 3600


def eligible(state,program,*,camera_range=False):
    flat=sequences.playback(state)
    output=flat["output"]
    contract=color_management.validate_output(output["color"])
    frame_limit=CAMERA_RANGE_FRAMES if camera_range else 120
    if ((program.width,program.height,program.fps)!=(3840,2160,60) or
        not 2<=len(program.frames)<=frame_limit or len(program.spans)>2 or
        not ("mastering" in contract and "maxCLL" in contract)):
        raise Ineligible("First export requires a short UHD60 project with complete HDR mastering declarations")
    profile=(output.get("preset"),output.get("crf"),output.get("bitrate",0))
    if camera_range and profile!=("slow",20,60):
        raise Ineligible("Camera-range first export requires the saved Slow CRF 20 and 60 Mb/s settings")
    if not camera_range and profile!=("ultrafast",15,0):
        raise Ineligible("First export requires the qualified Ultrafast CRF 15 output profile")
    video=[(track,clip) for track in flat["tracks"] if track["type"]=="video" and not track.get("hidden")
           for clip in track["clips"]]
    if (not 1<=len(video)<=2 or len({track["id"] for track,_ in video})!=1 or
        len(video)!=len(program.sources) or any(clip["kind"]=="sequence" for track in state["tracks"]
                                                for clip in track["clips"])):
        raise Ineligible("First export supports one picture track with at most two straight-cut video clips")
    neutral=hdr10plus_export.NEUTRAL.copy()
    for key in ("position","start","volume","audioDetached","bass","treble","pan","compress","hdrExposure"):
        neutral.pop(key)
    for _,clip in video:
        if (clip["kind"]!="video" or clip.get("transitionIn") or
            any(clip.get(name,value)!=value for name,value in neutral.items()) or
            set(clip.get("keys",{}))-{"volume"} or clip.get("hdrExposure",0) not in (0,.2) or
            clip.get("inputColor",{}).get("profile","source")!="source"):
            raise Ineligible("First export supports opaque straight cuts, with the qualified neutral or SDR exposure")
    for src in program.sources:
        if src.kind!="video" or src.orientation not in ("","transpose=clock") or src.interpretation[3]!="limited":
            raise Ineligible("First export requires qualified limited-range SDR/PQ video and orientation")
    if any(len(layers)!=1 or weight!=-1 for weight,layers in program.frames):
        raise Ineligible("First export requires continuous opaque pictures")
    return flat,contract


def source_ids(src,seek,rate,count,base,origin,cancelled=lambda:False):
    command=["ffmpeg","-hide_banner","-loglevel","debug","-nostdin","-noautorotate"]
    render_engine._media_input(command,src.path,"video",float(seek),1,count/rate,rate,"video")
    command+=["-map","0:v:0","-vf",f"setpts=PTS/1,fps={rate}:start_time=0:round=up",
              "-frames:v",str(count),"-f","null","-"]
    _,logs=run_capture(command,timeout=max(120,count//4),cancelled=cancelled)
    offset=timing.nearest((origin+seek)/base)
    seen,selected={},{}
    for line in logs.splitlines():
        if event:=READ.search(line):
            seen[int(event[2])]=int(event[1])+offset
        if event:=WRITE.search(line):
            chosen=seen.get(int(event[1]))
            if chosen is None:
                raise Ineligible("The independent source clock returned an incomplete picture")
            selected[int(event[2])]=chosen
    if any(index not in selected for index in range(count)):
        raise Ineligible("The independent source clock returned too few pictures")
    return [selected[index] for index in range(count)]


def verify_source_clocks(program,clocks,cancelled):
    checked=0
    for slot,(base,origin,stamps,selected) in clocks.items():
        src=program.sources[slot]
        for first,last in program.spans:
            indices=[index for index in range(first,last) if selected[index]>=0]
            if not indices:
                continue
            if len(indices)!=last-first:
                raise Ineligible("Video selection changed inside a straight-cut span")
            expected=source_ids(src,src.requests[first],program.fps,last-first,base,origin,cancelled)
            if any(stamps[selected[index]]!=pts for index,pts in zip(indices,expected,strict=True)):
                raise Ineligible("The independent decoder selected a different presentation timestamp")
            checked+=len(expected)
    if checked!=len(program.frames):
        raise Ineligible("The independent decoder did not verify every source picture selection")
    return checked


def source_snapshot(flat):
    ids={clip.get("assetId") for track in flat["tracks"] if not track.get("hidden") for clip in track["clips"]}
    paths=sorted({Path(asset["path"]).resolve(strict=True) for asset in flat["assets"] if asset["id"] in ids})
    result={}
    for path in paths:
        stat=path.stat()
        result[path]=(stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns)
    return result


def verify_static(frames,contract):
    mastering=contract["mastering"]
    expected={}
    for label,point in zip(("red","green","blue","white_point"),[*mastering["primaries"],mastering["whitePoint"]],strict=True):
        for axis,value in zip(("x","y"),point,strict=True):
            expected[f"{label}_{axis}"]=Fraction(round(value*50000),50000)
    for label,key in (("min_luminance","minLuminance"),("max_luminance","maxLuminance")):
        expected[label]=Fraction(round(mastering[key]*10000),10000)
    master_count=light_count=0
    for frame in frames:
        for row in hdr10plus_export.static_metadata(frame):
            if row["side_data_type"]=="Mastering display metadata":
                if any(key not in row or Fraction(row[key])!=value for key,value in expected.items()):
                    return False
                master_count+=1
            else:
                if (row.get("max_content"),row.get("max_average"))!=(contract["maxCLL"],contract["maxFALL"]):
                    return False
                light_count+=1
    return bool(master_count and light_count)


def verify_audio(flat,candidate,program,work,runner,cancelled):
    entries=[]
    for number,(first,last) in enumerate(program.spans):
        start,end=float(first/program.fps),float(last/program.fps)
        target=work/f"audio-{number}.wav"
        runner(render_engine.segment_command(flat,start,end,target,work,"final","audio"),str(work))
        elapsed=round(end*1_000_000)-round(start*1_000_000)
        entries.append(f"file '{target.name}'\nduration {elapsed/1e6:.6f}\n")
    playlist=work/"audio-only.txt"
    playlist.write_text("".join(entries),encoding="utf8")
    isolated=work/"audio-only.m4a"
    runner(["ffmpeg","-v","error","-nostdin","-f","concat","-safe","0","-i",str(playlist),
            "-c:a","aac","-b:a","192k","-movie_timescale","120000","-movflags","+faststart",str(isolated)],str(work))
    def decoded(path):
        return run_capture(["ffmpeg","-v","error","-threads","2","-i",path,"-map","0:a:0","-f","s16le","-"],
                           cancelled=cancelled)[0]
    return decoded(candidate)==decoded(isolated)


def compare_samples(flat,candidate,program,work,cancelled):
    samples=sorted({index for first,last in program.spans for index in (first,(first+last-1)//2,last-1)})
    filters="select='"+"+".join(f"eq(n,{frame})" for frame in samples)+"'"
    data=run_capture(["ffmpeg","-v","error","-threads","2","-i",candidate,"-vf",filters,
                      "-an","-fps_mode","passthrough","-c:v","rawvideo","-threads:v","1","-f","rawvideo","-"],
                     timeout=max(90,len(program.frames)//4),cancelled=cancelled)[0]
    values=np.frombuffer(data,dtype="<u2").reshape(len(samples),program.width*program.height*3//2)
    scores=[]
    for index,actual in zip(samples,values,strict=True):
        fps=program.fps
        command=hdr_render.command(flat,float(index/fps),float((index+1)/fps),work/f"sample-{index}.mov",work)
        raw=run_capture([*command[:command.index("-c:v")],"-c:v","rawvideo","-threads:v","1","-f","rawvideo","-"],
                        cancelled=cancelled)[0]
        desired=np.frombuffer(raw,dtype="<u2")
        if desired.shape!=actual.shape:
            raise Ineligible("The independent renderer did not return exactly one sample picture")
        error=actual.astype(np.float32)-desired
        mse=np.mean(error**2,dtype=np.float64)
        score=float(10*np.log10(1023**2/mse)) if mse else None
        scores.append({"frame":index,"decoded_to_managed_raw_psnr_db":score})
    return scores


def verify_delivery(flat,contract,candidate,program,clocks,receipt,work,runner,cancelled):
    if receipt.get("adapter")!="AMD Radeon(TM) 890M Graphics":
        raise Ineligible("First-export delivery is qualified only on the Radeon 890M adapter")
    clip_clocks=verify_source_clocks(program,clocks,cancelled)
    video,audio=hdr10plus_export.media(candidate)
    frames=json.loads(run_capture(["ffprobe","-v","error","-select_streams","v:0","-show_frames",
                                   "-show_entries","frame=pts:frame_side_data","-of","json",candidate],
                                  timeout=max(90,len(program.frames)//4),cancelled=cancelled)[0])["frames"]
    count=len(program.frames)
    end=timing.sample_at(count,program.fps)
    if ((video["width"],video["height"],video["time_base"],video["duration_ts"])!=
        (program.width,program.height,"1/120000",int(count*120000/program.fps)) or
        Fraction(video["avg_frame_rate"])!=program.fps or len(frames)!=count or
        any(int(frame["pts"])*program.fps!=index*120000 for index,frame in enumerate(frames)) or
        (audio["time_base"],audio["start_pts"],audio["duration_ts"],audio["channels"],audio["channel_layout"])!=
        ("1/48000",0,end,2,"stereo") or audio["sample_rate"]!="48000" or not verify_static(frames,contract)):
        raise Ineligible("The first-export delivery declarations or clocks did not match the project")
    if any(sum(row.get("side_data_type")==SIDE_DATA for row in frame.get("side_data_list",()))!=1 for frame in frames):
        raise Ineligible("The first-export HDR10+ metadata count did not match the picture clock")
    audio_exact=verify_audio(flat,candidate,program,work,runner,cancelled)
    sampled=compare_samples(flat,candidate,program,work,cancelled)
    quality=all(row["decoded_to_managed_raw_psnr_db"] is None or row["decoded_to_managed_raw_psnr_db"]>=50 for row in sampled)
    return dict(passed=audio_exact and quality,verified_source_pictures=clip_clocks,exact_video_pts=True,
                exact_decoded_pcm=audio_exact,audio_endpoint_samples=end,static_hdr_matches=True,
                hdr10plus_picture_associations=count,visual_checks=sampled,unsampled_pictures=count-len(sampled))
