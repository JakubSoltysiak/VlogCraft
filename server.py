#!/usr/bin/env python3
"""VlogCraft Studio 3 — local-only editing host.

This application binds to 127.0.0.1 and never sends footage to the internet.
Local imports link original media; browser drag-and-drop imports by copying
streamed, bounded-size chunks to the local workspace, even for files >4 GiB.
"""
from __future__ import annotations
import argparse
import hashlib
import collections
import json
import math
import mimetypes
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
import webbrowser
import zipfile
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from concurrent.futures import ThreadPoolExecutor
import project_store
import animation
import encoders
import timeline_proposal
import ai_bridge
import render_engine as engine

ROOT=Path(__file__).resolve().parent
WEB=ROOT/'web'
WORK=Path(os.environ.get('VLOGCRAFT_WORK',ROOT/'workspace'))
PROJECT=Path(os.environ.get('VLOGCRAFT_PROJECT',WORK/'project.json'))
CACHE_WORKERS=ThreadPoolExecutor(max_workers=2,thread_name_prefix='media-cache')
MEDIA=WORK/'media'; THUMBS=WORK/'thumbnails'; PROXIES=WORK/'proxies'; REVIEWS=WORK/'reviews'; EXPORTS=WORK/'exports'
AI_UNDO=WORK/'ai_undo.json'
LOCK=threading.RLock(); UPLOAD_LOCK=threading.RLock(); JOB_LOCK=threading.RLock()
VIDEO={'.mp4','.mov','.mkv','.m4v','.avi','.wmv','.webm','.mpg','.mpeg','.mts','.m2ts'}
IMAGE={'.jpg','.jpeg','.png','.webp','.bmp','.tif','.tiff'}
AUDIO={'.wav','.mp3','.m4a','.aac','.flac','.ogg','.opus','.wma'}
SUPPORTED=VIDEO|IMAGE|AUDIO
MAX_CHUNK=16*1024*1024  # keep resident uploads small; NOT a file size limit
UPLOADS={}
JOBS={'export':{'status':'idle','percent':0,'message':'','path':None,'error':None},'proxy':{'status':'idle','percent':0,'message':'','assetId':None,'error':None}}
DESKTOP_ACTION=None
PROXY_QUEUE=collections.deque()
CURRENT_PROCESS={'export':None,'proxy':None}
CANCEL={'export':threading.Event(),'proxy':threading.Event()}
AI_PREVIEW={'token':None,'digest':None,'created':0}

JOBS['motion']={'status':'idle','percent':0}
CANCEL['motion']=threading.Event()
CURRENT_PROCESS['motion']=None


def motion_source(cid):
    with LOCK:
        clip=next((c for t in STATE['tracks'] for c in t['clips'] if c['id']==cid and c['kind']=='video'),None)
        if clip is None:raise ValueError('Select a video clip')
        asset=next(a for a in STATE['assets'] if a['id']==clip['assetId'])
        return deepcopy(asset),deepcopy(clip)


def clip_length(clip):return engine.clip_length(clip)
def make_track(kind, index):
    return {'id':uuid.uuid4().hex,'name':f'{"V" if kind=="video" else "A"}{index} · '+('Video' if kind=='video' else 'Audio'),
            'type':kind,'muted':False,'hidden':False,'locked':False,'volume':1.0,'clips':[]}

def default_state():
    v2,v1,a2,a1=[make_track(k,i) for k,i in [('video',2),('video',1),('audio',2),('audio',1)]]
    v2['name']='V2 · Overlays';v1['name']='V1 · Main footage';a2['name']='A2 · Music';a1['name']='A1 · Source audio'
    return {'version':3,'name':'KENYA  /  The Journey','assets':[], 'tracks':[v2,v1,a2,a1],
            'output':{'width':3840,'height':2160,'fps':30,'crf':20,'preset':'medium'},
            'updated':int(time.time())}

def default_clip(asset,position=0,kind=None):
    kind=kind or asset['kind']; duration=asset['duration'] if asset['kind']!='image' else 5
    if duration<=0:duration=5
    return {'id':uuid.uuid4().hex,'assetId':asset['id'],'kind':kind,'position':round(position,3),
            'start':0.0,'end':round(duration,3),'speed':1.0,'volume':1.0,'opacity':1.0,'scale':1.0,
            'x':0.0,'y':0.0,'grade':'neutral','fit':'contain','fadeIn':0.0,'fadeOut':0.0,'locked':False}

def default_title(position=0):
    return {'id':uuid.uuid4().hex,'assetId':None,'kind':'title','position':position,'start':0.,'end':4.,
            'speed':1.,'volume':0,'opacity':1,'scale':1,'x':0,'y':0,'grade':'neutral',
            'fit':'contain','fadeIn':.25,'fadeOut':.25,'text':'KENYA','fontScale':.055,'color':'white',
            'titleAlign':'center','locked':False}

def migrate_v2(old):
    state=default_state();state['assets']=old.get('assets',[]);state['name']=old.get('name',state['name'])
    tracks=state['tracks'];master=next(t for t in tracks if t['type']=='video' and t['name'].startswith('V1'))
    pos=0
    for clip in old.get('timeline',[]):
        item=next((a for a in state['assets'] if a['id']==clip.get('assetId')),None)
        if not item:continue
        c=default_clip(item,pos)
        c.update({k:clip[k] for k in ['id','start','end','volume','fit','grade'] if k in clip})
        if clip.get('fade'):c['fadeIn']=c['fadeOut']=.25
        master['clips'].append(c);pos+=clip_length(c)
        if clip.get('caption'):
            title=default_title(c['position']);title['text']=clip['caption'];title['end']=clip_length(c)
            tracks[0]['clips'].append(title)
    music=next((a for a in state['assets'] if a['id']==old.get('musicId')),None)
    if music:
        c=default_clip(music,0,'audio');c['end']=min(music['duration'],pos)
        c['volume']=old.get('musicVolume',.2)
        tracks[2]['clips'].append(c)
    out=old.get('output',{});state['output']['width']=out.get('width',3840)
    state['output']['height']=state['output']['width']*9//16
    state['output']['fps']=out.get('fps',30)
    return state

