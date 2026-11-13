"""Repeated fresh-program and warm source-PTS seek latency, loaded/completed endpoint."""
import argparse,json,time,statistics,sys
from pathlib import Path
from windows_session import session
from native_playback import SETUP
def main(a):
 values=[]
 with session(a.executable,a.results,offline=True) as (page,proc,project,errors):
  result=page.evaluate("paths=>request('import','POST',{paths,autoProxy:false})",[str((a.media/f'h264-4k60-{i}.mp4').resolve()) for i in range(3)])
  assert not result['errors'];page.evaluate(SETUP,{'assets':result['assets'],'seconds':6,'cut':2})
  page.wait_for_function("Array.from(document.querySelector('#playbackEngine').options).some(o=>o.value==='native'&&!o.disabled)")
  began=time.perf_counter();page.select_option('#playbackEngine','native');page.wait_for_function('nativeState.metrics?.completed_frames>0',timeout=30000);first=time.perf_counter()-began
  for i,target in enumerate([2.2,.5,4.2,2.2,.5,4.2,2.2,.5,4.2,2.2,.5,4.2]):
   previous=page.evaluate('nativeState.generation');began=time.perf_counter();page.evaluate('t=>seek(t)',target)
   page.wait_for_function('previous=>nativeState.generation>previous&&!nativeState.seeking&&nativeState.metrics.completed_generation===nativeState.generation&&nativeState.metrics.completed_sequence_frame===frameIndex(playhead)&&!nativeState.metrics.waiting',arg=previous,timeout=15000)
   values.append({'target_seconds':target,'milliseconds':(time.perf_counter()-began)*1000,'first_visit':i<3})
  v=sorted(x['milliseconds'] for x in values)
  report={'first_ready_ms':first*1000,'seek_samples':values,'seek_p50_ms':statistics.median(v),'seek_p95_ms':v[int(.95*(len(v)-1))],
          'endpoint':'completed GPU frame in requested generation; not physical scanout','browser_errors':errors}
  (a.results/'seeks.json').write_text(json.dumps(report,indent=2));print(json.dumps(report));assert not errors
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('executable',type=Path);p.add_argument('media',type=Path);p.add_argument('results',type=Path);main(p.parse_args())
