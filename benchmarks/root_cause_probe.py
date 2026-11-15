"""Generated-media opt-in flight/heap diagnostics; never an acceptance FPS replacement."""
import argparse,hashlib,json,os,subprocess,time
from pathlib import Path
from contextlib import ExitStack
from windows_session import session
from native_playback import SETUP
from observer_memory import groups
from window_visibility import WindowVisibility
from observation_window import observe
from conditions import Conditions
from allocation_summary import allocation_summary

def main(a):
 a.results=a.results.resolve();a.results.mkdir(parents=True,exist_ok=True)
 assert not (a.results/'probe.json').exists(),'Preserve prior probe'
 native=a.executable.parent/'_internal/engine/native/VlogCraftNative.exe'
 os.environ['VLOGCRAFT_NATIVE_TRACE_FILE']=str(a.results/'native-events.json')
 metadata={'commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'mode':a.mode,'seconds':a.seconds,
           'timeline_seconds':600,'video_tracks':3,'audio_tracks':3,'native_binary_sha256':hashlib.sha256(native.read_bytes()).hexdigest()}
 (a.results/'manifest.json').write_text(json.dumps(metadata,indent=2),encoding='utf8')
 with session(a.executable,a.results,offline=True) as (first,proc,project,errors),ExitStack() as owned:
  page=first;browser_type=page.context.browser.browser_type;endpoint=page._vlogcraft_cdp_endpoint
  assets=page.evaluate("paths=>request('import','POST',{paths,autoProxy:false})",[str((a.media/f'h264-4k60-{n}.mp4').resolve()) for n in range(3)])
  assert not assets['errors'];page.evaluate(SETUP,{'assets':assets['assets'],'seconds':600,'cut':.5})
  page.evaluate("()=>{const s=$('previewStage'),d=devicePixelRatio;s.style.width=356/d+'px';s.style.height=200/d+'px';s.style.maxWidth='none';s.style.flex='0 0 auto';}")
  page.select_option('#playbackEngine','native');page.wait_for_function('nativeState.prepared&&nativeState.ack?.queued>=12000',timeout=45000)
  visibility=owned.enter_context(WindowVisibility(proc,'visible'));conditions=Conditions();memory=[]
  cdp=page.context.new_cdp_session(page)
  def sample(stage):
   heap={v['name']:v['value'] for v in cdp.send('Performance.getMetrics')['metrics'] if v['name'] in ('JSHeapUsedSize','JSHeapTotalSize','Nodes','Documents','JSEventListeners')}
   memory.append({'stage':stage,'groups':groups(proc),'heap':heap})
  cdp.send('Performance.enable');sample('prepared');geometry=page.evaluate('({composition:Number($("programResolution").value),rect:nativeRect(),dpr:devicePixelRatio})')
  if a.mode=='allocation':cdp.send('HeapProfiler.startSampling',{'samplingInterval':131072,'includeObjectsCollectedByMajorGC':True,'includeObjectsCollectedByMinorGC':True})
  else:
   page.evaluate('()=>{'+Path('benchmarks/flight_recorder.js').read_text('utf8')+'}');page.evaluate('()=>{window.qaFlight=installQAFlightRecorder();}')
  page.evaluate('nativePlayPause()');started=time.perf_counter()
  if a.mode=='flight':first._vlogcraft_intentional_detach=True;first.context.browser.close()
  observe(a.seconds,time.sleep if a.mode=='flight' else lambda s:page.wait_for_timeout(s*1000),lambda:None,period=a.seconds+1)
  if a.mode=='flight':
   browser=browser_type.connect_over_cdp(endpoint,no_defaults=True);page=next(p for p in browser.contexts[0].pages if p.url.startswith('http://127.0.0.1:'))
   cdp=page.context.new_cdp_session(page);cdp.send('Performance.enable')
  elapsed=time.perf_counter()-started
  audio=page.evaluate('({samples:nativeState.ack.samples,underruns:nativeState.ack.underruns,queued:nativeState.ack.queued,playing:isPlaying})')
  last=page.evaluate('nativeState.metrics');sample('active_end')
  result={'mode':a.mode,'requested_seconds':a.seconds,'elapsed_seconds':elapsed,'timeline_seconds':600,'geometry':geometry,'audio':audio,
          'native_binary_sha256':hashlib.sha256(native.read_bytes()).hexdigest(),'commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
          'skips':last['skipped_sequence_frames'],'timings':last['timings'],'native_last_wall_seconds':last['wall_seconds']}
  if a.mode=='allocation':
   profile=cdp.send('HeapProfiler.stopSampling')['profile']
   (a.results/'allocations-local.json').write_text(json.dumps(profile),encoding='utf8')
   result['sampled_allocations']=allocation_summary(profile)
   result['allocation_scope']='Sampled JS allocation bytes including collected objects; not retained size, full external memory or leak proof. Profiler perturbs execution.'
  else:result['flight']=page.evaluate('qaFlight.stop()')
  page.evaluate('stopPlayback()');sample('stopped');page.wait_for_timeout(30000);sample('natural_idle30_no_GC')
  page.evaluate('nativeStop()');page.wait_for_timeout(1000);sample('native_released')
  result.update(memory=memory,window_condition=visibility.finish(),conditions=conditions.finish(),browser_error_count=len(errors),
    scope='Partial generated workload; no PDH polling, no forced GC. Flight uses existing ack events and existing bounded native missed-event recorder. Not protected consistency/physical scanout qualification.')
  (a.results/'probe.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
  assert audio['playing'] and audio['samples']>48000*max(1,a.seconds-10)
  assert 'native' not in memory[-1]['groups'],'Native worker survived Stop'
  assert (a.results/'native-events.json').exists(),'Native event output missing; retained probe is incomplete'
  assert result['window_condition']['condition_held'],'Window qualification failed; retain all evidence'
  assert audio['underruns']==0 and not errors,'Underruns/browser error; retained failing probe'
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('executable',type=Path);p.add_argument('media',type=Path);p.add_argument('results',type=Path)
 p.add_argument('--mode',choices=('flight','allocation'),required=True);p.add_argument('--seconds',type=int,default=60);main(p.parse_args())
