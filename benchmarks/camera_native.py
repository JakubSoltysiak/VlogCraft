"""Local-only real-media checks. Only whitelisted numeric results may be published."""
from pathlib import Path
import bisect,json,os,subprocess,sys,time
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'benchmarks')]
from engine_profile import scene
import native_plan,server
import argparse
parser=argparse.ArgumentParser();parser.add_argument('private_manifest',type=Path);parser.add_argument('results',type=Path)
options=parser.parse_args();root=options.results.resolve();root.mkdir(parents=True,exist_ok=True);sources=json.loads(options.private_manifest.read_text())
if any(root.is_relative_to(Path(row['path']).resolve().parent) for row in sources):raise ValueError('Results must stay outside the original media directory')
reference=options.private_manifest.resolve().parent
sdk=ROOT/'build/tools/architecture/ffmpeg-shared/ffmpeg-9.0.2-full_build-shared/bin'
env=dict(os.environ,PATH=str(sdk)+os.pathsep+os.environ['PATH'])
results=[]
def launch(plan,folder,frames=180,capture=False,software=False):
 folder.mkdir(parents=True,exist_ok=True);file=folder/'sequence.plan';file.write_text(plan['text'])
 cmd=[str(ROOT/'build/tools/architecture/VlogCraftNative.exe'),'--plan',str(file),'--offscreen','--frames',str(frames)]
 if capture:cmd+=['--capture',str(folder/'picture')]
 if software:cmd+=['--software']
 began=time.perf_counter();p=subprocess.run(cmd,env=env,capture_output=True,timeout=90)
 (folder/'raw.log').write_bytes(p.stdout+p.stderr)
 if p.returncode:raise RuntimeError('Native camera run failed; private diagnostics retained')
 data=json.loads(p.stdout.decode().splitlines()[-1]);data['process_seconds']=time.perf_counter()-began
 assert data['completed_frames']==frames
 return data
for row in sources:
 folder=root/'native'/row['alias'];state=scene([Path(row['path'])],3,3840,1);plan=native_plan.compile_plan(state,960)
 fast=launch(plan,folder/'throughput')
 item={'alias':row['alias'],'native_180':{k:v for k,v in fast.items() if k!='selected'},'hdr10plus_retained_at_decode':any(x.get('hdr10plus_retained') for x in fast['selected'])}
 pts=json.loads((reference/'baseline'/row['alias']/'pts.json').read_text())['frames'];stamps=[int(f['best_effort_timestamp']) for f in pts]
 seeks=[]
 for at in (0,1.1,3.217):
  s=scene([Path(row['path'])],1,3840,1);c=s['tracks'][0]['clips'][0];c.update(start=at,end=at+1)
  data=launch(native_plan.compile_plan(s,960),folder/('seek-'+str(at)),1)
  got=data['selected'][0];expected=stamps[max(0,bisect.bisect_right(stamps,got['target_tick'])-1)]
  seeks.append({'target_seconds':at,'process_seconds':data['process_seconds'],'pts_matches_reference':got['pts']==expected})
  assert got['pts']==expected,'Native seek did not select the held presentation interval'
 item['seeks']=seeks
 # Private float readback, never displayed or uploaded.
 captured=launch(plan,folder/'capture',1,True)
 values=np.fromfile(folder/'capture/picture-0.rgba16f',np.float16).reshape(540,960,4)
 item['float_readback']={'finite':bool(np.isfinite(values).all()),'rgb_max':float(values[:,:,:3].max()),'rgb_min':float(values[:,:,:3].min()),'hdr_linear_output':plan['hdr']}
 assert item['float_readback']['finite']
 results.append(item);(root/'native-safe.json').write_text(json.dumps(results,indent=2))
 print(json.dumps({'alias':row['alias'],'native_complete':True,'pts_seek_checks':len(seeks)}),flush=True)
