"""Check actual native cut/seek source identity with generated VFR colors and independent FFprobe PTS."""
import argparse
from bisect import bisect_right
import ctypes
from fractions import Fraction
import json
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks"))
from window_geometry import alignment, owned_window, Point
from window_visibility import WindowVisibility
from windows_session import session

RATE = 60
CUT = 12
# Asset index, first source frame (in sequence time), and video track.
SHOTS = [(0, 6, 0), (1, 39, 1), (2, 14, 0), (0, 55, 1),
         (1, 3, 0), (0, 47, 1), (2, 24, 0), (0, 17, 1),
         (3, 9, 0), (2, 75, 1), (3, 51, 0), (0, 4, 1)]

SETUP = """async ({assets, shots, cut, rate}) => {
  stopPlayback();refreshPlayers();state.assets=assets;state.output.fps=rate;useProxies=false;
  state.tracks=[0,1].map(n=>({id:uid(),type:'video',name:'Picture '+n,volume:1,clips:[]}));
  const ids=[];
  shots.forEach(([asset,offset,track],i)=>{
    const c=clipFromAsset(assets[asset],i*cut/rate,'video');
    c.start=offset/rate;c.end=(offset+cut)/rate;c.audioDetached=true;
    state.tracks[track].clips.push(c);ids.push(c.id);
  });
  playhead=0;redraw();save();await flushSave();return ids;
}"""


def generate(folder):
    paths = []
    references = []
    for index, name in enumerate(("red", "lime", "blue", "yellow")):
        path = folder / f"source-{index}.mp4"
        select = f"select=not(eq(mod(n\\,{5 + index})\\,2))"
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                        f"color={name}:s=320x180:r=60:d=2", "-vf", select,
                        "-fps_mode", "vfr", "-c:v", "libx264", "-threads", "1",
                        "-g", "60", "-bf", "3", "-pix_fmt", "yuv420p", "-colorspace", "bt709",
                        "-color_primaries", "bt709", "-color_trc", "bt709", "-video_track_timescale",
                        "60000", str(path)], check=True, timeout=60, capture_output=True)
        result = json.loads(subprocess.check_output([
            "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
            "stream=time_base:frame=best_effort_timestamp", "-of", "json", str(path)
        ], timeout=30))
        scale = Fraction(result["streams"][0]["time_base"])
        pts = [int(f["best_effort_timestamp"]) for f in result["frames"]]
        assert pts[0] == 0 and len(set(b-a for a,b in zip(pts,pts[1:]))) > 1, "Expected variable source intervals"
        paths.append(str(path))
        references.append((scale, pts))
    return paths, references


def verify(metrics, frame, ids, references):
    shot, local_frame = divmod(frame, CUT)
    asset, offset, _ = SHOTS[shot]
    scale, pts = references[asset]
    target = Fraction(offset + local_frame, RATE) / scale
    expected = pts[bisect_right(pts, target) - 1]
    selected = metrics["selected"]
    assert len(selected) == 1, "Wrong number of active source layers"
    row = selected[0]
    assert row["clip"] == ids[shot], f"Wrong active cut at frame {frame}"
    assert Fraction(row["timebase_num"], row["timebase_den"]) == scale
    assert row["target_tick"] == int(target) and row["pts"] == expected, (
        f"Frame {frame}: reference PTS {expected} at tick {target}, worker PTS {row['pts']} for {row['target_tick']}")
    return {"frame":frame, "source":asset, "source_tick":int(target), "selected_pts":expected,
            "held_vfr":expected < target, "generation":metrics["generation"]}