def save_state(candidate=None):
    with LOCK:
        new=deepcopy(STATE if candidate is None else candidate)
        if PROJECT.is_file() and new==STATE and not RECOVERED:return
        new['updated']=int(time.time())
        project_store.save(PROJECT,new,validate_document)
        STATE.clear()
        STATE.update(new)

def probe(path):
    p=subprocess.run(['ffprobe','-v','error','-show_entries',
                      'format=duration:stream=codec_type,codec_name,width,height,r_frame_rate,channels,color_transfer,color_primaries,color_space,pix_fmt',
                      '-of','json',str(path)],capture_output=True,text=True,timeout=75)
    if p.returncode:raise ValueError(f'FFprobe could not read {Path(path).name}: {p.stderr[-500:]}')
    info=json.loads(p.stdout);streams=info.get('streams',[])
    v=next((x for x in streams if x.get('codec_type')=='video'),None)
    a=next((x for x in streams if x.get('codec_type')=='audio'),None)
    duration=float(info.get('format',{}).get('duration') or 0)
    if not math.isfinite(duration) or duration<0:duration=0
    rate=(v or {}).get('r_frame_rate','0/1')
    try:
        numerator,denominator=map(float,rate.split('/'))
        fps=round(numerator/denominator,3) if denominator else 0
    except (ValueError,ZeroDivisionError):fps=0
    return {'duration':round(duration,3),'width':(v or {}).get('width') or 0,
            'height':(v or {}).get('height') or 0,'hasAudio':bool(a),
            'codec':(v or a or {}).get('codec_name','unknown'),'fps':fps,
            'colorTransfer':(v or {}).get('color_transfer','unknown'),
            'hdr':(v or {}).get('color_transfer') in ('smpte2084','arib-std-b67')}

def classify(path):
    ext=Path(path).suffix.lower()
    if ext in VIDEO:return 'video'
    if ext in IMAGE:return 'image'
    if ext in AUDIO:return 'audio'
    raise ValueError(f'Unsupported media extension: {ext}')

def add_asset(path,auto_add=True):
    path=Path(path).expanduser().resolve(strict=True)
    if not path.is_file():raise ValueError('Not a file: '+str(path))
    kind=classify(path)
    with LOCK:
        existing=next((a for a in STATE['assets'] if os.path.normcase(a['path'])==os.path.normcase(str(path))),None)
        if existing:return existing
    meta=probe(path)
    if kind=='video' and not meta['width']:raise ValueError('No playable video stream: '+path.name)
    if kind=='audio' and not meta['hasAudio']:raise ValueError('No playable audio stream: '+path.name)
    a={'id':uuid.uuid4().hex,'name':path.name,'path':str(path),'kind':kind,'size':path.stat().st_size,**meta}
    with LOCK:
        existing=next((item for item in STATE['assets'] if Path(item['path'])==path),None)
        if existing:return existing
        new=deepcopy(STATE)
        new['assets'].append(a)
        if auto_add:
            t=next(t for t in reversed(new['tracks']) if t['type']==('audio' if kind=='audio' else 'video'))
            last=max((engine.clip_finish(c) for c in t['clips']),default=0)
            t['clips'].append(default_clip(a,last,'audio' if kind=='audio' else kind))
        save_state(new)
    CACHE_WORKERS.submit(cache_media,a)
    return a

def relink_asset(aid,path):
    path=path.resolve(strict=True)
    meta=probe(path)
    with LOCK:
        new=deepcopy(STATE)
        asset=next((a for a in new['assets'] if a['id']==aid),None)
        if not asset or classify(path)!=asset['kind']:raise ValueError('Choose media of the same type')
        used=[c for t in new['tracks'] for c in t['clips'] if c.get('assetId')==aid]
        if asset['kind']!='image' and any(c['end']>meta['duration']+.001 for c in used):
            raise ValueError('Replacement ends before a timeline out-point')
        if asset['kind']!='audio' and not meta['width']:raise ValueError('Replacement has no video')
        if any(c['kind']=='audio' for c in used) and not meta['hasAudio']:raise ValueError('Replacement has no audio stream')
        asset.update(meta,path=str(path),size=path.stat().st_size,name=path.name,cacheId=uuid.uuid4().hex)
        save_state(new)
    CACHE_WORKERS.submit(cache_media,asset)
    return asset


def cache_media(asset):
    create_thumbnail(asset)
    if asset.get('hasAudio'):
        import waveform
        waveform.build(asset,THUMBS/(cache_id(asset)+'.wave.png'))


def create_thumbnail(asset):
    if asset['kind']=='audio':return
    THUMBS.mkdir(parents=True,exist_ok=True)
    out=THUMBS/(asset.get('cacheId',asset['id'])+'.jpg')
    if out.exists():return
    args=['ffmpeg','-hide_banner','-nostdin','-v','error','-y']
    if asset['kind']=='video':args+=['-ss',str(min(1,max(0,asset['duration']*.25)))]
    args+=['-i',asset['path'],'-frames:v','1','-vf',
           'scale=480:270:force_original_aspect_ratio=decrease,pad=480:270:(ow-iw)/2:(oh-ih)/2:black',
           '-q:v','5',str(out)]
    try:subprocess.run(args,capture_output=True,timeout=55)
    except (OSError,subprocess.TimeoutExpired):pass

def _number(value,what,lo,hi):
    try:n=float(value)
    except (TypeError,ValueError):raise ValueError(f'{what}: not a number')
    if not math.isfinite(n) or not lo<=n<=hi:raise ValueError(f'{what} out of range ({lo}–{hi})')
    return n

