"""Terminate only owned synthetic-test processes; distinguish fault, navigation and CDP loss."""
import argparse,ctypes,json,sys,time,urllib.request
from pathlib import Path
import psutil
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'benchmarks'))
from windows_session import session
from native_playback import SETUP

def get(origin,path):
 with urllib.request.urlopen(origin+'/api/'+path,timeout=2) as r:return json.load(r)

def main(a):
 rows=[]
 with session(a.executable,a.results,offline=True) as (first,proc,project,errors):
  page=first;origin=page.url.rstrip('/');endpoint=page._vlogcraft_cdp_endpoint;browser_type=page.context.browser.browser_type
  def wait_ready(after=-1,phase='ready'):
   deadline=time.monotonic()+35
   while time.monotonic()<deadline:
    status=get(origin,'desktop/recovery')
    if status['epoch']>after and status['phase']==phase:return status
    time.sleep(.1)
   raise AssertionError('Recovery did not reach '+phase)
  wait_ready()
  data=page.evaluate("paths=>request('import','POST',{paths,autoProxy:false})",[str((a.media/f'h264-4k60-{n}.mp4').resolve()) for n in range(3)])
  assert not data['errors'];page.evaluate(SETUP,{'assets':data['assets'],'seconds':30,'cut':.5})
  page.select_option('#playbackEngine','native');page.wait_for_function('nativeState.prepared&&nativeState.metrics?.completed_frames>0&&!nativeState.metrics.waiting',timeout=30000)
  page.evaluate('recoverySettled()')
  def reconnect():
   nonlocal page
   first._vlogcraft_intentional_detach=True
   try:page.context.browser.close()
   except Exception:pass
   browser=browser_type.connect_over_cdp(endpoint,no_defaults=True)
   page=next(p for p in browser.contexts[0].pages if p.url.startswith(origin));page.set_viewport_size({'width':1440,'height':850})
   page.wait_for_function("state?.desktop&&document.documentElement.classList.contains('native-ready')")
  def owned_role(role):
   found=[]
   for p in psutil.Process(proc.pid).children(recursive=True):
    try:
     if p.name().lower()!='msedgewebview2.exe':continue
     command=p.cmdline();kind=next((x.split('=',1)[1] for x in command if x.startswith('--type=')),'browser')
     if kind==role:found.append(p)
    except psutil.Error:pass
   assert len(found)==1,'Expected exactly one owned '+role
   return found[0]
  def pending(n,playing=False):
   page.evaluate('stopPlayback();seek(2)');page.wait_for_timeout(600)
   if playing:page.evaluate('nativePlayPause()');page.wait_for_timeout(300)
   target='Unsaved recovery '+str(n)
   page.evaluate("name=>{snapshot();state.name=name;save();clearTimeout(saveTimer);saveTimer=null;return recoverySettled();}",target)
   assert json.loads(project.read_text('utf8'))['name']!=target,'Fixture must exercise an unpublished durable draft'
   return target
  for n,role in enumerate(('renderer','renderer','browser'),1):
   target=pending(n,playing=n==2);old=get(origin,'desktop/recovery')['epoch'];began=time.perf_counter()
   owned_role(role).terminate();status=wait_ready(old);reconnect()
   actual=page.evaluate('({name:state.name,undo:undoStack.length,playing:isPlaying,position:playhead})')
   assert actual['name']==target and actual['undo']>0 and not actual['playing']
   if n!=2:assert abs(actual['position']-2)<.05,actual
   page.evaluate('restoreHistory(undoStack,redoStack)');assert page.evaluate('state.name')!=target
   page.evaluate('restoreHistory(redoStack,undoStack);flushSave()');assert page.evaluate('state.name')==target
   assert len([p for p in psutil.Process(proc.pid).children(recursive=True) if p.name()=='VlogCraftNative.exe'])<=1
   rows.append({'injected':role,'recovered':True,'seconds':time.perf_counter()-began,'draft':True,'undo_redo':True,'paused':True,'epoch':status['epoch']})
   (a.results/'recovery.json').write_text(json.dumps(rows,indent=2),encoding='utf8')
  # A stale view must not publish over the recovered project.
  before=project.read_bytes();old_data=page.evaluate('({...state,_desktopEpoch:0,_editRevision:999,name:"stale view"})')
  try:
   urllib.request.urlopen(urllib.request.Request(origin+'/api/state',data=json.dumps(old_data).encode(),headers={'Content-Type':'application/json'}),timeout=5)
   raise AssertionError('Stale save unexpectedly accepted')
  except urllib.error.HTTPError as exc:assert exc.code==400
  assert project.read_bytes()==before
  epoch=get(origin,'desktop/recovery')['epoch'];name=page.evaluate('state.name')
  try:page.goto('http://127.0.0.1:9/unexpected',timeout=3000)
  except Exception:pass
  assert page.evaluate('state.name')==name and get(origin,'desktop/recovery')['epoch']==epoch
  page.select_option('#playbackEngine','native');page.evaluate('nativePlayPause()');page.wait_for_timeout(500)
  frame=page.evaluate('nativeState.metrics.sequence_frame');page.context.browser.close();time.sleep(2);reconnect()
  assert get(origin,'desktop/recovery')['epoch']==epoch
  assert page.evaluate('nativeState.metrics.sequence_frame')>frame
  page.evaluate('stopPlayback()')
  # Fourth failure inside one minute exercises the automatic-attempt budget and real Retry button.
  owned_role('renderer').terminate();status=wait_ready(epoch,phase='failed')
  clicked=[];family={proc.pid,*[p.pid for p in psutil.Process(proc.pid).children(recursive=True)]}
  def click(hwnd,_):
   pid=ctypes.c_ulong();ctypes.windll.user32.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
   title=ctypes.create_unicode_buffer(128);ctypes.windll.user32.GetWindowTextW(hwnd,title,128)
   if pid.value in family and title.value=='Retry editor':ctypes.windll.user32.SendMessageW(hwnd,0xF5,0,0);clicked.append(True)
   return True
  callback=ctypes.WINFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)(click)
  # EnumChildWindows requires the owned top-level form.
  def top(hwnd,_):
   pid=ctypes.c_ulong();ctypes.windll.user32.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
   if pid.value in family:ctypes.windll.user32.EnumChildWindows(hwnd,callback,0)
   return True
  top_callback=ctypes.WINFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)(top);ctypes.windll.user32.EnumWindows(top_callback,0)
  assert clicked;wait_ready(status['epoch']);reconnect()
  page.evaluate('flushSave()');assert not errors
  rows.append({'observer_detach_no_recovery':True,'navigation_blocked':True,'stale_save_rejected':True,'budget_and_manual_retry':True})
  (a.results/'recovery.json').write_text(json.dumps(rows,indent=2),encoding='utf8');print(json.dumps({'recovery_checks':True,'injected_failures':4,'manual_retry':True}),flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('executable',type=Path);p.add_argument('media',type=Path);p.add_argument('results',type=Path);main(p.parse_args())
