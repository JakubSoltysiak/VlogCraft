"""Generated mixed-media HDR10+ qualification. Raw media and reports stay local."""
import argparse
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
from xml.etree import ElementTree

import psutil
from PIL import Image, ImageDraw

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
import hdr10plus_master
from hdr10plus_index import SIDE_DATA
import render_engine
import server
from test_hdr_color import project
from test_timeline_transitions import settings


def ff(*args):
    return subprocess.run(args,capture_output=True,check=True,timeout=120,
                          creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)).stdout


def camera(folder,index,size,duration):
    name=folder/f'generated-pq-{index}.mp4'
    shade=('0x555555','0x999999')[index]
    ff('ffmpeg','-v','error','-y','-f','lavfi','-i',f'color=c={shade}:s={size}:r=60:d={duration}',
       '-f','lavfi','-i',f'sine=f={440+index*170}:r=48000:d={duration}',
       '-vf','drawbox=x=32:y=28:w=96:h=88:color=white:t=fill,setsar=1,'
             'setparams=range=limited:color_primaries=bt2020:color_trc=smpte2084:colorspace=bt2020nc',
       '-c:v','libx265','-preset','ultrafast','-pix_fmt','yuv420p10le','-x265-params','pools=2:frame-threads=1',
       '-c:a','aac',str(name))
    return name


