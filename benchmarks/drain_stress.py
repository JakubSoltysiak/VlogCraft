"""Historical title/video/audio drain-stall fixture; every repetition must decode."""
import argparse,json,subprocess,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import server,render_engine as engine
def main(a):
 rows=[];a.result.parent.mkdir(parents=True,exist_ok=True)
 with tempfile.TemporaryDirectory(prefix='drain-') as folder:
  root=Path(folder);src=root/'source.mp4'
  subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','testsrc2=s=320x180:r=24:d=1.2',
   '-f','lavfi','-i','sine=f=450:r=48000:d=1.2','-c:v','libx264','-preset','ultrafast','-c:a','aac','-shortest',str(src)],capture_output=True,check=True)
  asset=dict(id='a'*32,kind='video',name=src.name,path=str(src),size=src.stat().st_size,**server.probe(src))
  s=server.default_state();s['assets']=[asset];s['output'].update(width=320,height=180,fps=24,crf=27,preset='ultrafast')
  clip=server.default_clip(asset);clip['end']=1;s['tracks'][1]['clips']=[clip]
  title=server.default_title(.12);title.update(end=.4,text='KENYA');s['tracks'][0]['clips']=[title]
  audio=server.default_clip(asset,0,'audio');audio.update(end=1,volume=.2);s['tracks'][2]['clips']=[audio]
  for n in range(a.repeat):
   work=root/str(n);work.mkdir();target=work/'part.mov';start=time.monotonic()
   try:
    engine.render_range(s,.125,.5,target,work,runner=lambda c,w:subprocess.run(c,cwd=w,capture_output=True,check=True,timeout=a.stage_timeout))
    meta=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(target)]))
    assert int(meta['streams'][0]['nb_frames'])==9,meta
    subprocess.run(['ffmpeg','-v','error','-i',str(target),'-f','null','-'],capture_output=True,check=True,timeout=a.stage_timeout)
    rows.append({'seconds':time.monotonic()-start,'frames':9,'decoded':True,'exit':0})
   except Exception as error:
    rows.append({'failed':type(error).__name__});raise
   finally:a.result.write_text(json.dumps({'repetitions':rows},indent=2))
 assert len(rows)==a.repeat and all(row.get('decoded') for row in rows)
 print(json.dumps({'repetitions':len(rows),'decoded':len(rows),'timeouts':0}),flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--repeat',type=int,default=100);p.add_argument('--stage-timeout',type=float,default=3)
 p.add_argument('--result',type=Path,default=ROOT/'build/qa/drain-stress.json')
 a=p.parse_args();assert a.repeat>0;main(a)
