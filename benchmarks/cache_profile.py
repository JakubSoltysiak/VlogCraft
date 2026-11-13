"""Compare whole-project and range dependency caching on the same compositor."""
from copy import deepcopy
import importlib.util,json,subprocess,sys,tempfile,time,types
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'benchmarks')]
from engine_profile import scene
from preview_cache import PreviewCache
def complete(cache,job):
 end=time.monotonic()+120
 while cache.status(job['id'])['status'] in ('queued','rendering') and time.monotonic()<end:time.sleep(.01)
 assert cache.status(job['id'])['status']=='ready',cache.status(job['id'])
 return cache.path(job['id'])
def main():
 root=ROOT/'build/qa/architecture';results=root/'cache-comparison';results.mkdir(parents=True,exist_ok=True)
 paths=[root/'media'/f'h264-4k60-{i}.mp4' for i in range(3)]
 s=scene(paths,seconds=6,width=3840,layers=3)
 import server
 title=server.default_title(16);title.update(end=2,text='Far caption')
 s['tracks'].insert(0,server.make_track('video',4));s['tracks'][0]['clips']=[title]
 historical=types.ModuleType('historical_cache')
 exec(subprocess.check_output(['git','show','studio-3.4-development:preview_cache.py']).decode('utf8'),historical.__dict__)
 records=[]
 for label,cls in [('3.4.4 whole-project',historical.PreviewCache),('range dependencies',PreviewCache)]:
  with tempfile.TemporaryDirectory(dir=results) as folder:
   cache=cls(folder);state=deepcopy(s)
   try:
    row={'engine':label};start=time.perf_counter();first=cache.prepare(state,0,960);p=complete(cache,first);row['initial_prepare_seconds']=time.perf_counter()-start
    prior=p.read_bytes();state['tracks'][0]['clips'][0]['text']='Changed caption at sixteen seconds'
    start=time.perf_counter();second=cache.prepare(state,0,960);p=complete(cache,second);row['unrelated_edit_seconds']=time.perf_counter()-start
    row.update(same_range_id=first['id']==second['id'],same_bytes=prior==p.read_bytes(),cache_metrics=cache.metrics() if hasattr(cache,'metrics') else None)
    assert row['same_bytes'],'Unrelated title edit changed visible frames'
    records.append(row);print(json.dumps(row),flush=True)
   finally:cache.close()
 (results/'cache.json').write_text(json.dumps(records,indent=2))
if __name__=='__main__':main()
