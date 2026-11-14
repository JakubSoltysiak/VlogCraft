"""Complete local private originals on native GPU. No source identifiers on stdout."""
import argparse,json,sys,time,traceback
from pathlib import Path
from windows_session import session

def main(a):
 a.results=a.results.resolve();sources=json.loads(a.manifest.read_text('utf8'));rows=[]
 if any(a.results.is_relative_to(Path(row['path']).resolve().parent) for row in sources):raise ValueError('Results must remain outside original media directories')
 a.results.mkdir(parents=True,exist_ok=True)
 for n,source in enumerate(sources):
  folder=a.results/f'source-{n}';folder.mkdir()
  alias='Camera'+chr(65+n)
  with session(a.executable,folder,offline=True) as (page,proc,project,errors):
   result=page.evaluate("path=>request('import','POST',{paths:[path],autoProxy:false})",source['path'])
   assert not result['errors'],'Private media import failed; local diagnostics retained'
   page.evaluate("""assets=>{
    stopPlayback();refreshPlayers();state.assets=assets;state.tracks=[];useProxies=false;state.output.fps='60/1';
    const a=assets[0],c=clipFromAsset(a,0,'video');c.end=a.duration;c.audioDetached=true;
    state.tracks.push({id:uid(),type:'video',name:'Picture',volume:1,clips:[c]});
    if(a.hasAudio){const sound=clipFromAsset(a,0,'audio');sound.end=c.end;state.tracks.push({id:uid(),type:'audio',name:'Original audio',volume:1,clips:[sound]});}
    playhead=0;redraw();save();return flushSave();
   }""",result['assets'])
   expected=page.evaluate('Math.round(nativeDuration()*48000)');frames=page.evaluate('frameIndex(nativeDuration())')
   began=time.perf_counter();page.select_option('#playbackEngine','native')
   page.wait_for_function('nativeState.prepared&&nativeState.metrics?.completed_frames>0&&!nativeState.metrics.waiting',timeout=45000)
   first=time.perf_counter()-began
   page.evaluate('nativePlayPause()');deadline=time.monotonic()+expected/48000+30
   while page.evaluate('isPlaying'):
    if time.monotonic()>deadline:raise RuntimeError('Private media playback timeout')
    page.wait_for_timeout(250)
   page.wait_for_function('n=>nativeState.metrics?.completed_sequence_frame===n-1',arg=frames,timeout=10000)
   info=page.evaluate('({samples:nativeState.ack.samples,underruns:nativeState.ack.underruns,hdr:nativeState.hdr,native:nativeState.metrics,selected:nativeSelected()})')
   assert info['selected'] and info['samples']==expected and info['underruns']==0 and not errors
   metric=info['native'];rows.append({'alias':alias,'timeline_seconds':expected/48000,'samples':info['samples'],'expected_samples':expected,
    'underruns':info['underruns'],'first_ready_seconds':first,'native_complete':True,'HDR_linear':info['hdr'],
    'completed_last_frame':metric['completed_sequence_frame'],'skips':metric['skipped_sequence_frames'],
    'playback_interval':metric.get('timings',{}).get('playback_present_interval'),
    'pool_frames':[d.get('hardware_pool_frames') for d in metric.get('decoder_statistics',[])],
    'hdr10plus_retained_at_decode':any(r.get('hdr10plus_retained') for r in metric.get('selected',[]))})
   (a.results/'playback-safe.json').write_text(json.dumps(rows,indent=2),encoding='utf8')
   print(json.dumps({'alias':alias,'complete':True,'samples':expected,'underruns':0}),flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('executable',type=Path);p.add_argument('manifest',type=Path);p.add_argument('results',type=Path);a=p.parse_args()
 try:main(a)
 except BaseException as exc:
  a.results.mkdir(parents=True,exist_ok=True)
  (a.results/'failure-private.log').write_text(traceback.format_exc(),encoding='utf8')
  print(json.dumps({'private_camera_qualification':False,'error_type':type(exc).__name__}))
  raise SystemExit(1)
