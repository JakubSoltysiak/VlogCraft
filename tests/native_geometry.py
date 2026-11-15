"""Verify real monitor/child placement at actual Windows scaling, without camera pixels."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'benchmarks'))
from windows_session import session
from native_playback import SETUP
from window_geometry import alignment,resize

def main(a):
 with session(a.executable,a.results,offline=True) as (page,proc,project,errors):
  imported=page.evaluate("path=>request('import','POST',{paths:[path],autoProxy:false})",str((a.media/'h264-4k60-0.mp4').resolve()))
  assert not imported['errors'];page.evaluate(SETUP,{'assets':imported['assets'],'seconds':6,'cut':.5})
  page.select_option('#playbackEngine','native');page.wait_for_function('nativeState.metrics?.completed_frames>0',timeout=30000)
  page.wait_for_timeout(500);before=alignment(page,proc)
  resize(proc);page.wait_for_timeout(1000);after=alignment(page,proc)
  result={'before':before,'after_resize':after,'browser_errors':errors}
  (a.results/'geometry.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
  assert all(max(r['absolute_error_pixels'])<=3 for r in (before,after)),result
  assert not errors
  print(json.dumps(result),flush=True)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('executable',type=Path);p.add_argument('media',type=Path);p.add_argument('results',type=Path);main(p.parse_args())