def state_for(folder,canvas,source_canvas,count,spatial_motion,*,video_inputs=None):
    w,h=canvas
    block=count//3; duration=block/60
    photos=[folder/'photograph.jpg',folder/'overlay.png']
    image=Image.new('RGB',(640,360),'#b4b4b4')
    ImageDraw.Draw(image).rectangle((90,75,260,210),fill='#5a5a5a')
    image.save(photos[0],quality=96)
    image=Image.new('RGBA',(320,180),(0,0,0,0))
    ImageDraw.Draw(image).rectangle((45,16,115,68),fill=(255,255,255,92))
    image.save(photos[1])
    inputs=(list(video_inputs) if video_inputs else
            [camera(folder,n,source_canvas,2*duration+.3) for n in range(2)])+photos
    music=folder/'background.wav'
    ff('ffmpeg','-v','error','-y','-f','lavfi','-i',f'sine=f=180:r=48000:d={count/60}',str(music))
    inputs.append(music)
    assets=[dict(id=f'asset-{n}',kind='video' if n<2 else 'image' if n<4 else 'audio',
                 path=str(p),name=p.name,**server.probe(p)) for n,p in enumerate(inputs)]
    state=project(assets[:1],w,h)
    state['assets']=assets
    state['output'].update(fps=60,preset='ultrafast')
    first=state['tracks'][0]['clips'][0]
    first.update(end=duration,hdrExposure=.2)
    second=server.default_clip(assets[1],duration)
    frames=max(4,block//3)
    second.update(start=.15,end=.15+duration,transitionIn=settings(first,frames,audio='linear'))
    still=server.default_clip(assets[2],2*duration)
    property_name='scale' if spatial_motion else 'opacity'
    still.update(end=duration,transitionIn=settings(second,frames),keys={property_name:[
        {'time':0,'value':1,'mode':'linear'},
        {'time':duration,'value':1.1 if spatial_motion else .85,'mode':'linear'}]})
    state['tracks'][0]['clips']=[first,second,still]
    top=server.default_clip(assets[3],2*duration)
    top.update(end=duration,opacity=.6)
    title=server.default_title(2*duration)
    title.update(end=duration,fadeIn=duration*.8,fadeOut=0,text='TRAVEL',fontScale=.07)
    sound=server.default_clip(assets[4])
    sound.update(end=count/60,volume=.2)
    state['tracks'].insert(0,{'id':'overlays','name':'Overlays','type':'video','clips':[top,title]})
    state['tracks'].append({'id':'music','name':'Music','type':'audio','clips':[sound]})
    return state,inputs


@contextmanager
def resources(folder):
    stats={'process_tree_peak_rss_bytes':0,'scratch_peak_bytes':0,'observed_child_cpu_seconds':0}
    cpu={}
    done=threading.Event()
    parent=psutil.Process()
    own_cpu=sum(parent.cpu_times()[:2])

    def measure():
        while not done.is_set():
            total=parent.memory_info().rss
            for child in parent.children(recursive=True):
                try:
                    total+=child.memory_info().rss
                    cpu[child.pid]=sum(child.cpu_times()[:2])
                except psutil.Error:
                    continue
            stats['process_tree_peak_rss_bytes']=max(total,stats['process_tree_peak_rss_bytes'])
            disk=0
            for p in folder.glob('*/*'):
                if p.is_file():
                    try:disk+=p.stat().st_size
                    except FileNotFoundError:pass
            stats['scratch_peak_bytes']=max(disk,stats['scratch_peak_bytes'])
            done.wait(.2)

    worker=threading.Thread(target=measure)
    worker.start()
    try:yield stats
    finally:
        done.set();worker.join()
        stats['observed_child_cpu_seconds']=round(sum(cpu.values())+sum(parent.cpu_times()[:2])-own_cpu,3)


def hashes(path):
    return ff('ffmpeg','-v','error','-threads','4','-i',str(path),'-map','0:v','-map','0:a',
              '-fps_mode','passthrough','-c:v','rawvideo','-threads:v','1','-f','framemd5','-')


def main(folder,size,source_size,count,spatial_motion=True):
    folder=folder.resolve()
    folder.mkdir(parents=True,exist_ok=False)
    w,h=map(int,size.split('x'))
    state,inputs=state_for(folder,(w,h),source_size,count,spatial_motion)
    static,master=folder/'static.mp4',folder/'master.mp4'
    work=folder/'author'
    work.mkdir()
    before=[hashlib.sha256(path.read_bytes()).digest() for path in inputs]
    notes={}
    report={'canvas':[w,h],'input_video_size':source_size,'video_sources':2,'frames':count,'fps':60,
            'audio_rate':48000,'audio_sources':3,'visual_clips':5,'two_dissolves':True,
            'photograph_spatial_motion':spatial_motion,
            'embedded_camera_crossfade':'linear','encoder':'libx265 Main 10',
            'source_commit':ff('git','rev-parse','HEAD').decode().strip()}
    with resources(folder) as stats:
        began=time.monotonic()
        render_engine.render(state,static,folder/'render',on_progress=lambda p,text:print(p,text,flush=True))
        rendered=time.monotonic()
        report['static_seconds']=rendered-began

        def stage(text,_):
            notes[text]=time.monotonic()-rendered
            print(text,flush=True)

        (folder/'partial-result.json').write_text(json.dumps(report),encoding='utf-8')
        assert hdr10plus_master.author(static,master,work,60,count,render_engine._run,stage,lambda:False)==count
        report.update(author_seconds=time.monotonic()-rendered,
                      edited_total_seconds=time.monotonic()-began,authoring_stages=notes)
    report.update(stats)
    report['effective_output_fps']=count/report['edited_total_seconds']
    info=json.loads(ff('ffprobe','-v','error','-show_streams','-of','json',str(master)))
    video,audio=info['streams']
    assert (video['width'],video['height'],video['avg_frame_rate'],video['pix_fmt'],video['color_transfer'])==(
        w,h,'60/1','yuv420p10le','smpte2084')
    assert int(video['duration_ts'])*60==count*120000
    assert int(audio['duration_ts'])*60==count*48000
    assert hashes(static)==hashes(master)
    xml=ElementTree.fromstring(ff('ffprobe','-v','error','-select_streams','v:0','-show_frames','-of','xml',str(master)))
    decoded=xml.findall('./frames/frame')
    assert len(decoded)==count
    means=set()
    for frame in decoded:
        [side]=frame.findall(f"./side_data_list/side_data[@type='{SIDE_DATA}']")
        value=next(field.get('value') for field in side.findall('side_datum') if field.get('key')=='average_maxrgb')
        means.add(value)
    assert len(means)>5 and before==[hashlib.sha256(path.read_bytes()).digest() for path in inputs]
    report.update(independent_decoded_picture_pcm_equality=True,all_frames_have_metadata=True,
                  distinct_metadata_average_values=len(means),audio_endpoint_samples=int(audio['duration_ts']),
                  source_hashes_match=True)
    (folder/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('results',type=Path)
    parser.add_argument('--size',default='1280x720')
    parser.add_argument('--source-size',default='1280x720')
    parser.add_argument('--frames',type=int,default=120)
    parser.add_argument('--opacity-motion',action='store_true',help='Use photo opacity animation as a separate control')
    args=parser.parse_args()
    if args.frames<24 or args.frames%3:parser.error('Use at least 24 frames, divisible by three')
    main(args.results,args.size,args.source_size,args.frames,not args.opacity_motion)
