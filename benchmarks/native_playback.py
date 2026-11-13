"""Sustained native program transport: moving original4K layers, PCM and frequent cuts."""
import argparse,json,sys,time
from pathlib import Path
from windows_session import session
from resource_history import History
from conditions import Conditions
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tests'))
from performance import Resources
SETUP="""({assets,seconds,cut})=>{
 stopPlayback();refreshPlayers();state.assets=assets;state.output.fps=60;useProxies=false;state.tracks=[];
 assets.forEach((a,n)=>{
  const video={id:uid(),type:'video',name:'Video'+n,volume:1,clips:[]},audio={id:uid(),type:'audio',name:'Audio'+n,volume:.2,clips:[]};
  for(let i=0;i<Math.ceil(seconds/cut);i++){
   const start=(i%3)*.5,c=clipFromAsset(a,i*cut,'video');c.start=start;c.end=start+Math.min(cut,seconds-i*cut);c.audioDetached=true;
   if(n){c.scale=.4;c.x=n===1?-.2:.2;c.opacity=.7;c.keys={rotation:[{time:0,value:-4,mode:'linear'},{time:6,value:4,mode:'linear'}]};}
   video.clips.push(c);const sound=clipFromAsset(a,i*cut,'audio');sound.start=c.start;sound.end=c.end;audio.clips.push(sound);
  }
  state.tracks.unshift(video);state.tracks.push(audio);
 });playhead=0;redraw();save();return flushSave();
}"""
def main(a):
 with session(a.executable,a.results,offline=True) as (page,proc,project,errors):
  result=page.evaluate("paths=>request('import','POST',{paths,autoProxy:false})",[str((a.media/f'h264-4k60-{n}.mp4').resolve()) for n in range(a.layers)])
  assert not result['errors']
  page.evaluate(SETUP,{'assets':result['assets'],'seconds':a.seconds,'cut':a.cut})
  page.evaluate("""({width,rate})=>{state.output.fps=rate;const select=$('programResolution');if(![...select.options].some(o=>o.value===String(width)))select.add(new Option('Benchmark',width));select.value=width;save();return flushSave();}""",{'width':a.width,'rate':a.rate})
  page.wait_for_function("Array.from(document.querySelector('#playbackEngine').options).some(o=>o.value==='native'&&!o.disabled)")
  display=None
  if a.actual_display:
   from display_layout import actual_display
   display=actual_display(page,proc)
  if a.large_surface:
   page.evaluate("""()=>{const w=Math.min(innerWidth-24,(innerHeight-140)*16/9),css=document.createElement('style');css.textContent='#previewStage{position:fixed!important;left:12px!important;top:90px!important;width:'+w+'px!important;height:'+w*9/16+'px!important;max-height:none!important;max-width:none!important;z-index:400}';document.head.append(css);}""")
  begin=time.perf_counter();page.select_option('#playbackEngine','native')
  page.wait_for_function('nativeState.metrics?.completed_frames>0',timeout=30000);ready=time.perf_counter()-begin
  meter=Resources(proc.pid,gpu=True);history=History(proc.pid,5);conditions=Conditions()
  page.evaluate("""async()=>{
   await nativePlayPause();window.nativeBench={start:performance.now(),base:{...nativeState.metrics},peak:-60};
   nativeBench.timer=setInterval(()=>nativeBench.peak=Math.max(nativeBench.peak,Number($('masterMeter').value)),25);
  }""")
  deadline=time.monotonic()+a.seconds+20;checkpoint=0
  while True:
   data=page.evaluate("""()=>({measured_seconds:(performance.now()-nativeBench.start)/1000,base:nativeBench.base,last:nativeState.metrics,
    samples:nativeState.ack?.samples,underruns:nativeState.ack?.underruns,playing:isPlaying,
    reached_end:playhead>=nativeDuration()-.001,peak_meter_db:nativeBench.peak})""")
   if data['measured_seconds']>=checkpoint:
    (a.results/'checkpoint.json').write_text(json.dumps(data,indent=2));checkpoint+=5
   if not data['playing'] or time.monotonic()>deadline:break
   page.wait_for_timeout(250)
  page.evaluate('clearInterval(nativeBench.timer)');page.wait_for_timeout(200)
  data['working_set_history']=history.finish();data['resources']=meter.finish();data['conditions']=conditions.finish()
  data['actual_display_layout']=display;data['native_rect']=page.evaluate('nativeRect()')
  if a.large_surface:assert abs(data['native_rect']['width']/data['native_rect']['height']-16/9)<.005,'Benchmark monitor aspect changed unexpectedly'
  data.update(application_ready_seconds=getattr(page,'_vlogcraft_launch_seconds',None),first_ready_seconds=ready,seconds=a.seconds,cut_seconds=a.cut,video_tracks=a.layers,audio_tracks=a.layers,original_resolution=[3840,2160],
              program_resolution=[a.width,a.width*9//16],rate=a.rate,browser_errors=errors,proxies=False)
  data['expected_samples']=page.evaluate('Math.round(nativeDuration()*48000)')
  elapsed=data['measured_seconds']
  for key in ('completed_frames','present_calls','dxgi_present_count'):
   data[key+'_per_second']=((data['last'][key]-data['base'][key])/elapsed if key in data['last'] and key in data['base'] else None)
  if 'distinct_sequence_submissions' in data['last']:
   data['distinct_sequence_fps']=(data['last']['distinct_sequence_submissions']-data['base'].get('distinct_sequence_submissions',1))/elapsed
  cache=project.parent/(project.name+'.data')
  data['intermediate_encoded_video_files']=len(list((cache/'native-preview').rglob('*.mp4')))+len(list((cache/'preview-cache').glob('*.mp4')))
  (a.results/'native-playback.json').write_text(json.dumps(data,indent=2));print(json.dumps(data),flush=True)
  assert data['reached_end'] and data['samples']==data['expected_samples'],data
  assert not errors and data['peak_meter_db']>-59,data
  assert data['last']['peak_source_queue_frames']<=4 and data['last']['peak_inflight_gpu_frames']<=data['last'].get('gpu_slot_budget',3)<=6,data
  assert data['intermediate_encoded_video_files']==0,data
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('executable',type=Path);p.add_argument('media',type=Path);p.add_argument('results',type=Path)
 p.add_argument('--seconds',type=float,default=60);p.add_argument('--cut',type=float,default=.5)
 p.add_argument('--actual-display',action='store_true');p.add_argument('--large-surface',action='store_true');p.add_argument('--width',type=int,default=960);p.add_argument('--layers',type=int,choices=(1,3),default=3);p.add_argument('--rate',default='60/1');main(p.parse_args())
