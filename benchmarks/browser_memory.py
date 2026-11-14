"""Diagnostic observer control on a 600-second timeline; not a throughput trial."""
import argparse,json,time
from pathlib import Path
from windows_session import session
from native_playback import SETUP
from runtime_trace import RuntimeTrace

def main(a):
 with session(a.executable,a.results,offline=True) as (page,proc,project,errors):
  data=page.evaluate("paths=>request('import','POST',{paths,autoProxy:false})",[str((a.media/f'h264-4k60-{n}.mp4').resolve()) for n in range(3)])
  assert not data['errors'];page.evaluate(SETUP,{'assets':data['assets'],'seconds':600,'cut':.5})
  page.select_option('#playbackEngine','native');page.wait_for_function('nativeState.prepared&&nativeState.metrics?.completed_frames>0&&!nativeState.metrics.waiting')
  cdp=page.context.new_cdp_session(page);cdp.send('Performance.enable')
  trace=RuntimeTrace(proc.pid);rows=[];began=time.perf_counter()
  def sample(label):
   rows.append({'stage':label,'seconds':time.perf_counter()-began,
                'metrics':{x['name']:x['value'] for x in cdp.send('Performance.getMetrics')['metrics'] if x['name'] in ('JSHeapUsedSize','JSHeapTotalSize','Nodes','Documents','LayoutCount')},
                'frame':page.evaluate('nativeState.metrics.sequence_frame')})
  sample('before');page.evaluate('nativePlayPause()')
  if a.detach_observer:
   browser=page.context.browser;browser_type=browser.browser_type;endpoint=page._vlogcraft_cdp_endpoint
   page._vlogcraft_intentional_detach=True;browser.close()
   for n in range(a.seconds//30):time.sleep(30)
   assert proc.poll() is None,'Host exited while observer was detached'
   browser=browser_type.connect_over_cdp(endpoint);page=next(p for p in browser.contexts[0].pages if p.url.startswith('http://127.0.0.1:'))
   cdp=page.context.new_cdp_session(page);cdp.send('Performance.enable');sample('reconnected')
   assert page.evaluate('isPlaying&&nativeState.metrics.sequence_frame>60'), 'Playback did not continue while detached'
  else:
   for n in range(a.seconds//30):page.wait_for_timeout(30000);sample('playing')
  page.evaluate('stopPlayback()');sample('stopped');cdp.send('HeapProfiler.collectGarbage');page.wait_for_timeout(1000);sample('after_forced_GC')
  result={'diagnostic_only':True,'timeline_seconds':600,'observed_seconds':a.seconds,
          'observer_detached':a.detach_observer,'runtime_trace':trace.finish(),'heap_samples':rows,'browser_errors':errors,
          'interpretation':'Forced GC occurs after stopping; no acceptance FPS is measured. CDP observer detach is tooling, not application networking; private commit is measured externally in both arms.'}
  (a.results/'memory.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8');assert not errors
  print(json.dumps({'diagnostic_complete':True,'observer_detached':a.detach_observer}),flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('executable',type=Path);p.add_argument('media',type=Path);p.add_argument('results',type=Path)
 p.add_argument('--seconds',type=int,default=150);p.add_argument('--detach-observer',action='store_true');main(p.parse_args())
