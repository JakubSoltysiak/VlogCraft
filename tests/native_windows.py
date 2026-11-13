"""Native integrated surface/PCM transport; generated sources, no manual checks."""
import argparse,json,time,psutil
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'benchmarks')]
from windows_session import session
SETUP="""assets=>{
 stopPlayback();refreshPlayers();state.assets=assets;state.output.fps='60000/1001';useProxies=false;state.tracks=[];
 assets.forEach((a,n)=>{
 const v={id:uid(),type:'video',name:'V'+n,volume:1,clips:[]};
 const c=clipFromAsset(a,0,'video');c.start=0;c.end=4;c.audioDetached=true;
 if(n){c.scale=.4;c.opacity=.7;c.x=n===1?-.2:.2;c.keys={rotation:[{time:0,value:-5,mode:'linear'},{time:4,value:5,mode:'linear'}]};}
 v.clips=[c];state.tracks.unshift(v);
 const audio={id:uid(),type:'audio',name:'A'+n,volume:.2,clips:[]},ac=clipFromAsset(a,0,'audio');ac.end=4;audio.clips=[ac];state.tracks.push(audio);
 });playhead=0;redraw();save();return flushSave();
}"""
def main(a):
 with session(a.executable,a.results,offline=True) as (page,proc,project,errors):
  paths=[str((a.media/f'h264-4k60-{n}.mp4').resolve()) for n in range(3)]
  result=page.evaluate("paths=>request('import','POST',{paths,autoProxy:false})",paths);assert not result['errors']
  page.evaluate(SETUP,result['assets'])
  page.wait_for_function("Array.from(document.querySelector('#playbackEngine').options).some(o=>o.value==='native'&&!o.disabled)")
  before=time.perf_counter();page.select_option('#playbackEngine','native')
  page.wait_for_function("nativeState.metrics?.completed_frames>0&&!nativeState.metrics.waiting",timeout=30000);ready=time.perf_counter()-before
  page.locator('#playBtn').click();page.wait_for_function("isPlaying&&nativeState.ack?.samples>0")
  page.wait_for_timeout(900);page.locator('#playBtn').click()
  paused=page.evaluate('nativeClock()');page.wait_for_timeout(250);assert abs(page.evaluate('nativeClock()')-paused)<.08
  seek=[]
  for target in (2.2,.5,2.2):
   begin=time.perf_counter();previous=page.evaluate('nativeState.generation');page.evaluate('t=>seek(t)',target)
   page.wait_for_function("g=>nativeState.generation>g&&nativeState.metrics?.generation===nativeState.generation&&!nativeState.metrics.waiting&&Math.abs(nativeState.metrics.sequence_frame-frameIndex(playhead))<=1",arg=previous,timeout=15000)
   seek.append(time.perf_counter()-begin)
  # Coalesce rapid scrubbing, then seek during active transport before completing the sequence.
  page.evaluate('async()=>{await Promise.all([nativeSeek(80),nativeSeek(15),nativeSeek(132)]);playhead=132/sequenceRate();}')
  try:page.wait_for_function('!nativeState.seeking&&nativeState.metrics.completed_generation===nativeState.generation',timeout=15000)
  except Exception:
   (a.results/'seek-diagnostic.json').write_text(json.dumps(page.evaluate('({metrics:nativeState.metrics,generation:nativeState.generation,seekFrame:nativeState.seekFrame,start:nativeState.start,clock:nativeClock(),ack:nativeState.ack,seeking:nativeState.seeking,playhead})'),indent=2));raise
  page.locator('#playBtn').click();page.wait_for_function('isPlaying');page.wait_for_timeout(200)
  page.evaluate('()=>seek(2.2)')
  page.wait_for_function('!nativeState.seeking&&nativeState.ack?.samples>1000',timeout=15000)
  page.wait_for_function('!isPlaying&&playhead>=nativeDuration()-.001',timeout=15000)
  page.wait_for_timeout(200)
  state=page.evaluate("({clock:nativeClock(),playhead,samples:nativeState.ack.samples,underruns:nativeState.ack.underruns,metrics:nativeState.metrics,rate:state.output.fps,peakMeter:$('masterMeter').value})")
  assert state['underruns']==0,state
  assert state['metrics']['surface_parented'] and state['metrics']['surface_visible']
  page.set_viewport_size({'width':1024,'height':850})
  page.wait_for_function('Math.abs(nativeState.metrics.surface_width-Math.round(nativeRect().width*devicePixelRatio))<=1',timeout=10000)
  page.evaluate("document.querySelector('#helpModal').hidden=false")
  page.wait_for_function('nativeState.metrics.surface_visible===false',timeout=10000)
  page.evaluate("document.querySelector('#helpModal').hidden=true")
  page.wait_for_function('nativeState.metrics.surface_visible===true',timeout=10000)
  # A terminated owned renderer must return the whole SDR program to the reference engine.
  old=page.evaluate('JSON.stringify(state.tracks)')
  child=next(p for p in psutil.Process(proc.pid).children(recursive=True) if p.name().lower()=='vlogcraftnative.exe')
  child.kill();child.wait(timeout=10)
  page.wait_for_function("document.querySelector('#playbackEngine').value==='rendered'",timeout=10000)
  assert page.evaluate('JSON.stringify(state.tracks)')==old
  page.select_option('#playbackEngine','native')
  page.wait_for_function('nativeState.prepared&&nativeState.metrics?.completed_frames>0',timeout=30000)
  # Unsupported visual effects must switch the complete SDR program to reference rendering.
  page.evaluate("()=>{state.tracks.find(t=>t.type==='video').clips[0].mask='ellipse';redraw();save();}")
  page.wait_for_function("document.querySelector('#playbackEngine').value==='rendered'",timeout=15000)
  page.evaluate("request('preview/cancel','POST',{})")
  report={'initial_native_ready_seconds':ready,'seek_seconds':seek,'playback':state,'reference_fallback':True,'process_failure_recovery':True,'resize_and_modal_visibility':True,'rapid_and_playing_seek':True,'browser_errors':errors}
  a.results.mkdir(parents=True,exist_ok=True);(a.results/'native-windows.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
  assert not errors,errors
  assert state['metrics']['peak_source_queue_frames']<=4 and state['metrics']['peak_inflight_gpu_frames']<=state['metrics'].get('gpu_slot_budget',3)<=6
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('executable',type=Path);p.add_argument('media',type=Path);p.add_argument('results',type=Path);main(p.parse_args())
