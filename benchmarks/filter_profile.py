"""Ablation of real decode/scale/RGB/overlay/effect work without output encoding."""
import argparse,json,statistics,subprocess,time,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from engine_profile import Runner
import grading
def main(a):
 a.results.mkdir(parents=True,exist_ok=True);rows={}
 base=f'scale={a.width}:{a.width*9//16}:flags=bilinear'
 variants={'decode':'null','scale':base,'rgba':base+',format=rgba',
           'rotation':base+',format=rgba,rotate=.1:ow=ceil(hypot(iw\\,ih)/2)*2:oh=ceil(hypot(iw\\,ih)/2)*2:c=none',
           'mask':base+",format=rgba,geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='alpha(X,Y)*clip((1-sqrt(pow((X/W-.5)/.5,2)+pow((Y/H-.5)/.5,2)))/.1,0,1)':i=nearest"}
 cube=grading.filter_for({'look':{'master':[0,.2,.5,.8,1]}},{},a.results.resolve())
 variants.update(lut=base+cube,opacity=base+',format=rgba,colorchannelmixer=aa=.5',
                 chroma=base+',format=rgba,colorkey=0x00ff00:.16:.08',
                 color=base+",eq=brightness='0.04*sin(t)':contrast=1.1:saturation=1.1:eval=frame")
 for label,filters in variants.items():
  if a.variant and label not in a.variant:continue
  values=[]
  for n in range(a.repeat):
   runner=Runner();cmd=['ffmpeg','-nostdin','-loglevel','error','-filter_threads','1','-threads','1','-an','-i',str(a.source.resolve()),
      '-vf',filters,'-frames:v',str(a.frames),'-an','-c:v','wrapped_avframe','-f','null','-']
   runner(cmd,str(a.results.resolve()));values.append(runner.stages[0])
  rows[label]={'runs':values,'median_seconds':statistics.median(r['seconds'] for r in values)}
  print(label,rows[label]['median_seconds'],flush=True)
 (a.results/'filters.json').write_text(json.dumps({'width':a.width,'frames':a.frames,'repeat':a.repeat,'variants':rows},indent=2))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('results',type=Path);p.add_argument('--variant',nargs='+');p.add_argument('--width',type=int,default=960);p.add_argument('--frames',type=int,default=120);p.add_argument('--repeat',type=int,default=3);main(p.parse_args())
