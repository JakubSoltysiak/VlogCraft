"""Safe bounded extra allocation, intact playback budget, atomic export cancellation."""
import argparse,json,sys,time
from pathlib import Path
import psutil
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'benchmarks'))
from windows_session import session
from native_playback import SETUP

def main(a):
 a.results=a.results.resolve();a.results.mkdir(parents=True,exist_ok=True)
 available=psutil.virtual_memory().available;budget=min(512*1024**2,max(0,(available-4*1024**3)//4))
 assert budget>=64*1024**2,'Not enough headroom for a safe pressure test; no allocation performed'
 pressure=bytearray(budget)
 for n in range(0,budget,4096):pressure[n]=85
 with session(a.executable,a.results,offline=True) as (page,proc,project,errors):
  data=page.evaluate("paths=>request('import','POST',{paths,autoProxy:false})",[str((a.media/f'h264-4k60-{n}.mp4').resolve()) for n in range(3)]);assert not data['errors']
  page.evaluate(SETUP,{'assets':data['assets'],'seconds':12,'cut':.5});page.select_option('#playbackEngine','native')
  page.wait_for_function('nativeState.prepared&&nativeState.ack?.queued>=12000',timeout=30000);page.evaluate('nativePlayPause()')
  page.wait_for_function('!isPlaying&&nativeState.ack?.finished',timeout=30000)
  audio=page.evaluate('({samples:nativeState.ack.samples,underruns:nativeState.ack.underruns})');assert audio=={'samples':576000,'underruns':0}
  page.select_option('#playbackEngine','interactive');page.evaluate(SETUP,{'assets':data['assets'],'seconds':125,'cut':.5})
  target=a.results/'preserve-destination.mp4';target.write_bytes(b'previous destination must survive cancellation')
  page.evaluate("path=>request('export','POST',{path})",str(target));page.wait_for_timeout(250)
  page.evaluate("request('job/cancel','POST',{job:'export'})")
  deadline=time.monotonic()+20
  while time.monotonic()<deadline:
   job=page.evaluate("request('jobs')")['export']
   if job['status']=='cancelled':break
   page.wait_for_timeout(100)
  assert job['status']=='cancelled',job
  assert target.read_bytes()==b'previous destination must survive cancellation'
  deadline=time.monotonic()+10
  while list(a.results.glob('.vlogcraft_*')) and time.monotonic()<deadline:page.wait_for_timeout(100)
  assert not list(a.results.glob('.vlogcraft_*'));page.evaluate('flushSave()');assert not errors
  result={'extra_pressure_MiB':budget/2**20,'available_before_MiB':available/2**20,'playback_audio':audio,'destination_preserved':True,'cancelled':True,'temporary_export_directories_remaining':0,'browser_errors':errors,
          'scope':'Bounded extra allocation with at least4GiB pre-allocation headroom; not Windows low-memory exhaustion or physical-sync qualification'}
  (a.results/'pressure-cancel.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8');print(json.dumps(result),flush=True)
 del pressure
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('executable',type=Path);p.add_argument('media',type=Path);p.add_argument('results',type=Path);main(p.parse_args())
