"""Reopen only an owned generated project; check recovery history and process cleanup."""
import argparse,json,sys,time
from pathlib import Path
import psutil
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'benchmarks'))
from windows_session import session
from native_playback import SETUP

def main(a):
 a.results=a.results.resolve();a.results.mkdir(parents=True,exist_ok=True);project=a.results/'reopen.vlogcraft';rows=[]
 for n in range(a.repeat):
  folder=a.results/f'cycle-{n}';owned=[]
  with session(a.executable,folder,offline=True,project_path=project) as (page,proc,path,errors):
   if n==0:
    data=page.evaluate("paths=>request('import','POST',{paths,autoProxy:false})",[str((a.media/'h264-4k60-0.mp4').resolve())]);assert not data['errors']
    page.evaluate(SETUP,{'assets':data['assets'],'seconds':12,'cut':.5})
   else:assert page.evaluate('state.name')=='Lifecycle '+str(n-1)
   page.wait_for_function('typeof recoveryEpoch!=="undefined"');page.select_option('#playbackEngine','native')
   page.wait_for_function('nativeState.prepared&&nativeState.ack?.queued>=12000',timeout=30000)
   page.evaluate('nativePlayPause()');page.wait_for_timeout(500);page.evaluate('stopPlayback();nativeSeek(120)')
   page.wait_for_function('nativeState.ack?.queued>=12000',timeout=15000)
   page.evaluate("name=>{snapshot();state.name=name;save();return flushSave();}",'Lifecycle '+str(n))
   page.evaluate('recoverySettled()');page.evaluate('nativeStop()');page.wait_for_timeout(300)
   assert not get_status(page)['running'];assert not errors
   for p in psutil.Process(proc.pid).children(recursive=True):
    try:owned.append((p.pid,p.create_time()))
    except psutil.Error:pass
   rows.append({'cycle':n,'reopened':True,'history_entries':page.evaluate('undoStack.length'),'native_stopped':True})
  deadline=time.monotonic()+10
  while time.monotonic()<deadline:
   alive=[]
   for pid,created in owned:
    try:
     p=psutil.Process(pid)
     if p.create_time()==created and p.is_running():alive.append(pid)
    except psutil.Error:pass
   if not alive:break
   time.sleep(.1)
  rows[-1]['owned_children_remaining']=len(alive);assert not alive,'Owned children remain after normal close'
  (a.results/'lifecycle.json').write_text(json.dumps(rows,indent=2)+'\n',encoding='utf8')
 print(json.dumps({'cycles':len(rows),'all_children_released':True}),flush=True)
def get_status(page):return page.evaluate("request('native/status')")
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('executable',type=Path);p.add_argument('media',type=Path);p.add_argument('results',type=Path);p.add_argument('--repeat',type=int,default=5);main(p.parse_args())
