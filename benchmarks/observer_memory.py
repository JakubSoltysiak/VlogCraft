"""Separate application commit from DevTools retention on generated media only."""
import argparse,json,time
from pathlib import Path
from contextlib import ExitStack
import psutil
from windows_session import session
from native_playback import SETUP
from runtime_trace import RuntimeTrace
from conditions import Conditions
from window_visibility import WindowVisibility

def groups(proc):
 result={}
 for p in [psutil.Process(proc.pid),*psutil.Process(proc.pid).children(recursive=True)]:
  try:
   name=p.name().lower();kind='native' if name=='vlogcraftnative.exe' else 'webview' if name=='msedgewebview2.exe' else 'ffmpeg' if name=='ffmpeg.exe' else 'host'
   m=p.memory_info();r=result.setdefault(kind,{'rss_MiB':0,'private_commit_MiB':0})
   r['rss_MiB']+=m.rss/2**20;r['private_commit_MiB']+=getattr(m,'private',m.vms)/2**20
  except psutil.Error:pass
 return result

def main(a):
 a.results=a.results.resolve();a.results.mkdir(parents=True,exist_ok=True);rows=[]
 with session(a.executable,a.results,offline=True) as (first,proc,project,errors),ExitStack() as owned_windows:
  page=first;endpoint=page._vlogcraft_cdp_endpoint;browser_type=page.context.browser.browser_type
  imported=page.evaluate("paths=>request('import','POST',{paths,autoProxy:false})",[str((a.media/f'h264-4k60-{n}.mp4').resolve()) for n in range(3)])
  assert not imported['errors'];page.evaluate(SETUP,{'assets':imported['assets'],'seconds':600,'cut':.5})
  page.select_option('#playbackEngine','native');page.wait_for_function('nativeState.prepared&&nativeState.ack?.queued>=12000',timeout=45000)
  visibility=owned_windows.enter_context(WindowVisibility(proc,'visible'))
  cdp=page.context.new_cdp_session(page);cdp.send('Performance.enable')
  if not a.detach:cdp.send('Network.enable')
  epoch=page.evaluate("request('desktop/recovery')")['epoch'];started=time.perf_counter();trace=RuntimeTrace(proc.pid);conditions=Conditions()
  page.evaluate("()=>{window.observerErrorCount=0;addEventListener('error',()=>observerErrorCount++);addEventListener('unhandledrejection',()=>observerErrorCount++);}")
  def sample(stage,heap=True):
   row={'seconds':time.perf_counter()-started,'stage':stage,'groups':groups(proc)}
   if heap:row['heap']={r['name']:r['value'] for r in cdp.send('Performance.getMetrics')['metrics'] if r['name'] in ('JSHeapUsedSize','JSHeapTotalSize','Nodes','Documents','JSEventListeners')}
   rows.append(row);(a.results/'checkpoint.json').write_text(json.dumps({'stage':stage,'seconds':row['seconds'],'groups':row['groups']}),encoding='utf8')
  def disconnect():
   first._vlogcraft_intentional_detach=True;page.context.browser.close()
  def reconnect():
   nonlocal page,cdp
   browser=browser_type.connect_over_cdp(endpoint,no_defaults=True);page=next(p for p in browser.contexts[0].pages if p.url.startswith('http://127.0.0.1:'))
   page.on('pageerror',lambda e:errors.append(str(e)))
   cdp=page.context.new_cdp_session(page);cdp.send('Performance.enable')
  sample('prepared');base=page.evaluate('nativeState.metrics');page.evaluate('nativePlayPause()');play_started=time.perf_counter()
  if a.detach:disconnect()
  for n in range(a.seconds):
   if a.detach:time.sleep(1)
   else:page.wait_for_timeout(1000)
   if n%15==14:sample('active_detached' if a.detach else 'active_network_observer',not a.detach)
  if a.detach:reconnect()
  audio=page.evaluate('({underruns:nativeState.ack.underruns,samples:nativeState.ack.samples,playing:isPlaying})')
  elapsed=time.perf_counter()-play_started;last=page.evaluate('nativeState.metrics')
  transport={'measured_seconds':elapsed,'distinct_sequence_fps':(last['distinct_sequence_submissions']-base['distinct_sequence_submissions'])/elapsed,
             'skips':last['skipped_sequence_frames'],'physical_surface':[last['surface_width'],last['surface_height']]}
  assert audio['playing'] and audio['samples']>48000*max(1,a.seconds-10)
  page.evaluate('stopPlayback()');sample('stopped');cdp.send('HeapProfiler.collectGarbage');page.wait_for_timeout(1000);sample('after_GC')
  if not a.detach:cdp.send('Network.disable')
  cdp.detach();disconnect();time.sleep(3);sample('all_observers_detached',False)
  reconnect();cdp.send('HeapProfiler.collectGarbage');page.wait_for_timeout(1000);sample('fresh_observer_GC')
  assert page.evaluate("request('desktop/recovery')")['epoch']==epoch,'Observer disconnect caused application recovery'
  page.evaluate('nativeStop()');page.wait_for_timeout(1000);sample('native_released')
  assert 'native' not in rows[-1]['groups'],'Native child survived Stop'
  error_count=page.evaluate('observerErrorCount')
  result={'seconds':a.seconds,'timeline_seconds':600,'active_observer':'detached' if a.detach else 'Playwright plus extra Network observer',
          'rows':rows,'audio':audio,'transport':transport,'window_condition':visibility.finish(),'browser_errors':errors,'error_event_count':error_count,'runtime_trace':trace.finish(),'conditions':conditions.finish(),
          'scope':'Diagnostic only. GC after stop; full detach measures observer retention. Summed RSS may duplicate UMA pages. No physical sync/FPS qualification.'}
  (a.results/'observer-memory.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
  assert audio['underruns']==0 and not errors and error_count==0
  assert result['window_condition']['condition_held'],'Observer arm lost its visible condition'
  print(json.dumps({'complete':True,'active_observer':result['active_observer'],'audio':audio}),flush=True)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('executable',type=Path);p.add_argument('media',type=Path);p.add_argument('results',type=Path)
 p.add_argument('--seconds',type=int,default=150);p.add_argument('--detach',action='store_true');main(p.parse_args())
