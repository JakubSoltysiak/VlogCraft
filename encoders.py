"""Probe real encodes before presenting accelerators on this machine."""
import concurrent.futures
import subprocess
import threading

CODECS={'h264':('libx264','H.264'), 'hevc':('libx265','HEVC'), 'av1':('libsvtav1','AV1')}
BACKENDS={'amf':'AMD AMF','nvenc':'NVIDIA NVENC','qsv':'Intel Quick Sync'}
NAMES={name:label+' · CPU' for name,label in CODECS.values()}
for codec,(_,label) in CODECS.items():
    for backend,display in BACKENDS.items():
        NAMES[codec+'_'+backend]=label+' · '+display

_cached=None
_lock=threading.Lock()


def supports(name):
    cmd=['ffmpeg','-hide_banner','-nostdin','-v','error','-f','lavfi','-i','color=s=320x192:r=30',
         '-frames:v','2','-c:v',name,'-threads','2','-f','null','-']
    try:
        result=subprocess.run(cmd,capture_output=True,timeout=16,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        return result.returncode==0
    except (OSError,subprocess.TimeoutExpired):
        return False


def available():
    global _cached
    with _lock:
        if _cached is None:
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                _cached={name:NAMES[name] for name,ok in zip(NAMES,pool.map(supports,NAMES)) if ok}
        return _cached


def options(name,preset,crf,bitrate):
    if name not in NAMES:raise ValueError('Unknown video encoder')
    result=['-c:v',name]
    if name in ('libx264','libx265'):
        result+=['-preset',preset]
    elif name=='libsvtav1':
        result+=['-preset',{'ultrafast':'12','veryfast':'10','fast':'8','medium':'6','slow':'4'}[preset]]
    hardware=name.split('_')[-1] in BACKENDS
    if bitrate or hardware:
        result+=['-b:v',str(round((bitrate or 35)*1_000_000))]
    else:
        result+=['-crf',str(crf)]
    if name.startswith('hevc') or name=='libx265':result+=['-tag:v','hvc1']
    return result
