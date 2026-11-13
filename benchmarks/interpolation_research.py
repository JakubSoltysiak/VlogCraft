"""Isolated CPU motion-interpolation research, generated SDR only; never product/export."""
import argparse,json,subprocess,time
from pathlib import Path
def run(cmd):
 start=time.perf_counter();p=subprocess.run(cmd,capture_output=True,timeout=120)
 if p.returncode:raise RuntimeError('Isolated generated interpolation trial failed')
 return time.perf_counter()-start
def main(a):
 a.results.mkdir(parents=True,exist_ok=True);source=a.results/'moving30.mkv'
 run(['ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc2=s=640x360:r=30:d=2','-c:v','ffv1','-threads','2',str(source)])
 results=[]
 for name,filter in [('repeat','fps=60'),('motion_compensated','minterpolate=fps=60:mi_mode=mci:mc_mode=aobmc:me_mode=bidir')]:
  output=a.results/(name+'.mkv')
  elapsed=run(['ffmpeg','-v','error','-y','-threads','2','-i',str(source),'-vf',filter,'-c:v','ffv1','-threads','2',str(output)])
  info=json.loads(subprocess.check_output(['ffprobe','-v','error','-count_frames','-show_entries','stream=nb_read_frames','-of','json',str(output)]))
  frames=int(info['streams'][0]['nb_read_frames']);assert frames>0
  # Decode the result, rather than relying only on metadata.
  run(['ffmpeg','-v','error','-i',str(output),'-f','null','-'])
  results.append({'mode':name,'seconds':elapsed,'decoded_frames':frames,'process_fps':frames/elapsed})
 report={'resolution':[640,360],'input_rate':'30/1','output_rate':'60/1','trials':results,'adopted':False,
  'reason':'CPU-only batch prototype; future-frame lookahead/end truncation and motion-artifact acceptance not qualified. No 4K/GPU/NPU or perceptual-quality claim.'}
 (a.results/'interpolation.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('results',type=Path);main(p.parse_args())
