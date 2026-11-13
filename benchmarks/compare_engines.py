"""Comparable video-only workloads. This does not qualify full-editor replacements."""
import argparse,hashlib,json,os,re,statistics,subprocess,sys,threading,time,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tests'))
from performance import Resources
from common_video import command

def run(command,cwd,env,log):
    started=time.perf_counter();first=None;lines=[]
    with tempfile.TemporaryFile() as stdout,subprocess.Popen(command,cwd=cwd,env=env,stdout=stdout,stderr=subprocess.PIPE) as p:
        meter=Resources(p.pid,gpu=True)
        def read():
            nonlocal first
            for line in p.stderr:
                lines.append(line)
                if first is None and re.search(rb'\bn:\s*0\s',line):first=time.perf_counter()-started
        thread=threading.Thread(target=read);thread.start()
        try:
            code=p.wait(timeout=180)
            stdout.seek(0);out=stdout.read()
        finally:
            if p.poll() is None:p.kill();p.wait()
            thread.join();resources=meter.finish()
    elapsed=time.perf_counter()-started;err=b''.join(lines)
    log.write_bytes(err+out)
    if code:raise RuntimeError(err[-1600:].decode(errors='replace')+out[-1600:].decode(errors='replace'))
    return out,{'wall_seconds':elapsed,'first_output_frame_seconds':first,'resources':resources}

def main(args):
    tools=(ROOT/'build/tools/architecture').resolve();folder=args.media.resolve();results=args.results.resolve();results.mkdir(parents=True,exist_ok=True)
    sdk=tools/'ffmpeg-shared/ffmpeg-9.0.2-full_build-shared/bin'
    env=dict(os.environ,PATH=str(sdk)+os.pathsep+os.environ['PATH'])
    provenance={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [ROOT/'experiments/native_d3d11/main.cpp',ROOT/'experiments/native_d3d11/presentation.h',tools/'native_d3d11.exe',ROOT/'experiments/mlt/direct.py',ROOT/'benchmarks/common_video.py']}
    records=[]
    for width in args.width:
        frames=args.frames if width<=1920 else min(args.frames,60)
        for layers in (1,3):
            inputs=[folder/f'h264-4k60-{n}.mp4' for n in range(layers)]
            for engine in args.engine:
                rows=[]
                for repeat in range(args.repeat):
                    dest=results/f'{engine}-{width}-{layers}-{repeat}';dest.mkdir(exist_ok=True)
                    if engine=='ffmpeg':
                        cmd=command(inputs,width,width*9//16,frames);cwd=ROOT;environment=os.environ.copy()
                    elif engine=='mlt':
                        cmd=[str(ROOT/'.venv/Scripts/python.exe'),str(ROOT/'experiments/mlt/direct.py'),str(tools/'shotcut/Shotcut'),str(dest),*[str(p) for p in inputs],'--width',str(width),'--frames',str(frames)]
                        cwd=ROOT;environment=os.environ.copy()
                    else:
                        cmd=[str(tools/'native_d3d11.exe'),'--mode',engine,'--width',str(width),'--height',str(width*9//16),'--frames',str(frames),*[str(p) for p in inputs]]
                        cwd=ROOT;environment=env
                    out,row=run(cmd,cwd,environment,dest/'process.log')
                    if engine=='ffmpeg':
                        text=(dest/'process.log').read_text(errors='replace')
                        actual=[int(n) for n in re.findall(r'\bn:\s*(\d+)\s',text)]
                        assert actual and actual[-1]+1==frames,actual[-3:]
                        row.update(frames=frames,composited_fps=frames/row['wall_seconds'])
                    elif engine=='mlt':row.update(json.loads((dest/'direct.json').read_text()))
                    else:row.update(json.loads(out.decode().strip().splitlines()[-1]));assert row['frames']==frames,row
                    rows.append(row);print(json.dumps({'engine':engine,'width':width,'layers':layers,'repeat':repeat,'data':row}),flush=True)
                record={'engine':engine,'width':width,'height':width*9//16,'layers':layers,'frames':frames,'audio':False,'presented':False,
                        'runs':rows,'median_full_wall_fps':statistics.median(frames/r['wall_seconds'] for r in rows),
                        'min_full_wall_fps':min(frames/r['wall_seconds'] for r in rows),'max_full_wall_fps':max(frames/r['wall_seconds'] for r in rows)}
                records.append(record)
                (results/'comparison.json').write_text(json.dumps({'workload':'BT709 static scale/position/opacity, full 4K decode, no audio, no presentation','sha256':provenance,'records':records},indent=2))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('media',type=Path);p.add_argument('results',type=Path)
    p.add_argument('--width',type=int,nargs='+',default=[960,3840]);p.add_argument('--frames',type=int,default=180);p.add_argument('--repeat',type=int,default=3)
    p.add_argument('--engine',nargs='+',choices=['ffmpeg','mlt','hardware','download','software'],default=['ffmpeg','mlt','hardware','download','software'])
    main(p.parse_args())
