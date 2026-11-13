"""Isolated, actual-moving-video MLT composition. No editor migration."""
import argparse,json,os,subprocess,time,xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def prop(parent,name,value):ET.SubElement(parent,'property',name=name).text=str(value)
def project(paths,width,height,frames,dest,*,audio=False,rate='60'):
    root=ET.Element('mlt',producer='main');fps=Fraction(rate)
    ET.SubElement(root,'profile',frame_rate_num=str(fps.numerator),frame_rate_den=str(fps.denominator),width=str(width),height=str(height),
                  progressive='1',sample_aspect_num='1',sample_aspect_den='1',display_aspect_num='16',display_aspect_den='9',colorspace='709')
    for n,path in enumerate(paths):
        producer=ET.SubElement(root,'producer',id=f'source{n}',**{'in':'0','out':str(frames-1)})
        prop(producer,'mlt_service','avformat');prop(producer,'resource',path.resolve())
        prop(producer,'eof','pause');prop(producer,'threads',1)
        playlist=ET.SubElement(root,'playlist',id=f'track{n}')
        ET.SubElement(playlist,'entry',producer=f'source{n}',**{'in':'0','out':str(frames-1)})
    tractor=ET.SubElement(root,'tractor',id='main',**{'in':'0','out':str(frames-1)})
    multitrack=ET.SubElement(tractor,'multitrack')
    for n in range(len(paths)):ET.SubElement(multitrack,'track',producer=f'track{n}')
    for n in range(1,len(paths)):
        trans=ET.SubElement(tractor,'transition',**{'in':'0','out':str(frames-1)})
        for k,v in {'mlt_service':'affine','a_track':0,'b_track':n,'distort':1,'fill':1,
                    'rect':f'{width*(.05 if n==1 else .45)} {height*.25} {width*.5} {height*.5} 0.75'}.items():prop(trans,k,v)
        if audio:
            mix=ET.SubElement(tractor,'transition',**{'in':'0','out':str(frames-1)})
            for k,v in {'mlt_service':'mix','a_track':0,'b_track':n,'always_active':1,'sum':1,'start':1}.items():prop(mix,k,v)
    ET.indent(root);ET.ElementTree(root).write(dest,encoding='utf8',xml_declaration=True)

def run(args):
    args.results.mkdir(parents=True,exist_ok=True)
    xml=args.results/'scene.mlt';project(args.media,args.width,args.width*9//16,args.frames,xml,audio=args.audio)
    env=dict(os.environ,MLT_REPOSITORY=str(args.melt.parent/'lib/mlt'),MLT_DATA=str(args.melt.parent/'share/mlt'),
             QT_QPA_PLATFORM='offscreen')
    output=args.results/'output.mkv'
    cmd=[str(args.melt),str(xml),'-progress','-consumer','avformat:'+str(output),
         'vcodec=ffv1','acodec=pcm_s16le','pix_fmt=yuv420p','real_time=-'+str(args.workers),'threads=4','rescale=bilinear','terminate_on_pause=1']
    if args.sink=='null':cmd[cmd.index('avformat:'+str(output))]='avformat:NUL';cmd+=['f=null','vcodec=rawvideo']
    if not args.audio:cmd+=['an=1']
    rows=[]
    for n in range(args.repeat):
        start=time.perf_counter()
        r=subprocess.run(cmd,env=env,cwd=args.melt.parent,capture_output=True,timeout=180)
        elapsed=time.perf_counter()-start
        (args.results/f'run-{n}.log').write_bytes(r.stderr+r.stdout)
        row={'exit':r.returncode,'seconds':elapsed,'requested_frames':args.frames,'requested_fps':args.frames/elapsed}
        if r.returncode:raise RuntimeError((r.stderr+r.stdout)[-2000:])
        if args.sink=='file':
            streams=json.loads(subprocess.check_output(['ffprobe','-v','error','-count_frames','-show_streams','-of','json',str(output)]))['streams']
            video=next(s for s in streams if s['codec_type']=='video')
            assert int(video['nb_read_frames'])==args.frames,video
            row.update(decoded_frames=int(video['nb_read_frames']),bytes=output.stat().st_size)
        rows.append(row);print(json.dumps(row),flush=True)
    (args.results/'mlt.json').write_text(json.dumps({'sink':args.sink,'width':args.width,'layers':len(args.media),'audio':args.audio,'runs':rows},indent=2))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('melt',type=Path);p.add_argument('results',type=Path);p.add_argument('media',type=Path,nargs='+')
    p.add_argument('--width',type=int,default=960);p.add_argument('--frames',type=int,default=180);p.add_argument('--repeat',type=int,default=3)
    p.add_argument('--workers',type=int,default=1)
    p.add_argument('--sink',choices=['null','file'],default='file');p.add_argument('--audio',action='store_true')
    a=p.parse_args();a.melt=a.melt.resolve();a.results=a.results.resolve();a.media=[p.resolve() for p in a.media];run(a)
