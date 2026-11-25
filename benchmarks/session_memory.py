"""Local generated-media ownership diagnostics; never an acceptance FPS observer."""
import argparse,json,statistics,time,traceback,psutil
from pathlib import Path
from contextlib import ExitStack
from windows_session import session
from native_playback import SETUP
from runtime_trace import RuntimeTrace
from conditions import Conditions
from window_visibility import WindowVisibility

def main(a):
 a.results.mkdir(parents=True,exist_ok=True);measured=a.measure_seconds or a.seconds
 with session(a.executable,a.results,offline=True) as (page,proc,project,errors),ExitStack() as owned_windows:
  data=page.evaluate("paths=>request('import','POST',{paths,autoProxy:false})",[str((a.media/f'h264-4k60-{n}.mp4').resolve()) for n in range(3)])
  assert not data['errors'];page.evaluate(SETUP,{'assets':data['assets'],'seconds':a.seconds if a.mode=='continuous' else 125,'cut':.5})

  if a.full_status:page.evaluate("()=>{const original=request;request=(path,method,body)=>{if(path==='native/clock'&&body)delete body.sinceStatus;return original(path,method,body);};}")
  page.select_option('#playbackEngine','native');page.wait_for_function('nativeState.prepared&&nativeState.metrics?.completed_frames>0&&!nativeState.metrics.waiting',timeout=45000)
  visibility=owned_windows.enter_context(WindowVisibility(proc,a.window_mode))
  cdp=page.context.new_cdp_session(page);cdp.send('Performance.enable');cdp.send('Network.enable')
  clocks=set();wire={'requests':0,'encoded_bytes':0};rows=[];started=time.perf_counter()
  def request(event):
   if event['request']['url'].split('?')[0].endswith('/api/native/clock'):clocks.add(event['requestId']);wire['requests']+=1
  def finished(event):
   if event['requestId'] in clocks:wire['encoded_bytes']+=event['encodedDataLength'];clocks.discard(event['requestId'])
  cdp.on('Network.requestWillBeSent',request);cdp.on('Network.loadingFinished',finished)
  trace=RuntimeTrace(proc.pid);conditions=Conditions();failure=None;edit_batches=[]
  def sample(stage):
   metrics={v['name']:v['value'] for v in cdp.send('Performance.getMetrics')['metrics'] if v['name'] in ('JSHeapUsedSize','JSHeapTotalSize','Nodes','Documents','JSEventListeners')}
   state=page.evaluate('({frame:nativeState.metrics?.sequence_frame,playing:isPlaying,underruns:nativeState.ack?.underruns,samples:nativeState.ack?.samples,undo:undoStack.length,redo:redoStack.length,resolution:$("programResolution").value})')
   roles={}
   for child in psutil.Process(proc.pid).children(recursive=True):
    try:
     if child.name().lower()!='msedgewebview2.exe':continue
     role=next((v.split('=',1)[1] for v in child.cmdline() if v.startswith('--type=')),'browser')
     if role not in ('browser','renderer','gpu-process','utility'):role='other'
     memory=child.memory_info();entry=roles.setdefault(role,{'rss_MiB':0,'private_commit_MiB':0,'processes':0})
     entry['rss_MiB']+=memory.rss/2**20;entry['private_commit_MiB']+=getattr(memory,'private',memory.vms)/2**20;entry['processes']+=1
    except psutil.Error:pass
   rows.append({'seconds':time.perf_counter()-started,'stage':stage,'heap':metrics,'state':state,'clock_wire':dict(wire),'WebView_roles':roles})
   (a.results/'checkpoint.json').write_text(json.dumps({'rows':rows,'working_set':trace.rows[-1:]},indent=2),encoding='utf8')
  try:
   sample('prepared');page.evaluate('window.memoryEditingUnderruns=0;nativePlayPause()');iteration=0;next_sample=30
   while time.perf_counter()-started<measured:
    page.wait_for_timeout(250)
    elapsed=time.perf_counter()-started
    if a.mode=='editing' and elapsed>=(iteration+1)*10:
     iteration+=1;edit_started=time.perf_counter()
     page.evaluate("""n=>{window.memoryEditingUnderruns+=nativeState.ack?.underruns||0;stopPlayback();seek((n*7)%110);const c=state.tracks.find(t=>t.type==='video').clips[n%20];selectedId=c.id;renderInspector();$('timelineScroller').scrollLeft=(n%8)*180;snapshot();c.opacity=c.opacity===.95?1:.95;redraw();save();return flushSave();}""",iteration)
     if iteration%6==0:page.select_option('#programResolution','1280' if iteration%12==6 else '960')
     page.evaluate('nativePlayPause()');edit_batches.append({'iteration':iteration,'seconds':time.perf_counter()-started,'wall_ms':1000*(time.perf_counter()-edit_started)})
    if elapsed>=next_sample:sample('active');next_sample+=30
   sample('end');observed_underruns=page.evaluate('(window.memoryEditingUnderruns||0)+(nativeState.ack?.underruns||0)');page.evaluate('stopPlayback()');page.wait_for_timeout(1000);sample('stopped')
   if a.natural_idle_seconds is None:
    cdp.send('HeapProfiler.collectGarbage');page.wait_for_timeout(1000);sample('diagnostic_GC')
   else:
    page.wait_for_timeout(a.natural_idle_seconds*1000);sample('natural_idle')
   page.evaluate('nativeStop()');page.wait_for_timeout(1000);sample('native_released')
  except Exception as exc:failure=exc
  result={'diagnostic_only':True,'full_status_diagnostic':a.full_status,'mode':a.mode,'seconds':measured,'timeline_seconds':a.seconds if a.mode=='continuous' else 125,'rows':rows,'clock_wire':wire,'runtime_trace':trace.finish(),'conditions':conditions.finish(),
          'failure_type':type(failure).__name__ if failure else None,'browser_errors':errors,'audio_underruns_observed':locals().get('observed_underruns'),'editing_batches':edit_batches,
          'window_condition':visibility.finish(),'forced_gc':a.natural_idle_seconds is None,
          'scope':'Counters and heap observer enabled. Use the separate FPS benchmark for acceptance. RSS may double-count UMA mappings. Private commit is separate.'}
  (a.results/'memory.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
  if failure:raise failure
  assert not errors
  assert observed_underruns==0 and all((r['state'].get('underruns') or 0)==0 for r in rows),'Sampled audio underrun occurred'
  if a.window_mode!='uncontrolled':assert result['window_condition']['condition_held'],'Requested window condition changed; retain as unqualified'
  print(json.dumps({'complete':True,'mode':a.mode,'clock_wire':wire}),flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('executable',type=Path);p.add_argument('media',type=Path);p.add_argument('results',type=Path)
 p.add_argument('--window-mode',choices=('uncontrolled','visible','preview-covered','editor-covered'),default='visible')
 p.add_argument('--seconds',type=int,default=600);p.add_argument('--measure-seconds',type=int);p.add_argument('--full-status',action='store_true');p.add_argument('--natural-idle-seconds',type=int);p.add_argument('--mode',choices=('continuous','editing'),default='continuous');main(p.parse_args())
