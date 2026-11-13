"""Automatic high-precision and channel-preservation experiments, generated media only."""
import argparse,json,os,subprocess,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
def checked(command,env=None,log=None):
    r=subprocess.run(command,env=env,capture_output=True,timeout=180)
    if log:log.write_bytes(r.stdout+r.stderr)
    assert r.returncode==0,(command[0],r.stderr[-1000:])
    return r.stdout
def main(a):
    root=a.results.resolve();root.mkdir(parents=True,exist_ok=True)
    tools=ROOT/'build/tools/architecture';sdk=tools/'ffmpeg-shared/ffmpeg-9.0.2-full_build-shared/bin'
    env=dict(os.environ,PATH=str(sdk)+os.pathsep+os.environ['PATH'])
    ramp=root/'ramp10.mp4'
    checked(['ffmpeg','-nostdin','-v','error','-y','-f','lavfi','-i','nullsrc=s=1024x576:r=24:d=0.125',
        '-vf',"format=yuv420p10le,geq=lum='64+876*X/(W-1)':cb=512:cr=512",
        '-c:v','libx265','-pix_fmt','yuv420p10le','-x265-params','lossless=1:pools=2:frame-threads=1:log-level=error',str(ramp)])
    checked([str(tools/'native_d3d11.exe'),'--frames','3','--width','1024','--height','576','--capture',str(root/'native'),str(ramp)],env,root/'native.log')
    original=checked(['ffmpeg','-v','error','-i',str(ramp),'-frames:v','1','-pix_fmt','yuv420p10le','-f','rawvideo','-'])
    expected=(np.frombuffer(original,np.uint16)[:1024*576].reshape(576,1024).astype(float)-64)/876
    native=np.fromfile(root/'native-0.rgba16f',np.float16).reshape(576,1024,4)[:,:,0].astype(float)
    error=float(np.mean(np.abs(native-expected)));unique=int(np.unique(native[288]).size)
    assert unique>700 and error<.002,(unique,error)
    controls={}
    for mode in ('download','software'):
        checked([str(tools/'native_d3d11.exe'),'--mode',mode,'--frames','3','--width','1024','--height','576','--capture',str(root/mode),str(ramp)],env,root/(mode+'.log'))
        values=np.fromfile(root/(mode+'-0.rgba16f'),np.float16).reshape(576,1024,4)[:,:,0].astype(float)
        count=int(np.unique(values[288]).size);delta=float(np.abs(values-expected).mean())
        assert count>700 and delta<.002,(mode,count,delta)
        controls[mode]={'distinct_luma_values':count,'mean_error_normalized':delta}
    mlt=root/'mlt-ramp'
    checked([sys.executable,str(ROOT/'experiments/mlt/direct.py'),str(tools/'shotcut/Shotcut'),str(mlt),str(ramp),
             '--width','1024','--frames','3','--rate','24','--image-format','rgba64','--capture'],log=root/'mlt-ramp.log')
    high=np.fromfile(mlt/'frame-0.rgba',np.uint16).reshape(576,1024,4)[:,:,0].astype(float)/65535
    mlt_unique=int(np.unique(high[288]).size);mlt_error=float(np.mean(np.abs(high-expected)))
    assert mlt_unique>700 and mlt_error<.01,(mlt_unique,mlt_error)
    source=root/'six-channel.mkv'
    waves='|'.join(f'.08*sin(2*PI*{220+110*n}*t)' for n in range(6))
    checked(['ffmpeg','-nostdin','-v','error','-y','-f','lavfi','-i','testsrc2=s=640x360:r=60:d=2',
             '-f','lavfi','-i',f'aevalsrc={waves}:s=48000:d=2:c=5.1','-c:v','libx264','-threads','2','-c:a','pcm_f32le',str(source)])
    out=root/'mlt-audio'
    checked([sys.executable,str(ROOT/'experiments/mlt/direct.py'),str(tools/'shotcut/Shotcut'),str(out),str(source),
             '--width','640','--frames','120','--audio','--channels','6','--audio-dump'],log=root/'mlt-audio.log')
    audio=np.fromfile(out/'audio.f32',np.float32).reshape(-1,6)
    reference=np.frombuffer(checked(['ffmpeg','-v','error','-i',str(source),'-map','0:a:0','-c:a','pcm_f32le','-f','f32le','-']),np.float32).reshape(-1,6)
    assert audio.shape==reference.shape==(96000,6),audio.shape
    per_channel=np.sqrt(np.mean(audio.astype(float)**2,axis=0))
    assert np.all(per_channel>.03),per_channel
    mae=float(np.mean(np.abs(audio-reference)))
    assert mae<.001,mae
    result={'native_ramp':{'distinct_luma_values':unique,'mean_error_normalized':error},
            'native_high_bit_controls':controls,
            'mlt_rgba64_ramp':{'distinct_luma_values':mlt_unique,'mean_error_normalized':mlt_error},
            'mlt_six_channel':{'frames':120,'sample_frames':len(audio),'channels':6,'mean_absolute_pcm_error':mae,'rms_per_channel':per_channel.tolist()},
            'hdr_management_qualified':False,'atmos_qualified':False}
    (root/'precision-audio.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('results',type=Path);main(p.parse_args())
