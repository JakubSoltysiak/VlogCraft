"""Hardware-decoder worker experiment; offscreen throughput is not playback qualification."""
import argparse,json,os,statistics,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from engine_profile import scene
import native_plan
def main(a):
 a.results.mkdir(parents=True,exist_ok=True)
 s=scene([a.media/f'h264-4k60-{i}.mp4' for i in range(3)],3,960,3)
 plan=a.results/'sequence.plan';plan.write_text(native_plan.compile_plan(s,960)['text'],encoding='utf8')
 sdk=ROOT/'build/tools/architecture/ffmpeg-shared/ffmpeg-9.0.2-full_build-shared/bin'
 rows=[]
 for repeat in range(3):
  for workers in ((1,2,4) if repeat%2==0 else (4,2,1)):
   env=dict(os.environ,PATH=str(sdk)+os.pathsep+os.environ['PATH'],VLOGCRAFT_NATIVE_DECODE_THREADS=str(workers))
   began=time.perf_counter()
   p=subprocess.run([str(ROOT/'build/tools/architecture/VlogCraftNative.exe'),'--plan',str(plan),'--offscreen','--frames','180'],env=env,capture_output=True,timeout=90)
   (a.results/f'workers-{workers}-repeat-{repeat}.log').write_bytes(p.stdout+p.stderr)
   assert p.returncode==0,'Native worker experiment failed; local raw log retained'
   d=json.loads(p.stdout.decode().splitlines()[-1]);elapsed=time.perf_counter()-began
   assert d['completed_frames']==180 and d['completed_sequence_frame']==179
   assert all(x['pts']==x['target_tick'] for x in d['selected'])
   row={'workers_requested':workers,'repeat':repeat,'seconds':elapsed,'completed_frames':180,'fps':180/elapsed,
        'threads_active':[r['active_thread_type'] for r in d['decoder_statistics']],
        'threads_configured':[r['decoder_threads'] for r in d['decoder_statistics']],
        'pool_frames':[r['hardware_pool_frames'] for r in d['decoder_statistics']],
        'GPU_ms':d['timings']['composition_gpu'],'context_wait_ms':d['timings']['context_wait']}
   rows.append(row);(a.results/'workers.json').write_text(json.dumps({'diagnostic_only':True,'rows':rows},indent=2),encoding='utf8')
   print(json.dumps(row),flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('media',type=Path);p.add_argument('results',type=Path);main(p.parse_args())
