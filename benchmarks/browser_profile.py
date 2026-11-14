"""Isolated WebView CPU/layout and native-clock IPC diagnostic; not headline FPS."""
import argparse,json,sys,hashlib
from collections import Counter
from pathlib import Path
from windows_session import session
from native_playback import SETUP

INSTRUMENT="""()=>{
 const original=request,stats={count:0,sum:0,max:0,bins:Array(1001).fill(0),slow:[],anchor_jumps:[]};
 window.clockIPC=stats;
 window.request=async function(path,method,body){
  const begin=performance.now();
  if(path==='native/clock'){
   const ack=nativeState.ack;
   if(stats.previous){const step=(body.microseconds-stats.previous.microseconds)/1000-(begin-stats.previous.at);
    if(Math.abs(step)>5){const stamp=mixer?.getOutputTimestamp?.(),now=stamp?.performanceTime?stamp.contextTime+(begin-stamp.performanceTime)/1000:mixer.currentTime;
     stats.anchor_jumps.push({at:begin,step_ms:step,queued:ack?.queued,samples:ack?.samples,ack_lag_ms:(now-(ack?.contextEnd||now))*1000});if(stats.anchor_jumps.length>256)stats.anchor_jumps.shift();}}
   stats.previous={at:begin,microseconds:body.microseconds};
  }
  try{return await original(path,method,body);}
  finally{if(path==='native/clock'){
   const ms=performance.now()-begin;stats.count++;stats.sum+=ms;stats.max=Math.max(stats.max,ms);stats.bins[Math.min(1000,Math.floor(ms))]++;
   if(ms>16.667){stats.slow.push({at:begin,duration_ms:ms,microseconds:body.microseconds});if(stats.slow.length>256)stats.slow.shift();}
  }}
 };
}"""
def main(a):
 a.results.mkdir(parents=True,exist_ok=True)
 with session(a.executable,a.results,offline=True) as (page,proc,project,errors):
  result=page.evaluate("paths=>request('import','POST',{paths,autoProxy:false})",[str((a.media/f'h264-4k60-{n}.mp4').resolve()) for n in range(3)])
  assert not result['errors'];page.evaluate(SETUP,{'assets':result['assets'],'seconds':125,'cut':.5})
  source_patch=None
  if a.ui_source:
   from ui_patch import inject
   source_patch=inject(page)
  if a.meter_static:page.evaluate('updateMeter=()=>{}')
  page.wait_for_function("Array.from(document.querySelector('#playbackEngine').options).some(o=>o.value==='native'&&!o.disabled)")
  page.select_option('#playbackEngine','native')
  page.wait_for_function('nativeState.metrics?.completed_frames>0&&!nativeState.metrics.waiting')
  page.evaluate(INSTRUMENT)
  cdp=page.context.new_cdp_session(page);cdp.send('Performance.enable');cdp.send('Profiler.enable')
  cdp.send('Profiler.setSamplingInterval',{'interval':1000})
  before={x['name']:x['value'] for x in cdp.send('Performance.getMetrics')['metrics']}
  cdp.send('Profiler.start')
  page.evaluate('nativePlayPause()');page.wait_for_timeout(a.seconds*1000)
  after={x['name']:x['value'] for x in cdp.send('Performance.getMetrics')['metrics']}
  profile=cdp.send('Profiler.stop')['profile'];page.evaluate('stopPlayback()')
  ipc=page.evaluate('clockIPC');metrics=page.evaluate('nativeState.metrics')
  (a.results/'cpu-profile.json').write_text(json.dumps(profile),encoding='utf8')
  ids={n['id']:n for n in profile['nodes']};times=Counter()
  for node,dt in zip(profile.get('samples',[]),profile.get('timeDeltas',[])):
   name=ids[node]['callFrame'].get('functionName') or '(anonymous)'
   times[name]+=dt/1000
  total=sum(times.values())
  summary={'diagnostic_only':True,'ui_source_patch_sha256':source_patch,'meter_static_diagnostic':a.meter_static,'seconds':a.seconds,'profile_overhead':'Sampling and IPC observer enabled; not a qualification throughput trial',
    'cpu_top_self':[{'function':name,'milliseconds':ms,'sample_percent':100*ms/total} for name,ms in times.most_common(25)],
    'performance_deltas':{k:after.get(k,0)-before.get(k,0) for k in ('TaskDuration','ScriptDuration','LayoutDuration','RecalcStyleDuration','LayoutCount','RecalcStyleCount')},
    'clock_IPC':ipc,'native':metrics,'browser_errors':errors}
  (a.results/'browser-profile.json').write_text(json.dumps(summary,indent=2),encoding='utf8')
  print(json.dumps({k:v for k,v in summary.items() if k not in ('native','clock_IPC')}))
  assert not errors
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('executable',type=Path);p.add_argument('media',type=Path);p.add_argument('results',type=Path);p.add_argument('--seconds',type=int,default=30);p.add_argument('--ui-source',action='store_true');p.add_argument('--meter-static',action='store_true');main(p.parse_args())