def validate_state(d, base=None):
    if base is None:base=STATE
    if not isinstance(d,dict):raise ValueError('Project must be an object')
    tracks=d.get('tracks')
    if not isinstance(tracks,list) or not tracks:raise ValueError('At least one track required')
    assets={a['id']:a for a in base['assets']}
    result=deepcopy(base)
    result['name']=str(d.get('name',base['name']))[:160]
    new=[];ids=set();clipids=set()
    for ti,t in enumerate(tracks):
        if not isinstance(t,dict) or t.get('type') not in ('video','audio'):raise ValueError('Invalid track kind')
        tid=str(t.get('id',uuid.uuid4().hex))[:64]
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',tid) or tid in ids:raise ValueError('Duplicate track ID')
        ids.add(tid)
        items=t.get('clips',[])
        if not isinstance(items,list):raise ValueError('Too many clips in track')
        out={'id':tid,'type':t['type'],'name':str(t.get('name','Track'))[:90],
             'muted':bool(t.get('muted',False)),'hidden':bool(t.get('hidden',False)),
             'locked':bool(t.get('locked',False)), 'volume':_number(t.get('volume',1),'Track volume',0,3),'clips':[]}
        out['solo']=bool(t.get('solo',False))
        out['height']=int(_number(t.get('height',67),'Track height',42,150))
        color=t.get('color','#ad95da' if t['type']=='audio' else '#79b4de')
        if not isinstance(color,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',color):raise ValueError('Invalid track color')
        out['color']=color
        for src in items:
            if not isinstance(src,dict):raise ValueError('Invalid clip')
            cid=str(src.get('id',uuid.uuid4().hex))[:64]
            if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',cid) or cid in clipids:raise ValueError('Duplicate clip ID')
            clipids.add(cid)
            kind=src.get('kind');asset=assets.get(src.get('assetId'))
            if kind=='title':
                if t['type']!='video':raise ValueError('Titles belong on video tracks')
                assetId=None
            else:
                if not asset:raise ValueError('Unknown asset in clip')
                if t['type']=='audio' and asset['kind'] not in ('video','audio'):
                    raise ValueError('Audio tracks require audio or video media')
                if t['type']=='video' and asset['kind']=='audio':raise ValueError('Audio cannot play on video tracks')
                kind='audio' if t['type']=='audio' else asset['kind'];assetId=asset['id']
            start=_number(src.get('start',0),'Source in',0,100000)
            end=_number(src.get('end',4),'Source out',.001,100000)
            if end<=start:raise ValueError('Source out must follow source in')
            if asset and asset['kind']!='image' and end>float(asset['duration'])+.12:
                raise ValueError('Clip exceeds source duration: '+asset['name'])
            if kind in ('image','title') and start!=0:raise ValueError('Still/title in-point must be zero')
            speed=_number(src.get('speed',1),'Playback speed',.25,4)
            c={'id':cid,'assetId':assetId,'kind':kind,
               'position':_number(src.get('position',0),'Position',0,1e12),'start':start,'end':end,
               'speed':speed,'volume':_number(src.get('volume',1),'Clip volume',0,3),
               'opacity':_number(src.get('opacity',1),'Opacity',0,1),
               'scale':_number(src.get('scale',1),'Scale',.1,3),
               'x':_number(src.get('x',0),'X offset',-2,2),
               'y':_number(src.get('y',0),'Y offset',-2,2),
               'grade':src.get('grade','neutral'),'fit':src.get('fit','contain'),
               'fadeIn':_number(src.get('fadeIn',0),'Fade in',0,30),
               'fadeOut':_number(src.get('fadeOut',0),'Fade out',0,30),
               'locked':bool(src.get('locked',False))}
            if 'keys' in src:c['keys']=animation.validate(src['keys'])
            if c['grade'] not in engine.GRADES:raise ValueError('Invalid color grade')
            if c['fit'] not in ('contain','cover'):raise ValueError('Invalid fit')
            if kind=='title':
                c.update(text=str(src.get('text','Title'))[:250],
                         color=src.get('color','white') if src.get('color','white') in ('white','yellow','cyan','black','#ffffff','#f5ce8a','#a6ffdf') else 'white',
                         titleAlign=src.get('titleAlign','center') if src.get('titleAlign') in ('center','lower') else 'center',
                         fontScale=_number(src.get('fontScale',.048),'Title size',.01,.15))
            if kind=='title' and isinstance(src.get('captionFor'),str):c['captionFor']=src['captionFor'][:64]
            out['clips'].append(c)
        new.append(out)
    result['tracks']=new
    output=d.get('output',base['output'])
    w=int(output.get('width',3840));fps=int(output.get('fps',30));crf=int(output.get('crf',20))
    preset=output.get('preset','medium')
    h=int(output.get('height',w*9//16))
    if min(w,h)<16 or max(w,h)>16384 or w%2 or h%2 or fps not in (24,25,30,50,60):raise ValueError('Invalid export resolution or FPS')
    if crf<15 or crf>30 or preset not in ('ultrafast','veryfast','fast','medium','slow'):
        raise ValueError('Invalid quality or encoder preset')
    encoder=output.get('encoder','libx264')
    if encoder not in encoders.NAMES:raise ValueError('Unknown video encoder')
    result['output']={'width':w,'height':h,'fps':fps,'crf':crf,'preset':preset,'encoder':encoder,
                      'bitrate':_number(output.get('bitrate',0),'Video bitrate',0,2000)}
    return result

def validate_document(document):
    if not isinstance(document,dict):raise ValueError('Invalid project document')
    if document.get('version')==2:document=migrate_v2(document)
    if document.get('version')!=3:raise ValueError('Unsupported project version')
    assets=document.get('assets')
    if not isinstance(assets,list):raise ValueError('Missing media inventory')
    known=set()
    for asset in assets:
        if not isinstance(asset,dict):raise ValueError('Invalid asset')
        aid=asset.get('id','')
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',aid) or aid in known:raise ValueError('Invalid asset ID')
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',asset.get('cacheId',aid)):raise ValueError('Invalid cache ID')
        known.add(aid)
        if not Path(asset['path']).is_absolute() or classify(asset['path'])!=asset['kind']:
            raise ValueError('Invalid media path or type')
        if not isinstance(asset['name'],str) or not math.isfinite(float(asset['duration'])):
            raise ValueError('Invalid media metadata')
    return validate_state(document,document)


STATE,RECOVERED=project_store.load(PROJECT,validate_document)
if STATE is None:STATE=default_state()

def choose_files():
    if os.name=='nt':
        ps=('Add-Type -AssemblyName System.Windows.Forms; '
            '$d=New-Object System.Windows.Forms.OpenFileDialog; '
            '$d.Title="Link original media files (no copying)"; '
            '$d.Multiselect=$true; $d.Filter="Media|*.mp4;*.m4v;*.mov;*.mkv;*.webm;*.mts;*.avi;*.wmv;*.jpg;*.jpeg;*.png;*.webp;*.mp3;*.wav;*.m4a;*.flac|All files|*.*"; '
            'if($d.ShowDialog() -eq "OK") { ConvertTo-Json -Compress -InputObject @($d.FileNames) }')
        r=subprocess.run(['powershell.exe','-NoProfile','-STA','-Command',ps],capture_output=True,text=True,timeout=300)
        if r.returncode:raise RuntimeError(r.stderr[-500:])
        return json.loads(r.stdout.strip()) if r.stdout.strip() else []
    from tkinter import filedialog,Tk
    tk=Tk();tk.withdraw();tk.attributes('-topmost',True)
    try:return list(filedialog.askopenfilenames(title='Link original media'))
    finally:tk.destroy()

def choose_save_path():
    if os.name=='nt':
        ps=('Add-Type -AssemblyName System.Windows.Forms; '
            '$d=New-Object System.Windows.Forms.SaveFileDialog; $d.Filter="MP4 video|*.mp4"; '
            '$d.DefaultExt="mp4"; $d.FileName="Kenya_Vlog_4K.mp4"; '
            'if($d.ShowDialog() -eq "OK") {$d.FileName}')
        r=subprocess.run(['powershell.exe','-NoProfile','-STA','-Command',ps],capture_output=True,text=True,timeout=300)
        if r.returncode:raise RuntimeError(r.stderr[-500:])
        return r.stdout.strip() or None
    from tkinter import filedialog,Tk
    tk=Tk();tk.withdraw();tk.attributes('-topmost',True)
    try:return filedialog.asksaveasfilename(defaultextension='.mp4',initialfile='Kenya_Vlog_4K.mp4',filetypes=[('MP4','*.mp4')]) or None
    finally:tk.destroy()

def job_status(which,**kw):
    with JOB_LOCK:JOBS[which].update(kw)

def exec_process(command,cwd,which):
    if CANCEL[which].is_set():raise RuntimeError('Cancelled')
    creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
    start=JOBS[which]['percent']
    total=JOBS[which].get('duration',0)
    with tempfile.TemporaryFile() as errors:
        cmd=[command[0],'-progress','pipe:1',*command[1:]]
        p=subprocess.Popen(cmd,cwd=cwd,stdout=subprocess.PIPE,stderr=errors,creationflags=creationflags)
        with JOB_LOCK:
            CURRENT_PROCESS[which]=p
            if CANCEL[which].is_set():p.terminate()
        try:
            for line in p.stdout:
                if total and start<96 and line.startswith(b'out_time_us='):
                    try:seconds=int(line.split(b'=')[1])/1e6
                    except ValueError:continue
                    job_status(which,percent=min(94,round(start+91*seconds/total)))
            p.wait()
            if CANCEL[which].is_set():raise RuntimeError('Cancelled')
            if p.returncode:
                errors.seek(0,2);errors.seek(max(0,errors.tell()-1600))
                raise RuntimeError('FFmpeg: '+errors.read().decode(errors='replace'))
        finally:
            p.stdout.close()
            with JOB_LOCK:CURRENT_PROCESS[which]=None

def run_export(snapshot,path,review=False):
    dest=Path(path)
    temp=None
    try:
        temp=Path(tempfile.mkdtemp(prefix='.vlogcraft_',dir=str(dest.parent)))
        encoder=snapshot['output'].get('encoder','libx264')
        fallback=''
        if not review and encoder.split('_')[-1] in encoders.BACKENDS and encoder not in encoders.available():
            replacement=encoders.CODECS[encoder.split('_')[0]][0]
            snapshot['output']['encoder']=replacement
            fallback=' · used '+encoders.NAMES[replacement]+' (hardware unavailable)'
        job_status('export',duration=engine.sequence_duration(snapshot))

        job_status('export',status='rendering',percent=1,message='Preparing timeline…',path=None,error=None)
        engine.render(snapshot,dest,temp,review=review,cancelled=CANCEL['export'].is_set,
                      popen=lambda c,d:exec_process(c,d,'export'),
                      on_progress=lambda pct,msg:job_status('export',percent=pct,message=msg))
        job_status('export',status='done',percent=100,path=str(dest),message='Export completed'+fallback)
    except Exception as ex:
        job_status('export',status='cancelled' if CANCEL['export'].is_set() else 'error',error=str(ex),message='Export stopped')
    finally:
        if temp:shutil.rmtree(temp,ignore_errors=True)

def cache_id(asset):
    return asset.get('cacheId',asset['id'])


def proxy_path(asset):
    return PROXIES/(cache_id(asset)+'.mp4')


def needs_proxy(asset):
    return (asset['kind']=='video' and
            (asset['width']>=3840 or asset['size']>=2**32 or asset['codec'] not in ('h264','vp8','vp9') or
             Path(asset['path']).suffix.lower() not in ('.mp4','.m4v','.webm')))


def queue_proxy(asset):
    with JOB_LOCK:
        key=cache_id(asset)
        if proxy_path(asset).is_file() or any(cache_id(a)==key for a in PROXY_QUEUE):return
        if JOBS['proxy']['status']=='rendering' and JOBS['proxy'].get('cacheId')==key:return
        PROXY_QUEUE.append(deepcopy(asset))
        if JOBS['proxy']['status']!='rendering':start_next_proxy()


def start_next_proxy():
    if not PROXY_QUEUE:return
    asset=PROXY_QUEUE.popleft()
    CANCEL['proxy'].clear()
    job_status('proxy',status='rendering',percent=0,message='Preparing proxy',assetId=asset['id'],cacheId=cache_id(asset),error=None)
    threading.Thread(target=run_proxy,args=(asset,),daemon=True).start()


def run_proxy(asset):
    dest=proxy_path(asset)
    tmp=dest.with_suffix('.partial.mp4')
    try:
        PROXIES.mkdir(parents=True,exist_ok=True)
        cmd=['ffmpeg','-hide_banner','-nostdin','-v','error','-y','-progress','pipe:1','-i',asset['path'],
             '-map','0:v:0','-map','0:a:0?','-vf','scale=1280:720:force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1',
             '-c:v','libx264','-preset','veryfast','-crf','24','-pix_fmt','yuv420p','-g','24',
             '-c:a','aac','-b:a','160k','-movflags','+faststart',str(tmp)]
        with tempfile.TemporaryFile() as errors:
            with subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=errors,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)) as proc:
                with JOB_LOCK:
                    CURRENT_PROCESS['proxy']=proc
                    if CANCEL['proxy'].is_set():proc.terminate()
                for line in proc.stdout:
                    if line.startswith(b'out_time_us='):
                        try:seconds=int(line.split(b'=')[1])/1000000
                        except ValueError:continue
                        percent=min(99,int(100*seconds/max(.01,asset['duration'])))
                        job_status('proxy',percent=percent,message='Proxy: '+asset['name'])
                if CANCEL['proxy'].is_set():raise ValueError('Proxy cancelled')
                if proc.wait():
                    errors.seek(0);raise ValueError(errors.read()[-1200:].decode(errors='replace'))
        os.replace(tmp,dest)
        result=dict(status='done',percent=100,message='Proxy ready')
    except Exception as exc:
        result=dict(status='cancelled' if CANCEL['proxy'].is_set() else 'error',error=str(exc),message='Proxy stopped')
    finally:
        tmp.unlink(missing_ok=True)
        with JOB_LOCK:
            CURRENT_PROCESS['proxy']=None
            job_status('proxy',**result)
            start_next_proxy()

def _legacy(s):
    video=next((t for t in reversed(s['tracks']) if t['type']=='video'),None)
    timeline=[]
    for c in sorted(video['clips'],key=lambda x:x['position']) if video else []:
        if c.get('assetId'):
            timeline.append({'id':c['id'],'originalId':c['id'],'assetId':c['assetId'],'start':c['start'],'end':c['end'],
                             'volume':c['volume'],'fade':bool(c.get('fadeIn') or c.get('fadeOut')),
                             'caption':next((title['text'] for track in s['tracks'] for title in track['clips'] if title.get('captionFor')==c['id']),''),'fit':c.get('fit','contain'),'grade':c.get('grade','neutral')})
    a2=next((t for t in s['tracks'] if t['type']=='audio' and t['clips']),None)
    musicId=a2['clips'][0]['assetId'] if a2 and a2['clips'] else None
    musicVolume=a2['clips'][0].get('volume',.2) if musicId else .2
    return {'name':s['name'],'assets':s['assets'],'timeline':timeline,
            'musicId':musicId,'musicVolume':musicVolume,'output':s['output']}

def _apply_legacy(current,legacy):
    result=deepcopy(current)
    v1=next((t for t in reversed(result['tracks']) if t['type']=='video'),None)
    if not v1:raise ValueError('No main video track')
    source={c['id']:c for c in v1['clips']}
    timeline=[];pos=0
    for l in legacy['timeline']:
        original=l.get('originalId',l['id'])
        if original not in source:raise ValueError('Unknown clip in AI actions')
        c=deepcopy(source[original]);c['id']=l['id'];c.update({k:l[k] for k in ('start','end','volume','grade','fit')})
        c['position']=round(pos,3)
        if l.get('fade'):c['fadeIn']=c['fadeOut']=.25
        else:c['fadeIn']=c['fadeOut']=0
        timeline.append(c);pos+=clip_length(c)
    v1['clips']=[c for c in v1['clips'] if c['kind']=='title']+timeline
    previous={c['captionFor']:c for t in result['tracks'] for c in t['clips'] if c.get('captionFor') in source}
    for t in result['tracks']:
        t['clips']=[c for c in t['clips'] if c.get('captionFor') not in source]
    for l,c in zip(legacy['timeline'],timeline):
        if l.get('caption'):
            title=previous.get(c['id'],default_title())
            title.update(text=l['caption'],position=c['position'],end=clip_length(c),captionFor=c['id'])
            next(t for t in result['tracks'] if t['type']=='video')['clips'].append(title)
    if legacy.get('musicId'):
        a=next((t for t in result['tracks'] if t['type']=='audio' and t['clips']),None)
        if a:a['clips'][0]['volume']=legacy.get('musicVolume',.2)
    return result

def state_digest(s):
    contents={k:v for k,v in s.items() if k!='updated'}
    return hashlib.sha256(json.dumps(contents,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def edit_digest(s,p):
    return hashlib.sha256(json.dumps([state_digest(s),p],sort_keys=True).encode()).hexdigest()


def prepare_proposal(proposal,base):
    if not isinstance(proposal,dict):raise ValueError('Expected an edit proposal')
    if 'schema' in proposal:return timeline_proposal.apply(proposal,base,validate_state)
    edited,audit=ai_bridge.validate_and_apply(proposal,_legacy(base))
    checked=validate_state(_apply_legacy(base,edited),base)
    for old,new in zip(base['tracks'],checked['tracks']):
        if old.get('locked') and old!=new:raise ValueError('Proposal changes a locked track')
        clips={c['id']:c for c in new['clips']}
        for c in old['clips']:
            if c.get('locked') and clips.get(c['id'])!=c:raise ValueError('Proposal changes a locked clip')
    return checked,audit


class Handler(BaseHTTPRequestHandler):
    server_version='VlogCraftStudio/3.0'
    protocol_version='HTTP/1.1'
    def handle(self):
        try:super().handle()
        except (BrokenPipeError,ConnectionAbortedError,ConnectionResetError):pass
    def log_message(self,fmt,*args):
        if not any(x in str(args) for x in ('/media/','/thumb/','/api/jobs')):
            if getattr(__import__('sys'),'stdout',None):print('[VlogCraft]',fmt%args)
    def json_response(self,data,status=200):
        b=json.dumps(data,ensure_ascii=False,allow_nan=False).encode('utf8')
        self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(b)));self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(b)
    def reject(self,e):
        self.json_response({'error':str(e)},400)
    def check_origin(self):
        origin=self.headers.get('Origin')
        host=f'http://127.0.0.1:{self.server.server_address[1]}'
        return origin in (None,host)
    def read_json(self):
        n=int(self.headers.get('Content-Length','0'))
        if n<0 or n>5*1024**2:raise ValueError('JSON payload too large')
        return json.loads(self.rfile.read(n)) if n else {}
    def file_response(self,path,content_type=None):
        path=Path(path)
        if not path.is_file():return self.json_response({'error':'File missing'},404)
        total=path.stat().st_size
        start=0;end=max(0,total-1)
        rng=self.headers.get('Range')
        if rng:
            m=re.fullmatch(r'bytes=(\d*)-(\d*)',rng.strip())
            if not m or (not m.group(1) and not m.group(2)):
                self.send_response(416);self.send_header('Content-Range',f'bytes */{total}');self.send_header('Content-Length','0');self.end_headers();return
            if m.group(1):start=int(m.group(1))
            if m.group(2):
                if m.group(1):end=min(total-1,int(m.group(2)))
                else:start=max(0,total-int(m.group(2)))
            if start>=total or end<start:
                self.send_response(416);self.send_header('Content-Range',f'bytes */{total}');self.send_header('Content-Length','0');self.end_headers();return
        length=end-start+1
        self.send_response(206 if rng else 200)
        self.send_header('Content-Type',content_type or mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
        self.send_header('Content-Length',str(length));self.send_header('Accept-Ranges','bytes')
        if rng:self.send_header('Content-Range',f'bytes {start}-{end}/{total}')
        self.send_header('Cache-Control','private, max-age=3600');self.send_header('X-Content-Type-Options','nosniff')
        self.end_headers()
        if self.command=='HEAD':return
        try:
            with path.open('rb') as f:
                f.seek(start)
                remaining=length
                while remaining:
                    data=f.read(min(1024*1024,remaining))
                    if not data:break
                    self.wfile.write(data);remaining-=len(data)
        except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass
    def do_HEAD(self):self.do_GET()
    def do_GET(self):
        parsed=urlparse(self.path);path=parsed.path
        try:
            if path=='/api/state':
                with LOCK:snapshot=deepcopy(STATE)
                for asset in snapshot['assets']:asset['missing']=not Path(asset['path']).is_file()
                snapshot['desktop']=DESKTOP_ACTION is not None
                snapshot['recovered']=RECOVERED
                return self.json_response(snapshot)
            if path=='/api/encoders':return self.json_response(encoders.available())
            if path=='/api/jobs':
                with JOB_LOCK:jobs=deepcopy(JOBS);jobs['proxy']['queued']=len(PROXY_QUEUE)
                with LOCK:jobs['readyProxies']=[a['id'] for a in STATE['assets'] if proxy_path(a).is_file()]
                return self.json_response(jobs)
            if path=='/api/motion/frame':
                asset,clip=motion_source(parse_qs(parsed.query).get('clip',[''])[0])
                cmd=['ffmpeg','-nostdin','-v','error','-ss',str(clip['start']),'-i',asset['path'],
                     '-frames:v','1','-vf','scale=640:-2','-c:v','mjpeg','-f','image2pipe','pipe:1']
                frame=subprocess.run(cmd,capture_output=True,timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                if frame.returncode or not frame.stdout:raise ValueError('Unable to decode source frame')
                self.send_response(200);self.send_header('Content-Type','image/jpeg')
                self.send_header('Content-Length',str(len(frame.stdout)));self.end_headers()
                self.wfile.write(frame.stdout)
                return
            if path=='/api/upload/status':
                uid=parse_qs(parsed.query).get('id',[''])[0]
                with UPLOAD_LOCK:
                    x=UPLOADS.get(uid)
                    if not x:return self.json_response({'error':'Unknown transfer'},404)
                    return self.json_response({'offset':x['offset'],'size':x['size']})
            if path.startswith('/media/'):
                parts=path.split('/');aid=parts[2] if len(parts)>2 else ''
                with LOCK:a=next((a for a in STATE['assets'] if a['id']==aid),None)
                if not a:return self.json_response({'error':'Unknown asset'},404)
                proxy=proxy_path(a)
                if parse_qs(parsed.query).get('proxy',['0'])[0]=='1' and proxy.is_file():
                    return self.file_response(proxy,'video/mp4')
                return self.file_response(a['path'])
            if path.startswith(('/thumb/','/wave/')):
                aid=path.split('/')[2]
                if not re.fullmatch(r'[a-f0-9]{32}',aid):return self.json_response({'error':'Invalid ID'},404)
                with LOCK:asset=next((a for a in STATE['assets'] if a['id']==aid),None)
                if not asset:return self.json_response({'error':'Unknown asset'},404)
                if path.startswith('/wave/'):return self.file_response(THUMBS/(cache_id(asset)+'.wave.png'),'image/png')
                return self.file_response(THUMBS/(cache_id(asset)+'.jpg'),'image/jpeg')
            if path.startswith('/download/'):
                name=Path(path).name
                if not re.fullmatch(r'[\w.\-]{1,130}',name):return self.json_response({'error':'Invalid filename'},404)
                target=REVIEWS/name
                if not target.exists():target=EXPORTS/name
                return self.file_response(target)
            if path=='/' or path=='/index.html':return self.file_response(WEB/'index.html','text/html; charset=utf-8')
            if path in ('/app.js','/studio.js','/animation.js','/motion.js','/timeline.js','/style.css'):
                return self.file_response(WEB/path.lstrip('/'))
            return self.json_response({'error':'Not found'},404)
        except (BrokenPipeError,ConnectionAbortedError,ConnectionResetError):return
        except Exception as ex:return self.reject(ex)
    def do_PUT(self):
        if not self.check_origin():return self.json_response({'error':'Forbidden origin'},403)
        path=urlparse(self.path).path
        if path!='/api/upload/chunk':return self.json_response({'error':'Unknown route'},404)
        try:
            query=parse_qs(urlparse(self.path).query)
            uid=query.get('id',[''])[0];offset=int(query.get('offset',['-1'])[0])
            n=int(self.headers.get('Content-Length','-1'))
            if n<1 or n>MAX_CHUNK:return self.reject('Chunk must contain 1–16 MiB')
            with UPLOAD_LOCK:
                u=UPLOADS.get(uid)
                if not u:raise ValueError('Unknown transfer')
                if offset!=u['offset']:raise ValueError('Wrong chunk offset; resume using transfer status')
                if offset+n>u['size']:raise ValueError('Chunk exceeds declared file size')
                with Path(u['tmp']).open('r+b',buffering=0) as f:
                    f.seek(offset)
                    remaining=n
                    while remaining:
                        part=self.rfile.read(min(1024*1024,remaining))
                        if not part:raise ValueError('Interrupted chunk')
                        f.write(part);remaining-=len(part)
                u['offset']+=n;u['touched']=time.time()
                return self.json_response({'offset':u['offset'],'size':u['size']})
        except (BrokenPipeError,ConnectionAbortedError,ConnectionResetError):return
        except Exception as ex:return self.reject(ex)
    def do_POST(self):
        if not self.check_origin():return self.json_response({'error':'Forbidden origin'},403)
        path=urlparse(self.path).path
        try:
            data=self.read_json()
            if path=='/api/upload/start':
                name=Path(str(data.get('name','')).replace('\\','/')).name
                size=int(data.get('size',0))
                if not name or len(name)>220 or any(ord(x)<32 for x in name):raise ValueError('Invalid file name')
                if classify(name) not in ('video','audio','image'):raise ValueError('Unsupported media')
                if size<=0:raise ValueError('Invalid file size')
                MEDIA.mkdir(parents=True,exist_ok=True)
                free=shutil.disk_usage(MEDIA).free
                if size>free-128*1024**2:
                    raise ValueError('Not enough space for local drag-and-drop copy. Use Link files instead (no copy).')
                uid=uuid.uuid4().hex
                tmp=MEDIA/(uid+'.part')
                with tmp.open('xb'):pass
                with UPLOAD_LOCK:UPLOADS[uid]={'tmp':str(tmp),'size':size,'offset':0,'name':name,'touched':time.time()}
                return self.json_response({'id':uid,'offset':0,'chunkBytes':MAX_CHUNK,'copiesToWorkspace':True})
            if path=='/api/upload/finish':
                uid=str(data.get('id',''))
                with UPLOAD_LOCK:
                    u=UPLOADS.get(uid)
                    if not u:raise ValueError('Unknown transfer')
                    if u['offset']!=u['size']:raise ValueError('Upload not complete')
                    tmp=Path(u['tmp'])
                    final=MEDIA/(uid+'_'+u['name'])
                    os.replace(tmp,final)
                    del UPLOADS[uid]
                try:a=add_asset(final,auto_add=False)
                except Exception:
                    final.unlink(missing_ok=True);raise
                return self.json_response({'asset':a})
            if path=='/api/upload/cancel':
                uid=str(data.get('id',''))
                with UPLOAD_LOCK:u=UPLOADS.pop(uid,None)
                if u:Path(u['tmp']).unlink(missing_ok=True)
                return self.json_response({'cancelled':bool(u)})
            if path=='/api/motion':
                import motion
                asset,clip=motion_source(data.get('clipId'))
                with JOB_LOCK:
                    if JOBS['motion']['status']=='rendering':raise ValueError('Another analysis is active')
                    CANCEL['motion'].clear();job_status('motion',status='rendering',percent=0)
                try:
                    analysis=motion.analyze(asset,clip,data,CANCEL['motion'].is_set,
                                            lambda percent:job_status('motion',percent=percent))
                finally:
                    job_status('motion',status='idle')
                return self.json_response(analysis)
            if path=='/api/desktop':
                if DESKTOP_ACTION is None:raise ValueError('Open the desktop application')
                return self.json_response(DESKTOP_ACTION(data.get('action')))
            if path=='/api/relink':
                aid=data.get('assetId')
                paths=choose_files()
                if not paths:return self.json_response({'cancelled':True})
                if len(paths)!=1:raise ValueError('Select one replacement file')
                return self.json_response({'asset':relink_asset(aid,Path(paths[0]))})
            if path=='/api/import':
                paths=data.get('paths')
                if paths is None:paths=choose_files()
                if not isinstance(paths,(list,tuple)) or len(paths)>150:raise ValueError('Select up to 150 files')
                assets=[];errs=[]
                for item in paths:
                    try:assets.append(add_asset(item,auto_add=False))
                    except Exception as ex:errs.append(str(ex))
                for asset in assets:
                    if data.get('autoProxy') and needs_proxy(asset):queue_proxy(asset)
                return self.json_response({'assets':assets,'errors':errs})
            if path=='/api/state':
                with LOCK:
                    s=validate_state(data)
                    save_state(s)
                    return self.json_response(deepcopy(STATE))
            if path=='/api/title':return self.json_response({'clip':default_title()})
            if path=='/api/proxy':
                aid=str(data.get('assetId',''))
                with LOCK:a=next((x for x in STATE['assets'] if x['id']==aid),None)
                if not a or a['kind']!='video':raise ValueError('Select a video to create proxy')
                queue_proxy(a)
                return self.json_response({'started':True})
            if path=='/api/export' or path=='/api/review/video':
                with JOB_LOCK:
                    if JOBS['export']['status']=='rendering':raise ValueError('Another export is active')
                with LOCK:snap=deepcopy(STATE)
                if engine.sequence_duration(snap)<=0:raise ValueError('Timeline empty')
                review=path=='/api/review/video'
                if review:
                    snap['output'].update(width=1280,height=720,fps=24,crf=27,preset='veryfast')
                    dest=REVIEWS/f'Kenya_Review_{uuid.uuid4().hex[:10]}.mp4'
                else:
                    save_to=data.get('path') or choose_save_path()
                    if not save_to:return self.json_response({'cancelled':True})
                    dest=Path(save_to).expanduser().resolve()
                    if dest.suffix.lower()!='.mp4':raise ValueError('Choose an MP4 output file')
                    if dest in {Path(a['path']).resolve() for a in snap['assets']}:
                        raise ValueError('Refusing to overwrite your original footage')
                dest.parent.mkdir(parents=True,exist_ok=True)
                with JOB_LOCK:
                    if JOBS['export']['status']=='rendering':raise ValueError('Another export is active')
                    CANCEL['export'].clear()
                    job_status('export',status='rendering',percent=0,path=None,error=None,message='Starting…')
                    threading.Thread(target=run_export,args=(snap,str(dest),review),daemon=True).start()
                return self.json_response({'started':True,'url':'/download/'+dest.name if review else None})
            if path=='/api/job/cancel':
                kind=data.get('job','export')
                if kind not in ('export','proxy','motion'):raise ValueError('Invalid job')
                CANCEL[kind].set()
                with JOB_LOCK:
                    p=CURRENT_PROCESS[kind]
                    if p and p.poll() is None:p.terminate()
                return self.json_response({'cancelRequested':True})
            if path=='/api/review':
                with LOCK:snap=deepcopy(STATE)
                name=f'Kenya_Review_{uuid.uuid4().hex[:12]}.zip';dest=REVIEWS/name
                legacy=_legacy(snap);r=ai_bridge.create_review_zip(legacy,dest)
                with zipfile.ZipFile(dest,'a',zipfile.ZIP_DEFLATED) as z:
                    manifest={'project':snap['name'],'duration':engine.sequence_duration(snap),'output':snap['output'],
                              'proposalSchema':timeline_proposal.SCHEMA,'tracks':[{'trackId':t['id'],'name':t['name'],'type':t['type'],'locked':t['locked'],'muted':t['muted'],
                                         'clips':[{'clipId':c['id'],'assetName':next((a['name'] for a in snap['assets'] if a['id']==c.get('assetId')),'Title'),
                                                   'position':c['position'],'sourceIn':c['start'],'sourceOut':c['end'],'duration':clip_length(c)} for c in t['clips']]} for t in snap['tracks']]}
                    z.writestr('MULTITRACK_EDITS.txt','Use the IDs in multitrack_manifest.json. Return JSON with schema "vlogcraft.timeline/1" and actions. Each edit_clip action needs trackId, clipId and set (for example {"grade":"warm","volume":0.7}). Each edit_track needs trackId and set (volume, muted or hidden). Positions and source trims are seconds. All edits require approval.')
                    z.writestr('multitrack_manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
                return self.json_response({'url':'/download/'+name,**r})
            if path=='/api/ai/analyze':
                with LOCK:snap=deepcopy(STATE)
                return self.json_response(ai_bridge.analyze_with_openai(_legacy(snap),str(data.get('apiKey','')),str(data.get('goal',''))))
            if path=='/api/ai/preview':
                proposal=data.get('proposal')
                with LOCK:base=deepcopy(STATE)
                checked,audit=prepare_proposal(proposal,base)
                with LOCK:
                    AI_PREVIEW.update(token=uuid.uuid4().hex,digest=edit_digest(base,proposal),created=time.time(),checked=checked,changes=audit)
                return self.json_response({'changes':audit,'approvalToken':AI_PREVIEW['token'],
                                           'count':len(audit),'summary':str(proposal.get('summary',''))[:1000]})
            if path=='/api/ai/apply':
                proposal=data.get('proposal')
                with LOCK:
                    base=deepcopy(STATE)
                    if data.get('approvalToken')!=AI_PREVIEW['token'] or not AI_PREVIEW['token']:
                        raise ValueError('Preview exact edits before applying')
                    if time.time()-AI_PREVIEW['created']>900 or edit_digest(base,proposal)!=AI_PREVIEW['digest']:
                        raise ValueError('Project changed since AI preview')
                    checked,audit=AI_PREVIEW['checked'],AI_PREVIEW['changes']
                    undo_data=json.dumps({'before':base,'afterDigest':state_digest(checked)},ensure_ascii=False)
                    project_store.atomic_write(AI_UNDO,undo_data.encode('utf8'))
                    save_state(checked)
                    AI_PREVIEW.update(token=None,digest=None,created=0)
                    return self.json_response({'state':deepcopy(STATE),'changes':audit})
            if path=='/api/ai/undo':
                with LOCK:
                    if not AI_UNDO.is_file():raise ValueError('No AI edit to undo')
                    undo=json.loads(AI_UNDO.read_text(encoding='utf8'))
                    if state_digest(STATE)!=undo.get('afterDigest'):
                        raise ValueError('Newer changes were made after the AI edit; undo blocked')
                    checked=validate_state(undo['before'])
                    save_state(checked);AI_UNDO.unlink()
                    return self.json_response({'state':deepcopy(STATE)})
            if path=='/api/migrate/v2':
                legacy=WORK/'previous_v2_project.json'
                if not legacy.exists():raise ValueError('No prior project imported')
                migrated=migrate_v2(json.loads(legacy.read_text('utf8')))
                with LOCK:
                    save_state(validate_document(migrated))
                    return self.json_response(deepcopy(STATE))
            return self.json_response({'error':'Unknown action'},404)
        except (BrokenPipeError,ConnectionAbortedError,ConnectionResetError):return
        except Exception as ex:return self.reject(ex)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=0)
    parser.add_argument('--no-browser',action='store_true');args=parser.parse_args()
    for app in ('ffmpeg','ffprobe'):
        if not shutil.which(app):raise SystemExit(f'{app} not in PATH. Windows: winget install Gyan.FFmpeg')
    for p in (MEDIA,THUMBS,PROXIES,REVIEWS,EXPORTS):p.mkdir(parents=True,exist_ok=True)
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    server.daemon_threads=True
    url='http://127.0.0.1:'+str(server.server_address[1])+'/'
    print('VLOGCRAFT STUDIO 3 • '+url,flush=True)
    print('All projects, sources and renders stay local. Close this terminal to stop.',flush=True)
    if not args.no_browser:threading.Timer(.6,lambda:webbrowser.open(url)).start()
    try:server.serve_forever(.25)
    except KeyboardInterrupt:pass
    finally:server.server_close()
if __name__=='__main__':main()
