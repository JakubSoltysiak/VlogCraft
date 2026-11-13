"""Real local diagnostics, native monitor override and original-resolution reference invariants."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'benchmarks'))
from windows_session import session
def main(a):
 with session(a.executable,a.results,offline=True) as (page,proc,project,errors):
  original=page.evaluate('JSON.stringify(state.output)')
  page.locator('#performanceBtn').click();page.locator('#performanceDisk').check();page.locator('#performanceRun').click()
  page.wait_for_function("performanceReport?.status==='complete'",timeout=60000)
  r=page.evaluate('performanceReport')
  assert r['hardware']['native']['active_refresh_hz']>0
  assert r['storage_test']['available'] and r['storage_test']['bytes_written']==134217728
  page.locator('#performanceApply').click();assert page.evaluate('JSON.stringify(state.output)')==original
  page.locator('[data-close="performanceModal"]').click()
  data=page.evaluate("paths=>request('import','POST',{paths,autoProxy:false})",[str((a.media/'h264-4k60-0.mp4').resolve())]);assert not data['errors']
  page.evaluate("assets=>{state.assets=assets;state.tracks=[{id:uid(),type:'video',name:'Video',volume:1,clips:[clipFromAsset(assets[0],0,'video')]}];redraw();save();return flushSave();}",data['assets'])
  page.select_option('#playbackEngine','native');page.wait_for_function('nativeState.prepared&&nativeState.metrics?.completed_frames>0',timeout=30000)
  assert page.locator('#previewSource').is_disabled() and page.locator('#previewSource').input_value()=='original'
  page.select_option('#programResolution','2560')
  page.wait_for_function('nativeState.signature.startsWith(\'["2560"\')&&nativeState.prepared&&nativeState.metrics?.completed_frames>0',timeout=30000)
  assert '2560 × 1440' in page.locator('#programPreviewStatus').inner_text()
  assert page.evaluate('JSON.stringify(state.output)')==original
  page.select_option('#playbackEngine','rendered');assert page.locator('#programResolution').input_value()=='960'
  assert not page.locator('#previewSource').is_disabled()
  (a.results/'settings.json').write_text(json.dumps({'local_inventory':True,'bounded_storage':True,'reversible_preview_only':True,'native_1440p':True,'browser_errors':errors},indent=2))
  assert not errors
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('executable',type=Path);p.add_argument('media',type=Path);p.add_argument('results',type=Path);main(p.parse_args())
