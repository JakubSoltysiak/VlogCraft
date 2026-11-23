"""Exercise bounded native three-layer rewind with actual decoded VFR timestamps."""
import argparse
from bisect import bisect_right
from fractions import Fraction
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time


def run(worker, output):
    output.mkdir(parents=True, exist_ok=False)
    media = (output / "local-vfr.mp4").resolve()
    subprocess.run(["ffmpeg","-v","error","-nostdin","-f","lavfi","-i","testsrc2=s=160x96:r=6:d=4",
                    "-vf","select=not(eq(mod(n\\,7)\\,2))","-fps_mode","vfr","-c:v","libx264",
                    "-pix_fmt","yuv420p","-threads","1","-g","6","-bf","2","-colorspace","bt709",
                    "-color_trc","bt709","-color_primaries","bt709","-video_track_timescale","60000",
                    str(media)],check=True,timeout=30)
    ref=json.loads(subprocess.check_output(["ffprobe","-v","error","-select_streams","v:0","-show_entries",
                    "stream=time_base:frame=best_effort_timestamp","-of","json",str(media)],timeout=20))
    base=Fraction(ref["streams"][0]["time_base"])
    pts=[int(f["best_effort_timestamp"]) for f in ref["frames"]]
    assert len(set(b-a for a,b in zip(pts,pts[1:])))>1 and base==Fraction(1,60000)
    starts=[6,0,6,0]
    plan=output/"rewind.plan"
    lines=["VLOGCRAFT_NATIVE 1","RATE 6 1","CANVAS 160 96","END 24","COLOR SDR"]
    for layer in range(3):
        lines.append(f"SOURCE a{layer}\t{media}")
        for shot,offset in enumerate(starts):
            left=6*shot
            start=10000*(offset+layer)
            lines.append(f"CLIP c{layer}_{shot} a{layer} {left} {left+6} {start} 1 60000 1 1 0 0 1 0 1 0 0 0 0 {start+60000}")
    plan.write_text("\n".join(lines)+"\n",encoding="utf-8")
    env=os.environ.copy()
    env.pop("VLOGCRAFT_NATIVE_TRACE_FILE",None)
    events=queue.Queue()
    observed=set()
    pairs=0
    seek_pending=False
    exact_seek=False
    closed_during_rewind=False
    close_ms=None
    observed_tail=False
    observed_adoptions=False
    checked={}
    with subprocess.Popen([str(worker.resolve()),"--plan",str(plan.resolve()),"--offscreen"],stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding="utf-8",env=env) as proc:
        def reader():
            try:
                for line in proc.stdout:
                    events.put(json.loads(line))
            finally:
                events.put(None)
        thread=threading.Thread(target=reader,daemon=True)
        thread.start()
        def send(command):
            proc.stdin.write(command+"\n");proc.stdin.flush()
        try:
            deadline=time.monotonic()+22
            playing=False
            while time.monotonic()<deadline:
                try:event=events.get(timeout=min(1.,deadline-time.monotonic()))
                except queue.Empty:continue
                if event is None:raise AssertionError("Native worker exited before qualification")
                if event["event"]=="error":raise AssertionError(event)
                counters=event.get("decoder_statistics",[])
                assert all(row["peak_queue_plus_tail"]<=4 for row in counters)
                assert event["peak_decoder_count"]<=3
                if event["waiting"] or len(event["selected"])!=3:continue
                gen=event["generation"];frame=event["sequence_frame"]
                if not playing:
                    if event["completed_generation"]==gen and event["completed_sequence_frame"]==0:
                        send("CLOCK 0 1 11");playing=True
                    continue
                if gen not in (11,12):continue
                shot,local=divmod(frame,6)
                for layer,row in enumerate(event["selected"]):
                    target=10000*(starts[shot]+layer+local)
                    assert row["clip"]==f"c{layer}_{shot}" and row["target_tick"]==target,(frame,row,target)
                    assert row["pts"]==pts[bisect_right(pts,target)-1],(frame,row,pts)
                    pairs+=1
                if gen==11:
                    observed.add(frame)
                    observed_tail|=any(row["rewind_tail_hits"]>0 for row in counters)
                    observed_adoptions|=all(row["adopted_rewinds"]>0 for row in counters)
                    if frame>=15 and not seek_pending and any(row["early_rewinds"]>row["adopted_rewinds"] for row in counters):
                        # Reverse during the second outstanding rewind. Position 7
                        # is in the preceding clip; release only its new generation.
                        send("CLOCK 1166667 0 12");seek_pending=True
                elif gen==12:
                    if not exact_seek and frame==7 and event["completed_sequence_frame"]==7 and event["completed_generation"]==12:
                        exact_seek=True;checked=counters
                        send("CLOCK 1166667 1 12")
                    elif exact_seek and frame>=15 and any(row["early_rewinds"]-row["adopted_rewinds"]>old["early_rewinds"]-old["adopted_rewinds"]
                                                            for row,old in zip(counters,checked)):
                        # One interrupted preparation already remains unadopted.
                        # Close during a newly prepared second pass through that cut.
                        closed_during_rewind=True;break
            assert {4,5,6,7}.issubset(observed) and observed_tail and observed_adoptions,(observed,observed_tail,observed_adoptions)
            assert seek_pending and exact_seek and closed_during_rewind,(seek_pending,exact_seek,closed_during_rewind)
            closing=time.monotonic();send("CLOSE")
            assert proc.wait(timeout=5)==0
            close_ms=round((time.monotonic()-closing)*1000,3)
        finally:
            if proc.poll() is None:proc.kill();proc.wait(timeout=5)
            thread.join(timeout=2)
    return dict(passed=True,source_frame_pairs=pairs,observed_sequence_frames=sorted(observed),
                exact_seek_during_pending_rewind=exact_seek,closed_during_another_pending_rewind=closed_during_rewind,
                close_ms=close_ms,decoder_counters=checked)


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("worker",type=Path);parser.add_argument("output",type=Path)
    args=parser.parse_args()
    result=run(args.worker,args.output)
    (args.output/"qualification.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps(result))
