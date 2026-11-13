"""Detect a source-index subprocess surviving its isolated native project window."""
import argparse,json,sys,time
from pathlib import Path
import psutil
from windows_session import session
def main(a):
    index=None
    with session(a.executable,a.results) as (page,process,project,errors):
        data=page.evaluate("paths=>request('import','POST',{paths,autoProxy:false})",[str(a.media.resolve())])
        assert not data['errors'],data
        asset=data['assets'][0]
        page.wait_for_function("(async()=>{const j=await request('jobs');return j.readyAudio.length===1})()")
        page.wait_for_timeout(600)
        page.evaluate("id=>{void request('source/frame','POST',{assetId:id,seconds:2,step:0}).catch(()=>{})}",asset['id'])
        deadline=time.monotonic()+5
        while time.monotonic()<deadline and index is None:
            for child in psutil.Process(process.pid).children(recursive=True):
                try:
                    if child.name().lower()=='ffprobe.exe' and '-show_frames' in child.cmdline():index=child;break
                except psutil.Error:pass
            time.sleep(.02)
        assert index is not None,'Source indexing process did not start'
    time.sleep(.05)
    survived=index.is_running()
    result={'index_started':True,'survived_native_host_exit':survived}
    if survived:
        index.terminate()
        try:index.wait(timeout=5)
        except psutil.TimeoutExpired:index.kill();index.wait()
        result['diagnostic_orphan_cleaned']=True
    (a.results/'index-shutdown.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)
    if a.require_clean:assert not survived,result
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('executable',type=Path);p.add_argument('media',type=Path);p.add_argument('results',type=Path);p.add_argument('--require-clean',action='store_true');main(p.parse_args())
