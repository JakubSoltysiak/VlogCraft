"""Close only owned generated project windows during initialization; no camera media."""
import argparse,ctypes,json,os,shutil,subprocess,sys,tempfile,time
from pathlib import Path
import psutil

def main(a):
 a.results=a.results.resolve();a.results.mkdir(parents=True,exist_ok=True);rows=[]
 for n in range(3):
  folder=a.results/str(n);folder.mkdir()
  with tempfile.TemporaryDirectory(dir=folder) as temp:
   project=Path(temp)/'early-close.vlogcraft';cmd=[str(a.executable.resolve())]
   if a.executable.stem.lower()=='python':cmd.append(str(Path('desktop.py').resolve()))
   with (folder/'host.log').open('wb') as log:
    proc=subprocess.Popen([*cmd,'--project',str(project)],stdout=log,stderr=log)
    deadline=time.monotonic()+35;found=[];owned=[]
    while time.monotonic()<deadline and not found:
     family={proc.pid,*[p.pid for p in psutil.Process(proc.pid).children(recursive=True)]}
     def window(hwnd,_):
      pid=ctypes.c_ulong();ctypes.windll.user32.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
      title=ctypes.create_unicode_buffer(256);ctypes.windll.user32.GetWindowTextW(hwnd,title,256)
      if pid.value in family and title.value=='VlogCraft Studio • early-close' and ctypes.windll.user32.IsWindowVisible(hwnd):found.append(hwnd)
      return True
     callback=ctypes.WINFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)(window);ctypes.windll.user32.EnumWindows(callback,0);time.sleep(.05)
    assert found,'Owned startup window did not appear'
    time.sleep(n*.25)
    for p in psutil.Process(proc.pid).children(recursive=True):
     try:owned.append((p.pid,p.create_time()))
     except psutil.Error:pass
    ctypes.windll.user32.PostMessageW(found[0],0x10,0,0)
    try:code=proc.wait(timeout=40)
    except subprocess.TimeoutExpired:
     for p in psutil.Process(proc.pid).children(recursive=True):
      try:p.terminate()
      except psutil.Error:pass
     proc.terminate();proc.wait();raise
   cache=project.parent/(project.name+'.data')
   for name in ('studio.log','lifecycle.jsonl'):
    if (cache/name).exists():shutil.copy2(cache/name,folder/name)
   deadline=time.monotonic()+10;remaining=[]
   while time.monotonic()<deadline:
    remaining=[]
    for pid,created in owned:
     try:
      p=psutil.Process(pid)
      if p.create_time()==created and p.is_running():remaining.append(pid)
     except psutil.Error:pass
    if not remaining:break
    time.sleep(.1)
   rows.append({'cycle':n,'delay_after_visible_seconds':n*.25,'exit_code':code,'owned_children_remaining':len(remaining)})
   (a.results/'startup-close.json').write_text(json.dumps(rows,indent=2)+'\n',encoding='utf8')
   assert code==0 and not remaining,rows[-1]
 print(json.dumps(rows),flush=True)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('executable',type=Path);p.add_argument('results',type=Path);main(p.parse_args())
