"""Fresh-process ready time, filesystem/runtime caches unmanaged."""
import argparse,json,statistics,time
from pathlib import Path
from windows_session import session
def main(a):
 values=[]
 for i in range(3):
  with session(a.executable,a.results/str(i),offline=True) as (page,proc,project,errors):
   values.append(page._vlogcraft_launch_seconds);assert not errors
 r={'fresh_process_ready_seconds':values,'median':statistics.median(values),'range':[min(values),max(values)],'filesystem_cache':'unmanaged','endpoint':'native-ready application state; no media imported'}
 (a.results/'startup.json').write_text(json.dumps(r,indent=2));print(json.dumps(r))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('executable',type=Path);p.add_argument('results',type=Path);main(p.parse_args())
