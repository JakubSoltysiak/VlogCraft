"""Native cache/cut PTS integration; exact decoded pictures, no source interpolation."""
import json,os,subprocess,sys,tempfile,time,threading,queue,argparse
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'benchmarks')]
import native_plan
from engine_profile import scene
def main(a):
 a.results.mkdir(parents=True,exist_ok=True)
 s=scene([a.media/f'h264-4k60-{i}.mp4' for i in range(3)],1.5,960,3)
 import copy
 for track in s['tracks']:
  c=copy.deepcopy(track['clips'][0]);c['id']='cut'+c['id'];c['position']=1.5;track['clips'].append(c)
 plan=a.results/'sequence.plan';plan.write_text(native_plan.compile_plan(s)['text'])
 sdk=ROOT/'build/tools/architecture/ffmpeg-shared/ffmpeg-9.0.2-full_build-shared/bin'
 p=subprocess.Popen([str(ROOT/'build/tools/architecture/VlogCraftNative.exe'),'--plan',str(plan),'--offscreen'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=dict(os.environ,PATH=str(sdk)+os.pathsep+os.environ['PATH']))
 q=queue.Queue()
 def read():
  for line in p.stdout:
   try:q.put(json.loads(line))
   except ValueError:pass
 t=threading.Thread(target=read,daemon=True);t.start();checks=[]
 try:
  for frame,expected in ((0,0),(90,0),(91,256),(93,768)):
   p.stdin.write(f'CLOCK {round(frame/60*1000000)} 0 1\n');p.stdin.flush()
   deadline=time.monotonic()+15
   while True:
    d=q.get(timeout=max(.1,deadline-time.monotonic()))
    if d.get('event')=='error':raise RuntimeError('Native cache trial failed')
    if d.get('completed_sequence_frame')==frame:
     assert len(d['selected'])==3 and all(x['pts']==expected for x in d['selected']),d
     checks.append({'sequence_frame':frame,'all_source_pts':expected});break
   time.sleep(.05)
  assert sum(x['warm_cache_hits'] for x in d['decoder_statistics'])>0,d
  report={'checks':checks,'cache_hits':sum(x['warm_cache_hits'] for x in d['decoder_statistics']),'cache_frames_per_source':[x['warm_cache_frames'] for x in d['decoder_statistics']]}
  assert max(report['cache_frames_per_source'])<=6
  (a.results/'cache.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
 finally:
  p.stdin.write('CLOSE\n');p.stdin.flush();p.wait(timeout=10);t.join(timeout=2)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('media',type=Path);p.add_argument('results',type=Path);main(p.parse_args())
