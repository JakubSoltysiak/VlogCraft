"""Program presentation/endurance over 1500 clips and 32 independent source files."""
import argparse,json,sys,time
from pathlib import Path
from corpus import distinct,SETUP
from windows_session import session
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tests'))
from performance import Resources
from resource_history import History
MEASURE="""async options=>{
 const start=performance.now(),startPlayhead=playhead,seen=new Map(),subscriptions=new WeakMap(),gaps=[];
 let active=true,callbacks=0,total=0,dropped=0,bufferMs=0,last=start,peak=-60,ended=false;
 function count(v){const prev=seen.get(v),now=v.getVideoPlaybackQuality();total+=Math.max(0,now.totalVideoFrames-prev.totalVideoFrames);dropped+=Math.max(0,now.droppedVideoFrames-prev.droppedVideoFrames);seen.set(v,now);}
 function subscribe(v){
  if(seen.has(v))return;seen.set(v,v.getVideoPlaybackQuality());const token={};subscriptions.set(v,token);
  let previous=null;
  const frame=(now,meta)=>{
   if(!active||!v.isConnected||subscriptions.get(v)!==token)return;
   callbacks++;if(previous!==null)gaps.push(now-previous);previous=now;v.requestVideoFrameCallback(frame);
  };v.requestVideoFrameCallback(frame);
 }
 let done;
 const finished=new Promise(resolve=>done=resolve);
 const tick=()=>{
  if(!active)return;
  const now=performance.now();
  peak=Math.max(peak,Number($('masterMeter').value));
  if(renderedEnabled()&&(renderedLoading||!renderedCurrent||renderedCurrent.media.readyState<3))bufferMs+=now-last;
  last=now;
  for(const [v] of seen)if(!v.isConnected){count(v);seen.delete(v);}
  const players=renderedEnabled()&&renderedCurrent?[renderedCurrent.media]:Array.from(activePlayers.values()).map(p=>p.media);
  for(const v of players)if(v?.tagName==='VIDEO'){subscribe(v);count(v);}
  if(options.untilEnd&&!isPlaying&&playhead>=duration()-.001){ended=true;done();}
  else requestAnimationFrame(tick);
 };requestAnimationFrame(tick);
 const progress=setInterval(()=>console.log('VLOGCRAFT_BENCH_PROGRESS '+JSON.stringify({elapsed_seconds:(performance.now()-start)/1000,playhead,buffering_seconds:bufferMs/1000,callbacks})),30000);
 const timeout=setTimeout(done,options.seconds*1000);await finished;clearTimeout(timeout);clearInterval(progress);active=false;
 for(const [v] of seen)count(v);
 const elapsed=(performance.now()-start)/1000;gaps.sort((a,b)=>a-b);
 return {measured_seconds:elapsed,video_frame_callbacks:callbacks,presented_callback_fps:callbacks/elapsed,
         browser_total_video_frames:total,browser_dropped_video_frames:dropped,buffering_seconds:bufferMs/1000,
         playhead_advanced_seconds:playhead-startPlayhead,first_measured_playhead:startPlayhead,
         reached_sequence_end:ended,video_callback_gap_p95_ms:gaps.length?gaps[Math.floor(gaps.length*.95)]:null,
         peak_meter_db:peak,cache_requests:window.labCache};
}"""
def main(a):
 paths=distinct(a.media)
 with session(a.executable,a.results) as (page,process,project,errors):
  imported=page.evaluate("paths=>request('import','POST',{paths,autoProxy:false})",[str(p) for p in paths])
  assert not imported['errors'],imported
  page.evaluate(SETUP,imported['assets']);page.evaluate('()=>{save();return flushSave()}')
  page.wait_for_function("(async()=>{const j=await request('jobs');return j.readyAudio.length===32})()")
  page.wait_for_timeout(1000)
  page.evaluate("""()=>{window.labCache={hits:0,misses:0};const original=request;
   request=async(...args)=>{const data=await original(...args);if(args[0]==='preview')labCache[data.cacheHit?'hits':'misses']++;return data;};}""")
  page.on('console',lambda msg:print(msg.text,flush=True) if msg.text.startswith('VLOGCRAFT_BENCH_PROGRESS') else None)
  prepare=time.perf_counter()
  page.select_option('#playbackEngine',a.engine)
  if a.engine=='rendered':page.wait_for_function("renderedCurrent?.media.readyState>=2&&!renderedLoading",timeout=180000)
  first_ready=time.perf_counter()-prepare
  resources=Resources(process.pid,gpu=True);history=History(process.pid)
  page.locator('#playBtn').click();page.wait_for_function('isPlaying&&mixer?.state==="running"')
  page.wait_for_timeout(350)
  try:data=page.evaluate(MEASURE,{'seconds':a.seconds,'untilEnd':a.until_end})
  finally:memory_history=history.finish()
  page.evaluate('stopPlayback()')
  data['resources']=resources.finish();data['working_set_history']=memory_history;data['first_program_ready_seconds']=first_ready
  data.update(engine=a.engine,source_files=32,source_resolution=[1280,720],source_rate='60/1',proxy_mode=False,
              program_resolution=page.evaluate("renderedCurrent?[renderedCurrent.media.videoWidth,renderedCurrent.media.videoHeight]:null"),
              timeline_clips=page.evaluate("state.tracks.flatMap(t=>t.clips).length"),timeline_seconds=600,browser_errors=errors)
  cache=project.parent/(project.name+'.data')/'preview-cache'
  files=list(cache.glob('*.mp4'));data['final_complete_cache_files']=len(files);data['final_complete_cache_bytes']=sum(p.stat().st_size for p in files)
  (a.results/'playback.json').write_text(json.dumps(data,indent=2))
  assert len(files)<=12 and data['final_complete_cache_bytes']<=512*1024**2,data
  assert data['video_frame_callbacks']>0 and data['peak_meter_db']>-59,data
  assert not errors,errors
  if a.until_end:assert data['reached_sequence_end'],data
  (a.results/'playback.json').write_text(json.dumps(data,indent=2));print(json.dumps(data),flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('executable',type=Path);p.add_argument('media',type=Path);p.add_argument('results',type=Path)
 p.add_argument('--engine',choices=['interactive','rendered'],default='rendered');p.add_argument('--seconds',type=float,default=70);p.add_argument('--until-end',action='store_true');main(p.parse_args())
