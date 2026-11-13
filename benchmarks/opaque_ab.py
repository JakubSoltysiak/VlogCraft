"""Interleaved control: only toggle the opaque-base optimization, identical encoder settings."""
import argparse,hashlib,json,os,statistics,subprocess,time
from pathlib import Path
import numpy as np
from engine_profile import scene,Runner,Resources,engine
def picture(path,at):
 return np.frombuffer(subprocess.check_output(['ffmpeg','-v','error','-ss',str(at),'-i',str(path),'-frames:v','1',
    '-vf','scale=192:108','-pix_fmt','rgb24','-f','rawvideo','-']),np.uint8).astype(float)
def main(a):
 a.results.mkdir(parents=True,exist_ok=True);state=scene([a.source.resolve()],3,3840,1)
 original=engine._opaque_base
 assert original(engine.active_clips(state,0,3)[0],{x['id']:x for x in state['assets']},0,3,60,3840,2160)
 records=[]
 try:
  for encoder in ('libx264','h264_amf'):
   state['output']['encoder']=encoder;runs=[];examples={}
   for n,enabled in enumerate((False,True,True,False,False,True)):
    engine._opaque_base=original if enabled else lambda *args:False
    work=(a.results/f'{encoder}-{n}').resolve();work.mkdir(exist_ok=True);target=work/'output.mp4';runner=Runner()
    resources=Resources(os.getpid(),gpu=True);start=time.perf_counter();engine.render(state,target,work,popen=runner);elapsed=time.perf_counter()-start
    metrics=resources.finish()
    meta=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(target)]))
    video=next(x for x in meta['streams'] if x['codec_type']=='video')
    assert int(video['nb_frames'])==180 and video['r_frame_rate']=='60/1'
    subprocess.run(['ffmpeg','-v','error','-i',str(target),'-f','null','-'],capture_output=True,check=True,timeout=90)
    row={'opaque_enabled':enabled,'seconds':elapsed,'frames':180,'decoded':True,'bytes':target.stat().st_size,'stages':runner.stages,'resources':metrics}
    runs.append(row);examples.setdefault(enabled,target);print(json.dumps({'encoder':encoder,**row}),flush=True)
   errors=[float(np.abs(picture(examples[False],at)-picture(examples[True],at)).mean()) for at in (0,2.9)]
   before=statistics.median(r['seconds'] for r in runs if not r['opaque_enabled']);after=statistics.median(r['seconds'] for r in runs if r['opaque_enabled'])
   records.append({'encoder':encoder,'runs':runs,'disabled_median_seconds':before,'enabled_median_seconds':after,
                   'disabled_range_seconds':[min(r['seconds'] for r in runs if not r['opaque_enabled']),max(r['seconds'] for r in runs if not r['opaque_enabled'])],
                   'enabled_range_seconds':[min(r['seconds'] for r in runs if r['opaque_enabled']),max(r['seconds'] for r in runs if r['opaque_enabled'])],
                   'wall_time_reduction_percent':100*(1-after/before),'first_last_rgb_mae_at_192x108':errors})
   (a.results/'ab.json').write_text(json.dumps({'method':'interleaved ABBAAB; current renderer, only opaque guard disabled/enabled; original4K60, 3s, 35Mbps veryfast',
       'source_sha256':hashlib.sha256(a.source.read_bytes()).hexdigest(),'records':records},indent=2))
   assert max(errors)<3,errors
 finally:engine._opaque_base=original
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('results',type=Path);main(p.parse_args())
