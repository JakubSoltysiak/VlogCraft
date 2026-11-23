"""Sustained native program transport: moving original4K layers, PCM and frequent cuts."""
import argparse,json,os,sys,time
from pathlib import Path
from fractions import Fraction
from contextlib import ExitStack
from windows_session import session
from resource_history import History
from conditions import Conditions
from runtime_trace import RuntimeTrace,windows,active_windows
from window_geometry import alignment
from window_visibility import WindowVisibility
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tests'))
from performance import Resources
SETUP="""({assets,seconds,cut,switchSources=false,staggerRewinds=false})=>{
 stopPlayback();refreshPlayers();state.assets=assets;state.output.fps=60;useProxies=false;state.tracks=[];
 const trackAssets=switchSources?assets.slice(0,1):assets;
 trackAssets.forEach((a,n)=>{
  const video={id:uid(),type:'video',name:'Video'+n,volume:1,clips:[]},audio={id:uid(),type:'audio',name:'Audio'+n,volume:.2,clips:[]};
  for(let i=0;i<Math.ceil(seconds/cut);i++){
   const shot=switchSources?assets[i%assets.length]:a;
   const sourcePhase=staggerRewinds?n:0;
   const start=switchSources?(Math.floor(i/assets.length)%3)*.5:((i+sourcePhase)%3)*.5;
   const c=clipFromAsset(shot,i*cut,'video');c.start=start;c.end=start+Math.min(cut,seconds-i*cut);c.audioDetached=true;
   if(n){c.scale=.4;c.x=n===1?-.2:.2;c.opacity=.7;c.keys={rotation:[{time:0,value:-4,mode:'linear'},{time:6,value:4,mode:'linear'}]};}
   video.clips.push(c);const sound=clipFromAsset(shot,i*cut,'audio');sound.start=c.start;sound.end=c.end;audio.clips.push(sound);
  }
  state.tracks.unshift(video);state.tracks.push(audio);
 });playhead=0;redraw();save();return flushSave();
}"""
def main(a):
 with session(a.executable,a.results,offline=True,legacy_viewport=a.legacy_viewport,legacy_focus_emulation=a.legacy_focus_emulation) as (page,proc,project,errors),ExitStack() as owned_windows:
  result=page.evaluate("paths=>request('import','POST',{paths,autoProxy:false})",[str((a.media/f'h264-4k60-{n}.mp4').resolve()) for n in range(3 if a.switch_sources else a.layers)])
  assert not result['errors']
  page.evaluate(SETUP,{'assets':result['assets'],'seconds':a.seconds,'cut':a.cut,'switchSources':a.switch_sources,'staggerRewinds':a.stagger_source_rewinds})
  page.evaluate("""({width,rate})=>{state.output.fps=rate;const select=$('programResolution');if(![...select.options].some(o=>o.value===String(width)))select.add(new Option('Benchmark',width));select.value=width;save();return flushSave();}""",{'width':a.width,'rate':a.rate})
  page.wait_for_function("Array.from(document.querySelector('#playbackEngine').options).some(o=>o.value==='native'&&!o.disabled)")
  if not a.legacy_viewport and not a.actual_display and not a.large_surface:
   page.evaluate("()=>{const stage=$('previewStage'),d=devicePixelRatio;stage.style.width=(356/d)+'px';stage.style.height=(200/d)+'px';stage.style.maxWidth='none';stage.style.maxHeight='none';stage.style.flex='0 0 auto';}")
  ui_patch=None
  if a.ui_source:
   from ui_patch import inject
   ui_patch=inject(page)
  display=None
  if a.actual_display:
   from display_layout import actual_display
   display=actual_display(page,proc)
  if a.large_surface:
   page.evaluate("""()=>{const w=Math.min(innerWidth-24,(innerHeight-140)*16/9),css=document.createElement('style');css.textContent='#previewStage{position:fixed!important;left:12px!important;top:90px!important;width:'+w+'px!important;height:'+w*9/16+'px!important;max-height:none!important;max-width:none!important;z-index:400}';document.head.append(css);}""")
  begin=time.perf_counter();page.select_option('#playbackEngine','native')
  page.wait_for_function('nativeState.metrics?.completed_frames>0',timeout=30000);ready=time.perf_counter()-begin
  physical_alignment=None
  if not a.legacy_viewport:
   page.wait_for_timeout(200);physical_alignment=alignment(page,proc)
   assert max(physical_alignment['absolute_error_pixels'])<=3,physical_alignment
  visibility=owned_windows.enter_context(WindowVisibility(proc,a.window_mode))
  if a.window_mode in ('visible-browser-unfocused','editor-covered-unfocused'):page.wait_for_function('!document.hasFocus()',timeout=5000)
  meter=Resources(proc.pid,gpu=not a.diagnostic_no_gpu_counters);history=History(proc.pid,5);conditions=Conditions()
  trace=RuntimeTrace(proc.pid) if a.trace else None;status_rows=[];last_status=-1
  failure=None;data={};focus_changes=[]
  expected_samples=page.evaluate('Math.round(nativeDuration()*48000)')
  try:
   page.evaluate("""async()=>{
    await nativePlayPause();window.nativeBench={start:performance.now(),base:{...nativeState.metrics},peak:-60};
    nativeBench.timer=setInterval(()=>nativeBench.peak=Math.max(nativeBench.peak,Number($('masterMeter').value)),25);
   }""")
   deadline=time.monotonic()+a.seconds+20;checkpoint=0
   while True:
    data=page.evaluate("""()=>({measured_seconds:(performance.now()-nativeBench.start)/1000,base:nativeBench.base,last:nativeState.metrics,
     samples:nativeState.ack?.samples,underruns:nativeState.ack?.underruns,playing:isPlaying,
     reached_end:playhead>=nativeDuration()-.001,peak_meter_db:nativeBench.peak,browser_focused:document.hasFocus()})""")
    if not focus_changes or focus_changes[-1]['focused']!=data['browser_focused']:focus_changes.append({'seconds':data['measured_seconds'],'focused':data['browser_focused']})
    if a.trace and data['last'].get('wall_seconds',-1)>last_status:
     row=data['last'];last_status=row['wall_seconds'];status_rows.append({k:row[k] for k in ('wall_seconds','sequence_frame','present_calls','completed_frames','skipped_sequence_frames','source_wait_iterations','gpu_wait_iterations','skipped_without_queue_wait','clock_rewind_hold_iterations') if k in row})
    if data['measured_seconds']>=checkpoint:
     (a.results/'checkpoint.json').write_text(json.dumps(data,indent=2));checkpoint+=5
    if not data['playing'] or time.monotonic()>deadline:break
    page.wait_for_timeout(250)
   page.evaluate('clearInterval(nativeBench.timer)');page.wait_for_timeout(200)
  except Exception as exc:
   failure=exc
  data['working_set_history']=history.finish();data['resources']=meter.finish();data['conditions']=conditions.finish()
  data['window_condition']=visibility.finish()
  data['browser_focus_changes']=focus_changes
  data['focus_emulation']='Playwright default override' if a.legacy_focus_emulation else 'disabled via connect_over_cdp(no_defaults=True)'
  data['browser_visibility_state']=page.evaluate('({state:document.visibilityState,focused:document.hasFocus(),dpr:devicePixelRatio})') if failure is None else None
  if trace:
   data['runtime_trace']=trace.finish();data['status_trace']=status_rows
   active_rows=[r for r in status_rows if r.get('sequence_frame',0)>0]
   data['throughput_windows']=[windows(active_rows,n) for n in (1,10)]
   data['active_throughput_windows']=[active_windows(status_rows,n,round(a.seconds*float(Fraction(a.rate)))-1) for n in (1,10)]
   data['frame_interval_scope']=('Playback-only Present histogram excludes initial paused preparation; lifetime timing retained separately.' if 'playback_present_interval' in data.get('last',{}).get('timings',{}) else 'Native lifetime histogram includes initial paused-frame preparation; p99 unavailable in unchanged 3.4.7 binary. Active counter windows exclude frame-zero startup.')
   if failure is None:data['drained_last']=page.evaluate('nativeState.metrics')
  if failure is not None:
   data.update(failed=True,failure_type=type(failure).__name__,expected_samples=expected_samples,reached_end=False)
   (a.results/'native-playback.json').write_text(json.dumps(data,indent=2),encoding='utf8')
   raise failure
  data['layout_contract']='legacy DPR1 emulation' if a.legacy_viewport else 'native DPI; fixed356x200 physical monitor unless actual-display/large-surface';data['physical_alignment']=physical_alignment;data['actual_display_layout']=display;data['native_rect']=page.evaluate('nativeRect()')
  if a.large_surface:assert abs(data['native_rect']['width']/data['native_rect']['height']-16/9)<.005,'Benchmark monitor aspect changed unexpectedly'
  data.update(ui_source_patch_sha256=ui_patch,application_ready_seconds=getattr(page,'_vlogcraft_launch_seconds',None),first_ready_seconds=ready,seconds=a.seconds,cut_seconds=a.cut,video_tracks=a.layers,audio_tracks=a.layers,source_files=len(result['assets']),source_switches=a.switch_sources,original_resolution=[3840,2160],
              program_resolution=[a.width,a.width*9//16],rate=a.rate,browser_errors=errors,proxies=False)
  data['expected_samples']=page.evaluate('Math.round(nativeDuration()*48000)')
  data['source_rewind_schedule']='staggered diagnostic' if a.stagger_source_rewinds else 'original'
  data['gpu_counter_observer']='disabled for attribution diagnostic; not protected acceptance' if a.diagnostic_no_gpu_counters else 'legacy high-frequency PDH GPU observer; cost recorded separately'
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
  assert data['underruns']==0,'Audio underruns occurred; trial is not qualified'
  assert data['last']['peak_source_queue_frames']<=4 and data['last']['peak_inflight_gpu_frames']<=data['last'].get('gpu_slot_budget',3)<=6,data
  assert data['intermediate_encoded_video_files']==0,data
  if a.window_mode!='uncontrolled':assert data['window_condition']['condition_held'],'Requested visible/covered condition was not maintained; retain trial as unqualified'
  if a.window_mode in ('visible-browser-unfocused','editor-covered-unfocused'):assert focus_changes and all(not r['focused'] for r in focus_changes),'Actual browser focus changed during the background-focus arm'
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('executable',type=Path);p.add_argument('media',type=Path);p.add_argument('results',type=Path)
 p.add_argument('--seconds',type=float,default=60);p.add_argument('--cut',type=float,default=.5)
 p.add_argument('--window-mode',choices=('uncontrolled','visible','visible-unfocused','visible-browser-unfocused','preview-covered','editor-covered','editor-covered-unfocused'),default='visible')
 p.add_argument('--legacy-focus-emulation',action='store_true',help='Diagnostic reproduction only; keep Playwright artificial page focus')
 p.add_argument('--diagnostic-no-gpu-counters',action='store_true',help='Attribution control only; retain all original/default-observer acceptance scores')
 p.add_argument('--legacy-viewport',action='store_true',help='Replay historical DPR1 measurement geometry; not visual-placement qualification');p.add_argument('--trace',action='store_true');p.add_argument('--ui-source',action='store_true');p.add_argument('--actual-display',action='store_true');p.add_argument('--large-surface',action='store_true');p.add_argument('--width',type=int,default=960);p.add_argument('--layers',type=int,choices=(1,3),default=3);p.add_argument('--rate',default='60/1');p.add_argument('--switch-sources',action='store_true',help='Alternate three sources in one picture track and one audio track')
 p.add_argument('--native-miss-trace',action='store_true',help='Retain the native per-miss diagnostic on clean playback-worker shutdown')
 p.add_argument('--stagger-source-rewinds',action='store_true',help='Diagnostic: offset the three source loops by one cut each while preserving all pictures, audio tracks and cut boundaries')
 args=p.parse_args()
 if args.stagger_source_rewinds and (args.layers!=3 or args.switch_sources or args.cut!=.5):p.error('Staggered rewinds require the three-layer half-second cut fixture')
 if args.switch_sources and args.layers!=1:p.error('--switch-sources requires --layers 1')
 if args.native_miss_trace:
  args.results.mkdir(parents=True,exist_ok=True)
  os.environ['VLOGCRAFT_NATIVE_TRACE_FILE']=str((args.results/'native-misses.json').resolve())
 main(args)