def center_color(page, process):
    """Read only one pixel from the owned and physically visible generated preview."""
    hwnd = owned_window(process)
    x, y, w, h = alignment(page, process)["actual_client_pixels"]
    center = Point(x + w//2, y + h//2)
    user = ctypes.windll.user32
    user.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
    old = user.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    try:
        user.ClientToScreen(ctypes.c_void_p(hwnd), ctypes.byref(center))
        user.WindowFromPoint.argtypes=[Point]
        user.WindowFromPoint.restype=ctypes.c_void_p
        child = user.WindowFromPoint(center)
        kind = ctypes.create_unicode_buffer(128)
        user.GetClassNameW(ctypes.c_void_p(child), kind, len(kind))
        if kind.value != "VlogCraftNativePlayback" or not user.IsChild(ctypes.c_void_p(hwnd), ctypes.c_void_p(child)):
            raise AssertionError("Native preview center was covered")
        user.GetDC.restype=ctypes.c_void_p
        dc=user.GetDC(None)
        try:
            rgb=ctypes.windll.gdi32.GetPixel(ctypes.c_void_p(dc),center.x,center.y)
        finally:
            user.ReleaseDC(None,ctypes.c_void_p(dc))
        if rgb == -1: raise RuntimeError("Windows could not read generated preview pixel")
        return [(rgb >> shift) & 255 for shift in (0,8,16)]
    finally:
        user.SetThreadDpiAwarenessContext(ctypes.c_void_p(old))


def main(args):
    folder=args.results.resolve()
    folder.mkdir(parents=True,exist_ok=False)
    report={"paused":[],"playing":[],"physical_color_checks":0,"passed":False}
    try:
        paths, references=generate(folder)
        with session(args.executable,folder,offline=True) as (page,process,_,errors):
            imported=page.evaluate("paths=>request('import','POST',{paths,autoProxy:false})",paths)
            assert not imported["errors"]
            ids=page.evaluate(SETUP,{"assets":imported["assets"],"shots":SHOTS,"cut":CUT,"rate":RATE})
            page.wait_for_function("[...$('playbackEngine').options].some(o=>o.value==='native'&&!o.disabled)")
            page.select_option("#playbackEngine","native")
            page.wait_for_function("nativeState.metrics?.completed_frames>0",timeout=30000)
            with WindowVisibility(process,"visible") as visible:
                # The last four gestures issue several directions before the worker can finish them.
                gestures=[[11],[12],[23],[24],[26],[35],[36],[47],[48],[60],[72],[84],[85],
                          [96],[107],[108],[119],[120],[132],
                          [13,116,14,39],[39,39],[127,4,50,24],[2,123,15,0]]
                for gesture in gestures:
                    frame=gesture[-1]
                    began=time.monotonic()
                    page.evaluate("""frames=>{
                        for(const f of frames.slice(0,-1))seek(f/60,{scrubbing:true});
                        seek(frames.at(-1)/60);
                    }""",gesture)
                    page.wait_for_function("""f=>!nativeState.seeking&&!nativeState.seekBusy&&
                        nativeState.metrics?.completed_generation===nativeState.generation&&
                        nativeState.metrics.completed_sequence_frame===f&&nativeState.metrics.sequence_frame===f&&
                        !nativeState.metrics.waiting""",arg=frame,timeout=15000)
                    elapsed=round((time.monotonic()-began)*1000,2)
                    row=verify(page.evaluate("nativeState.metrics"),frame,ids,references)
                    report["paused"].append({**row,"gesture":gesture,"picture_ack_ms":elapsed})
                    page.wait_for_function("nativeState.metrics?.surface_visible",timeout=5000)
                    # Allow for scanout of a submitted frame. Color identity must eventually match.
                    until=time.monotonic()+1
                    while True:
                        rgb=center_color(page,process)
                        ch=row["source"]
                        if ch==3:
                            matches=min(rgb[:2])-rgb[2]>32
                        else:
                            matches=rgb[ch]-max(rgb[(ch+1)%3],rgb[(ch+2)%3])>32
                        if matches:break
                        if time.monotonic()>=until:raise AssertionError(f"Incorrect physical source color at frame {frame}")
                        page.wait_for_timeout(16)
                    report["physical_color_checks"]+=1
                page.locator("#playBtn").click()
                deadline=time.monotonic()+12
                seen=set()
                while time.monotonic()<deadline:
                    data=page.evaluate("({m:nativeState.metrics,playing:isPlaying,end:nativeState.ack?.finished})")
                    m=data["m"]
                    if m and m["completed_generation"]==m["generation"] and not m["waiting"]:
                        f=m["sequence_frame"]
                        if f==m["completed_sequence_frame"] and f not in seen:
                            report["playing"].append(verify(m,f,ids,references))
                            seen.add(f)
                    if data["end"] and not data["playing"]:break
                    page.wait_for_timeout(16)
                else:
                    raise AssertionError("Playing sequence did not finish")
                audio=page.evaluate("({samples:nativeState.ack.samples,underruns:nativeState.ack.underruns})")
                report.update(audio=audio,window_held=visible.finish()["condition_held"])
                assert audio=={"samples":len(SHOTS)*CUT*48000//RATE,"underruns":0}
                final=page.evaluate("nativeState.metrics")
                report["peak_live_decoders"]=final["peak_decoder_count"]
                report["peak_queue_frames"]=final["peak_source_queue_frames"]
                assert report["peak_live_decoders"]<=3 and report["peak_queue_frames"]<=4
                if "standby_surface_budget_bytes" in final:
                    report["standby_peak_bytes"]=final["peak_standby_surface_bytes"]
                    report["standby_budget_bytes"]=final["standby_surface_budget_bytes"]
                    assert report["standby_peak_bytes"]<=report["standby_budget_bytes"]
                assert report["window_held"] and not errors
                assert len({r["source"] for r in report["playing"]})>=2,"Insufficient observed active cut handoffs"
                assert any(r["held_vfr"] for r in report["paused"]),"No confirmed VFR held interval"
                page.evaluate("()=>{seek(.6,{scrubbing:true});seek(.2,{scrubbing:true});return nativeStop()}")
                assert not page.evaluate("request('native/status')")["running"]
            report["cancelled_during_seek"]=True
        report["passed"]=True
    except Exception as error:
        report["failure_type"]=type(error).__name__
        raise
    finally:
        (folder/"handoff-verification.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable",type=Path)
    parser.add_argument("results",type=Path)
    main(parser.parse_args())
