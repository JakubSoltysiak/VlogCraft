"""Reproducible stage timing of the production renderer; generated inputs only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import statistics
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
import render_engine as engine
import server
from performance import Resources


def asset(path,n=0):
    return dict(id=f'{n+1:032x}',kind='video',name=path.name,path=str(path.resolve()),
                size=path.stat().st_size,**server.probe(path))


def scene(paths,seconds=3,width=3840,layers=1,effects=False):
    s=server.default_state();s['assets']=[asset(p,n) for n,p in enumerate(paths)]
    s['tracks']=[];s['output'].update(width=width,height=width*9//16,fps=60,bitrate=35,preset='veryfast',encoder='libx264')
    for n in range(layers):
        a=s['assets'][n%len(paths)];c=server.default_clip(a)
        c.update(end=seconds,volume=.25)
        if n:
            c.update(scale=.5,x=(-.2 if n==1 else .2),opacity=.75)
        if effects:
            c['keys']={'rotation':[{'time':0,'value':-5,'mode':'linear'},{'time':seconds,'value':5,'mode':'linear'}]}
            c['look']={'master':[0,.2,.5,.8,1]}
        t=server.make_track('video',n+1);t['clips']=[c];s['tracks'].insert(0,t)
    return s


class Runner:
    def __init__(self):self.stages=[]
    def __call__(self,command,cwd):
        command=list(command)
        if '-loglevel' in command:command[command.index('-loglevel')+1]='info'
        command[1:1]=['-benchmark','-nostats']
        start=time.perf_counter()
        r=subprocess.run(command,cwd=cwd,capture_output=True,text=True,timeout=180)
        elapsed=time.perf_counter()-start
        row={'output':Path(command[-1]).name,'seconds':round(elapsed,6),'exit':r.returncode}
        m=re.search(r'utime=([\d.]+)s stime=([\d.]+)s rtime=([\d.]+)s',r.stderr)
        if m:row.update(ffmpeg_user_s=float(m[1]),ffmpeg_system_s=float(m[2]),ffmpeg_runtime_s=float(m[3]))
        m=re.search(r'maxrss=(\d+)KiB',r.stderr)
        if m:row['ffmpeg_peak_rss_MiB']=round(int(m[1])/1024,2)
        if Path(command[-1]).is_file():row['bytes']=Path(command[-1]).stat().st_size
        self.stages.append(row)
        if r.returncode:raise RuntimeError(r.stderr[-3000:])


def main(args):
    results=args.results.resolve();results.mkdir(parents=True,exist_ok=True)
    paths=[p.resolve() for p in args.media]
    s=scene(paths,args.seconds,args.width,args.layers,args.effects)
    if args.quality=='preview':s['output']['bitrate']=0
    s['output']['encoder']=args.encoder
    rows=[]
    for n in range(args.repeat):
        work=results/f'run-{n}';work.mkdir(exist_ok=True)
        target=work/'output.mp4';runner=Runner()
        meter=Resources(os.getpid(),gpu=args.gpu)
        begin=time.perf_counter()
        if args.quality=='export':engine.render(s,target,work,popen=runner)
        else:engine.render_range(s,0,args.seconds,target,work,'preview',runner)
        elapsed=time.perf_counter()-begin
        resources=meter.finish()
        meta=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(target)]))
        v=next(x for x in meta['streams'] if x['codec_type']=='video')
        assert int(v['nb_frames'])==round(args.seconds*60),(v,args.seconds)
        subprocess.run(['ffmpeg','-v','error','-i',str(target),'-f','null','-'],capture_output=True,check=True,timeout=120)
        row={'seconds':round(elapsed,6),'frames':int(v['nb_frames']),'fps':round(int(v['nb_frames'])/elapsed,3),
             'file_bytes':target.stat().st_size,'stages':runner.stages,'resources':resources,'decoded':True}
        rows.append(row);print(json.dumps(row),flush=True)
    data={'revision':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
          'fixture':{'inputs':[{'name':p.name,'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),
                              'metadata':{k:v for k,v in a.items() if k not in ('path','id')}} for p,a in zip(paths,s['assets'])],
                     'timeline_seconds':args.seconds,'width':args.width,'height':args.width*9//16,'layers':args.layers,'effects':args.effects,
                     'quality':args.quality,'encoder':args.encoder},
          'runs':rows,'median_seconds':statistics.median(x['seconds'] for x in rows),
          'min_seconds':min(x['seconds'] for x in rows),'max_seconds':max(x['seconds'] for x in rows)}
    (results/'profile.json').write_text(json.dumps(data,indent=2))
    print(json.dumps({k:v for k,v in data.items() if k not in ('fixture','runs')}),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('results',type=Path);p.add_argument('media',type=Path,nargs='+')
    p.add_argument('--seconds',type=float,default=3);p.add_argument('--width',type=int,default=3840)
    p.add_argument('--layers',type=int,default=1);p.add_argument('--repeat',type=int,default=3)
    p.add_argument('--quality',choices=['export','preview'],default='export')
    p.add_argument('--encoder',default='libx264');p.add_argument('--effects',action='store_true');p.add_argument('--gpu',action='store_true')
    main(p.parse_args())
