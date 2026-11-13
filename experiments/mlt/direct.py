"""Pull real MLT images through the C ABI; no null-consumer shortcuts."""
import argparse,ctypes as C,json,os,time
from fractions import Fraction
from pathlib import Path
import prototype

def main(args):
    args.results.mkdir(parents=True,exist_ok=True);started=time.perf_counter()
    folder=args.folder.resolve();args.results=args.results.resolve();args.media=[p.resolve() for p in args.media]
    C.windll.kernel32.SetDllDirectoryW(str(folder));os.environ['PATH']=str(folder)+os.pathsep+os.environ['PATH']
    os.environ.update(MLT_DATA=str(folder/'share/mlt'),MLT_REPOSITORY=str(folder/'lib/mlt'),QT_QPA_PLATFORM='offscreen')
    directory=os.add_dll_directory(str(folder))
    dll=C.CDLL(str(folder/'libmlt-7.dll'))
    def api(name,restype,argtypes):
        fn=getattr(dll,name);fn.restype=restype;fn.argtypes=argtypes;return fn
    ptr=C.c_void_p;integer=C.c_int;ref=C.POINTER(integer)
    init=api('mlt_factory_init',ptr,[C.c_char_p]);profile_init=api('mlt_profile_init',ptr,[C.c_char_p])
    make=api('mlt_factory_producer',ptr,[ptr,C.c_char_p,ptr]);service=api('mlt_producer_service',ptr,[ptr])
    frame_get=api('mlt_service_get_frame',integer,[ptr,C.POINTER(ptr),integer])
    image_get=api('mlt_frame_get_image',integer,[ptr,C.POINTER(ptr),ref,ref,ref,integer])
    audio_get=api('mlt_frame_get_audio',integer,[ptr,C.POINTER(ptr),ref,ref,ref,ref])
    frame_close=api('mlt_frame_close',None,[ptr]);producer_close=api('mlt_producer_close',None,[ptr])
    profile_close=api('mlt_profile_close',None,[ptr]);factory_close=api('mlt_factory_close',None,[])
    seek=api('mlt_producer_seek',integer,[ptr,integer])
    fps=Fraction(args.rate);format_id=10 if args.image_format=='rgba64' else 2;pixel_bytes=8 if format_id==10 else 4
    profile_file=args.results/'profile'
    profile_file.write_text(f'description=VlogCraft benchmark\nframe_rate_num={fps.numerator}\nframe_rate_den={fps.denominator}\nwidth={args.width}\nheight={args.width*9//16}\nprogressive=1\nsample_aspect_num=1\nsample_aspect_den=1\ndisplay_aspect_num=16\ndisplay_aspect_den=9\ncolorspace=709\n')
    xml=args.results/'scene.mlt';prototype.project(args.media,args.width,args.width*9//16,args.frames+300,xml,audio=args.audio,rate=args.rate)
    assert init(str(folder/'lib/mlt').encode())
    environment=api('mlt_environment_set',integer,[C.c_char_p,C.c_char_p])
    environment(b'MLT_DATA',str(folder/'share/mlt').encode())
    environment(b'MLT_PRESETS_PATH',str(folder/'share/mlt/presets').encode())
    profile=profile_init(str(profile_file.resolve()).encode());assert profile
    path=C.c_char_p(str(xml.resolve()).encode());producer=make(profile,b'xml',C.cast(path,ptr));assert producer
    srv=service(producer);setup=time.perf_counter()-started
    samples=0;first=0;run=time.perf_counter();captures=[]
    pcm=(args.results/'audio.f32').open('wb') if args.audio_dump else None
    try:
        for n in range(args.frames):
            frame=ptr();assert frame_get(srv,C.byref(frame),0)==0 and frame.value
            try:
                data=ptr();fmt=integer(format_id);width=integer(args.width);height=integer(args.width*9//16)
                assert image_get(frame,C.byref(data),C.byref(fmt),C.byref(width),C.byref(height),0)==0 and data.value
                assert (fmt.value,width.value,height.value)==(format_id,args.width,args.width*9//16),(fmt.value,width.value,height.value)
                if n==0:first=setup+time.perf_counter()-run
                if args.capture and n in (0,args.frames-1):
                    name=f'frame-{n}.rgba';(args.results/name).write_bytes(C.string_at(data,width.value*height.value*pixel_bytes));captures.append(name)
                if args.audio:
                    audio=ptr();af=integer(5);hz=integer(48000);channels=integer(args.channels);count=integer(round((n+1)*48000/fps)-round(n*48000/fps))
                    assert audio_get(frame,C.byref(audio),C.byref(af),C.byref(hz),C.byref(channels),C.byref(count))==0 and audio.value
                    assert hz.value==48000 and channels.value==args.channels
                    samples+=count.value
                    if pcm:pcm.write(C.string_at(audio,count.value*channels.value*4))
            finally:frame_close(frame)
        elapsed=time.perf_counter()-run
        seeks=[]
        for at in ((240,60,240) if args.measure_seeks else ()):
            begin=time.perf_counter();seek(producer,at);frame=ptr()
            assert frame_get(srv,C.byref(frame),0)==0
            try:
                data=ptr();fmt=integer(2);w=integer(args.width);h=integer(args.width*9//16)
                assert image_get(frame,C.byref(data),C.byref(fmt),C.byref(w),C.byref(h),0)==0
            finally:frame_close(frame)
            seeks.append(time.perf_counter()-begin)
        result={'engine':'MLT C ABI','frames':args.frames,'layers':len(args.media),'width':args.width,'audio':args.audio,
                'image_format':args.image_format,'audio_channels':args.channels,'setup_seconds':setup,'first_frame_seconds':first,'processing_seconds':elapsed,
                'composited_fps':args.frames/elapsed,'seeks_seconds':seeks,'audio_samples':samples,'captures':captures,'presented':False}
        (args.results/'direct.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)
    finally:
        if pcm:pcm.close()
        producer_close(producer);profile_close(profile);factory_close();directory.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('folder',type=Path);p.add_argument('results',type=Path);p.add_argument('media',type=Path,nargs='+')
    p.add_argument('--image-format',choices=['rgba','rgba64'],default='rgba');p.add_argument('--rate',default='60');p.add_argument('--channels',type=int,default=2);p.add_argument('--audio-dump',action='store_true')
    p.add_argument('--width',type=int,default=960);p.add_argument('--frames',type=int,default=180);p.add_argument('--audio',action='store_true');p.add_argument('--capture',action='store_true');p.add_argument('--measure-seeks',action='store_true')
    main(p.parse_args())
