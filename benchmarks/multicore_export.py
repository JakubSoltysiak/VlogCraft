"""Alternate bounded FFmpeg worker configurations without changing output quality options."""
import argparse,json,os,re,statistics,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from engine_profile import scene,Runner
import render_engine as engine
class Workers(Runner):
 def __init__(self,decode,filters,encode):super().__init__();self.budget=(decode,filters,encode)
 def __call__(self,command,cwd):
  command=list(command)
  if '-c:v' in command:
   last_input=max(i for i,x in enumerate(command) if x=='-i')
   for i,x in enumerate(command[:-1]):
    if x=='-threads':command[i+1]=str(self.budget[0] if i<last_input else self.budget[2])
    if x=='-filter_complex_threads':command[i+1]=str(self.budget[1])
  return super().__call__(command,cwd)
def main(a):
 a.results=a.results.resolve();a.media=a.media.resolve()
 a.results.mkdir(parents=True,exist_ok=True);rows=[]
 paths=[a.media/f'h264-4k60-{n}.mp4' for n in range(3)]
 s=scene(paths,3,3840,a.layers,a.effects)
 configs=[(1,1,4),(1,1,8),(2,1,4),(1,2,4)]
 baseline=None;baseline_source_quality=None
 for repeat in range(3):
  for config in (configs if repeat%2==0 else configs[::-1]):
   folder=a.results/f'repeat-{repeat}-workers-{"-".join(map(str,config))}';folder.mkdir()
   runner=Workers(*config);target=folder/'output.mp4';began=time.perf_counter()
   engine.render(s,target,folder,popen=runner);elapsed=time.perf_counter()-began
   meta=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(target)]))
   v=next(x for x in meta['streams'] if x['codec_type']=='video');assert int(v['nb_frames'])==180 and v['r_frame_rate']=='60/1'
   subprocess.run(['ffmpeg','-v','error','-i',str(target),'-f','null','-'],capture_output=True,check=True,timeout=90)
   if baseline is None:baseline=target
   quality=subprocess.run(['ffmpeg','-v','info','-i',str(baseline),'-i',str(target),'-lavfi','ssim','-f','null','-'],capture_output=True,text=True,timeout=90)
   assert quality.returncode==0
   match=re.findall(r'All:([0-9.]+)',quality.stderr);assert match
   similarity=float(match[-1]);assert similarity>.99,similarity
   source_quality=None
   if a.layers==1 and not a.effects:
    q=subprocess.run(['ffmpeg','-v','info','-i',str(paths[0]),'-i',str(target),'-lavfi','ssim=shortest=1','-an','-f','null','-'],capture_output=True,text=True,timeout=90)
    assert q.returncode==0;source_quality=float(re.findall(r'All:([0-9.]+)',q.stderr)[-1])
    if baseline_source_quality is None:baseline_source_quality=source_quality
    assert source_quality>=baseline_source_quality-.0005,(source_quality,baseline_source_quality)
   row={'SSIM_vs_source':source_quality,'repeat':repeat,'workers':list(config),'seconds':elapsed,'frames':180,'fps':180/elapsed,'decoded':True,'SSIM_vs_first_baseline':similarity,'stages':runner.stages}
   rows.append(row);(a.results/'workers.json').write_text(json.dumps({'layers':a.layers,'effects':a.effects,'quality_options_unchanged':True,'rows':rows},indent=2),encoding='utf8')
   print(json.dumps(row),flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('media',type=Path);p.add_argument('results',type=Path);p.add_argument('--layers',type=int,default=1);p.add_argument('--effects',action='store_true');main(p.parse_args())
