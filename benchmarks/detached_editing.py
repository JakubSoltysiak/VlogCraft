"""Bounded editing fixture with no DevTools connection during active measurement.

Retains the earlier attached 30-minute failure as a distinct cohort. The same
generated 1,500-clip workload edits every ten seconds; this fixture runs those
commands inside the view instead of transporting each command through CDP.
"""
import argparse,json,time
from pathlib import Path
import psutil
from windows_session import session
from native_playback import SETUP
from observer_memory import groups
from runtime_trace import RuntimeTrace
from conditions import Conditions
from window_visibility import WindowVisibility

EDIT = """seconds=>{
 window.qaEditing={batches:[],underruns:0,done:false,error:null};
 window.qaErrorCount=0;addEventListener('error',()=>qaErrorCount++);addEventListener('unhandledrejection',()=>qaErrorCount++);
 window.qaEditingTask=(async()=>{
  try{
   const started=performance.now();await nativePlayPause();
   for(let n=1;n<=Math.floor(seconds/10);n++){
    await new Promise(resolve=>setTimeout(resolve,Math.max(0,started+n*10000-performance.now())));
    const began=performance.now();qaEditing.underruns+=nativeState.ack?.underruns||0;
    stopPlayback();seek((n*7)%110);
    const c=state.tracks.find(t=>t.type==='video').clips[n%20];selectedId=c.id;renderInspector();
    $('timelineScroller').scrollLeft=(n%8)*180;snapshot();c.opacity=c.opacity===.95?1:.95;
    redraw();save();await flushSave();
    if(n%6===0){$('programResolution').value=n%12===6?'1280':'960';$('programResolution').dispatchEvent(new Event('change',{bubbles:true}));}
    await nativePlayPause();qaEditing.batches.push({iteration:n,seconds:(performance.now()-started)/1000,wall_ms:performance.now()-began});
   }
   qaEditing.underruns+=nativeState.ack?.underruns||0;stopPlayback();await flushSave();await recoverySettled();
   qaEditing.undo=undoStack.length;qaEditing.redo=redoStack.length;
  }catch(error){qaEditing.error=error.name;}
  finally{qaEditing.done=true;}
 })();
}"""

def main(a):
 a.results=a.results.resolve();a.results.mkdir(parents=True,exist_ok=True)
 with session(a.executable,a.results,offline=True) as (first,proc,project,errors):
  data=first.evaluate("paths=>request('import','POST',{paths,autoProxy:false})",[str((a.media/f'h264-4k60-{n}.mp4').resolve()) for n in range(3)])
  assert not data['errors'];first.evaluate(SETUP,{'assets':data['assets'],'seconds':125,'cut':.5})
  first.select_option('#playbackEngine','native');first.wait_for_function('nativeState.prepared&&nativeState.ack?.queued>=12000',timeout=45000)
  endpoint=first._vlogcraft_cdp_endpoint;browser_type=first.context.browser.browser_type
  epoch=first.evaluate("request('desktop/recovery')")['epoch']
  with WindowVisibility(proc,'visible') as visibility:
   trace=RuntimeTrace(proc.pid);conditions=Conditions();started=time.perf_counter();rows=[];failure=None;editing={}
   try:
    first.evaluate(EDIT,a.seconds);first._vlogcraft_intentional_detach=True;first.context.browser.close()
    deadline=time.perf_counter()+a.seconds+8;next_sample=15
    while time.perf_counter()<deadline:
     if proc.poll() is not None:raise RuntimeError('Owned editor exited during detached editing')
     time.sleep(min(1,max(0,deadline-time.perf_counter())))
     if time.perf_counter()-started>=next_sample:
      row={'seconds':time.perf_counter()-started,'stage':'active_detached','groups':groups(proc)};rows.append(row)
      (a.results/'checkpoint.json').write_text(json.dumps(row),encoding='utf8')
      next_sample+=15
    browser=browser_type.connect_over_cdp(endpoint,no_defaults=True)
    page=next(p for p in browser.contexts[0].pages if p.url.startswith('http://127.0.0.1:'))
    page.on('pageerror',lambda error:errors.append(str(error)))
    page.wait_for_function('qaEditing?.done',timeout=30000);editing=page.evaluate('qaEditing')
    cdp=page.context.new_cdp_session(page);cdp.send('Performance.enable')
    def sample(stage):
     rows.append({'seconds':time.perf_counter()-started,'stage':stage,'groups':groups(proc),
                  'heap':{v['name']:v['value'] for v in cdp.send('Performance.getMetrics')['metrics'] if v['name'] in ('JSHeapUsedSize','JSHeapTotalSize','Nodes','Documents','JSEventListeners')}})
    sample('reconnected_after_stop');page.wait_for_timeout(30000);sample('idle30_no_GC')
    cdp.send('HeapProfiler.collectGarbage');page.wait_for_timeout(1000);sample('diagnostic_GC_after_stop')
    page.evaluate('nativeStop()');page.wait_for_timeout(1000);sample('native_released')
    assert 'native' not in rows[-1]['groups'],'Native worker survived explicit Stop'
    assert page.evaluate("request('desktop/recovery')")['epoch']==epoch,'Detach unexpectedly triggered recovery'
    assert page.evaluate('qaErrorCount')==0 and not errors
    assert not editing['error'] and editing['underruns']==0
    assert len(editing['batches'])==a.seconds//10 and editing['undo']==min(80,a.seconds//10)
   except BaseException as error:failure=error
   result={'mode':'editing-detached','seconds':a.seconds,'timeline_seconds':125,'active_observer':'detached',
           'failure_type':type(failure).__name__ if failure else None,'browser_errors':errors,
           'rows':rows,'editing_batches':editing.get('batches',[]),'audio_underruns_observed':editing.get('underruns'),
           'editing_active_elapsed_seconds':(editing.get('batches') or [{}])[-1].get('seconds'),
           'undo_entries':editing.get('undo'),'clock_wire':{'active_observer':'none; not measured'},
           'runtime_trace':trace.finish(),'conditions':conditions.finish(),'window_condition':visibility.finish(),
           'scope':'Autonomous bounded fixture; no CDP/Network/heap observer during active editing. GC only after stopping and30s idle. A distinct observer control, not a replacement for the retained failed attached run.'}
   (a.results/'memory.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
   if failure:raise failure
   assert result['window_condition']['condition_held'],'Detached editing visibility condition changed; retained as unqualified'
 print(json.dumps({'complete':True,'batches':len(editing['batches']),'underruns':editing['underruns'],'undo':editing['undo']}),flush=True)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('executable',type=Path);p.add_argument('media',type=Path);p.add_argument('results',type=Path);p.add_argument('--seconds',type=int,default=1800);main(p.parse_args())
