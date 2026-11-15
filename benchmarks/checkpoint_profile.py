"""Matched editing batches at a full undo history; generated media only."""
import argparse,json,time
from pathlib import Path
from windows_session import session
from native_playback import SETUP

def main(a):
 a.results=a.results.resolve();a.results.mkdir(parents=True,exist_ok=True);rows=[]
 for arm,exe in [('baseline',a.baseline),('candidate',a.candidate)]:
  with session(exe,a.results/arm,offline=True) as (page,proc,project,errors):
   imported=page.evaluate("paths=>request('import','POST',{paths,autoProxy:false})",[str((a.media/f'h264-4k60-{n}.mp4').resolve()) for n in range(3)])
   assert not imported['errors'];page.evaluate(SETUP,{'assets':imported['assets'],'seconds':125,'cut':.5})
   prepared=time.perf_counter()
   page.evaluate("async()=>{const c=state.tracks.find(t=>t.type==='video').clips[0];for(let n=0;n<80;n++){snapshot();c.opacity=n%2?.95:1;}redraw();save();await flushSave();if(typeof recoverySettled==='function')await recoverySettled();}")
   fill_ms=1000*(time.perf_counter()-prepared)
   page.select_option('#playbackEngine','native');page.wait_for_function('nativeState.prepared&&nativeState.ack?.queued>=12000',timeout=45000)
   for n in range(a.repeat):
    started=time.perf_counter()
    script=page.evaluate("""async n=>{const t=performance.now();stopPlayback();seek((n*7)%110);const c=state.tracks.find(t=>t.type==='video').clips[n%20];snapshot();c.opacity=c.opacity===.95?1:.95;redraw();save();await flushSave();return performance.now()-t;}""",n)
    saved=time.perf_counter();page.evaluate('nativePlayPause()');resumed=time.perf_counter();page.wait_for_timeout(1000);page.evaluate('stopPlayback()')
    page.evaluate("async()=>{if(typeof recoverySettled==='function')await recoverySettled();}")
    health=page.evaluate("({undo:undoStack.length,ack:typeof recoveryAckSequence==='undefined'?null:recoveryAckSequence,sequence:typeof recoverySequence==='undefined'?null:recoverySequence})")
    rows.append({'arm':arm,'iteration':n,'fill_history_ms':fill_ms,'edit_save_JS_ms':script,'edit_save_wall_ms':1000*(saved-started),'resume_prebuffer_wall_ms':1000*(resumed-saved),'batch_wall_ms':1000*(resumed-started),'health':health})
    (a.results/'checkpoint-profile.json').write_text(json.dumps(rows,indent=2)+'\n',encoding='utf8')
    assert health['undo']==80 and not errors
 print(json.dumps(rows),flush=True)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('baseline',type=Path);p.add_argument('candidate',type=Path);p.add_argument('media',type=Path);p.add_argument('results',type=Path);p.add_argument('--repeat',type=int,default=3);main(p.parse_args())
