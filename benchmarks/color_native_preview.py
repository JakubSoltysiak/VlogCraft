"""Short actual HDR surface/PCM check; private original remains read-only."""
import argparse,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from windows_session import session
from window_visibility import WindowVisibility
from tools.performance_record import fingerprint
import hashlib,subprocess

def main(a):
 original=json.loads(a.manifest.read_text())[0];a.results.mkdir(parents=True,exist_ok=True)
 with session(a.executable,a.results,offline=True) as (page,proc,project,errors),WindowVisibility(proc,'visible') as visibility:
  page.set_default_timeout(15000)
  imported=page.evaluate("p=>request('import','POST',{paths:[p],autoProxy:false})",original['path']);assert not imported['errors']
  page.evaluate("""assets=>{stopPlayback();refreshPlayers();state.assets=assets;const c=clipFromAsset(assets[0],0,'video');c.end=3;c.inputColor={profile:'source',range:'auto',pixelAspect:'square'};state.tracks=[{id:uid(),type:'video',name:'Picture',volume:1,clips:[c]}];state.output={width:144,height:256,fps:60,encoder:'libx265',crf:20,preset:'veryfast',color:{version:1,workingSpace:'linear-rec2020-100nits',output:'hdr10',sdrWhiteNits:100}};playhead=0;redraw();save();return flushSave();}""",imported['assets'])
  page.evaluate("()=>{const s=$('previewStage'),d=devicePixelRatio;s.style.width=180/d+'px';s.style.height=320/d+'px';s.style.flex='0 0 auto';s.style.maxWidth='none';}")
  page.select_option('#playbackEngine','native');page.select_option('#programResolution','960');page.wait_for_function('nativeState.prepared&&nativeState.metrics?.completed_frames>0&&!nativeState.metrics.waiting||nativeState.blocked',timeout=45000)
  if page.evaluate('nativeState.blocked'):raise AssertionError('HDR presentation unavailable/failed; retained local diagnostics, do not claim this preview tested')
  page.evaluate('nativePlayPause()');deadline=time.monotonic()+15
  while page.evaluate('isPlaying'):
   assert time.monotonic()<deadline,'HDR preview playback did not finish';page.wait_for_timeout(100)
  info=page.evaluate('({samples:nativeState.ack.samples,underruns:nativeState.ack.underruns,metrics:nativeState.metrics,status:$("programPreviewStatus").textContent})')
  m=info['metrics'];assert m['hdr_linear_scrgb'] and info['samples']==144000 and info['underruns']==0 and not errors
  condition=visibility.finish();assert condition['condition_held'],'Retain failed window condition'
  result={'alias':'CameraA','duration_seconds':3,'source_PQ_Main10':True,'explicit_square_pixel_interpretation':True,'native_HDR_linear_scRGB':m['hdr_linear_scrgb'],
   'composition':[960,1706],'physical_surface':[m['surface_width'],m['surface_height']],
   'samples':info['samples'],'underruns':info['underruns'],'skips':m['skipped_sequence_frames'],'dynamic_metadata_decode_retained':any(x.get('hdr10plus_retained') for x in m.get('selected',[])),
   'window_condition_held':condition['condition_held'],'calibrated_monitoring':False,'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'source_fingerprint':fingerprint(),'host_sha256':hashlib.sha256(a.executable.read_bytes()).hexdigest(),'scope':'Three-second HDR presentation/PCM check, not sustained playback or HDR10+ display mastering.'}
  (a.results/'color-native.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('executable',type=Path);p.add_argument('manifest',type=Path);p.add_argument('results',type=Path);main(p.parse_args())
