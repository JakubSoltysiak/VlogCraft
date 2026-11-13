"""Generated native precision and picture parity; hardware required, no private media."""
import argparse,json,os,subprocess,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'benchmarks')]
from engine_profile import scene
import native_plan,render_engine
def checked(args,env=None):
 p=subprocess.run(args,env=env,capture_output=True,timeout=120)
 if p.returncode:raise RuntimeError((p.stdout+p.stderr).decode(errors='replace')[-2000:])
 return p.stdout
def main(a):
 root=a.results.resolve();root.mkdir(parents=True,exist_ok=True)
 tools=ROOT/'build/tools/architecture';sdk=tools/'ffmpeg-shared/ffmpeg-9.0.2-full_build-shared/bin'
 env=dict(os.environ,PATH=str(sdk)+os.pathsep+os.environ['PATH'])
 def native(text,tag,frames=1):
  folder=root/tag;folder.mkdir(exist_ok=True);(folder/'sequence.plan').write_text(text)
  data=checked([str(tools/'VlogCraftNative.exe'),'--plan',str(folder/'sequence.plan'),'--offscreen','--frames',str(frames),'--capture',str(folder/'image')],env)
  metric=json.loads(data.decode().splitlines()[-1]);assert metric['completed_frames']==frames
  return np.fromfile(folder/'image-0.rgba16f',np.float16).reshape(576,1024,4)[:,:,:3].astype(float),metric
 ramp=ROOT/'build/qa/architecture/precision-audio-final/ramp10.mp4'
 assert ramp.is_file(),'Run the existing precision_audio benchmark first'
 original=checked(['ffmpeg','-v','error','-i',str(ramp),'-frames:v','1','-pix_fmt','yuv420p10le','-f','rawvideo','-'])
 expected=(np.frombuffer(original,np.uint16)[:1024*576].reshape(576,1024).astype(float)-64)/876
 def plan(path,color):
  return f'VLOGCRAFT_NATIVE 1\nRATE 24 1\nCANVAS 1024 576\nEND 3\nCOLOR {color}\nSOURCE source\t{path}\nCLIP clip source 0 3 0 1 12288 1 1 0 0 1 0 1 0 0 0 0 1536\n'
 values,metric=native(plan(ramp,'SDR'),'ramp-sdr',3)
 count=int(np.unique(values[288,:,0]).size);mae=float(np.abs(values[:,:,0]-expected).mean())
 assert count>700 and mae<.002,(count,mae)
 pq=root/'pq10.mp4'
 checked(['ffmpeg','-v','error','-y','-i',str(ramp),'-map','0:v','-c:v','libx265','-x265-params','lossless=1:pools=2:frame-threads=1:log-level=error:colorprim=bt2020:transfer=smpte2084:colormatrix=bt2020nc','-color_primaries','bt2020','-color_trc','smpte2084','-colorspace','bt2020nc',str(pq)])
 values,_=native(plan(pq,'PQ'),'ramp-pq',3)
 pqmax=float(values.max())
 v=expected.clip(0,1)**(1/78.84375);linear=(np.maximum(v-.8359375,0)/(18.8515625-18.6875*v))**(1/.1593017578125)*125
 relative=float((np.abs(values[:,:,0]-linear)/(1+linear)).mean());pqcount=int(np.unique(values[288,:,0]).size)
 assert np.isfinite(values).all() and values.max()>100 and pqcount>700 and relative<.002,(relative,pqcount)
 # Use the actual editor compiler and production renderer for transformed, layered SDR.
 sources=[]
 for i,color in enumerate(('red','green','blue')):
  path=root/f'solid{i}.mp4'
  checked(['ffmpeg','-v','error','-y','-f','lavfi','-i',f'color={color}:s=1024x576:r=24:d=0.125','-c:v','libx264','-threads','1',str(path)])
  sources.append(path)
 s=scene(sources,.125,1024,3)
 for track in s['tracks']:
  track['clips'][0]['keys']={'rotation':[{'time':0,'value':-5,'mode':'linear'},{'time':.125,'value':5,'mode':'linear'}]}
 s['output'].update(width=1024,height=576,fps=24,preset='ultrafast')
 # Native monitor compiler permits enumerated widths; use text canvas 1024 solely in this fixture.
 p=native_plan.compile_plan(s,960);p['text']=p['text'].replace('CANVAS 960 540','CANVAS 1024 576')
 values,_=native(p['text'],'layers')
 work=root/'reference';work.mkdir(exist_ok=True);target=root/'reference.mov'
 render_engine.render_range(s,0,.125,target,work)
 rgb=checked(['ffmpeg','-v','error','-i',str(target),'-frames:v','1','-pix_fmt','rgb24','-f','rawvideo','-'])
 ref=np.frombuffer(rgb,np.uint8).reshape(576,1024,3).astype(float)/255
 delta=np.abs(values-ref);picture={'mean_absolute_rgb_error':float(delta.mean()),'p95_absolute_rgb_error':float(np.quantile(delta,.95))}
 assert picture['mean_absolute_rgb_error']<.02 and picture['p95_absolute_rgb_error']<.04,picture
 result={'native_10bit':{'distinct_luma_values':count,'mean_error':mae},'native_pq':{'distinct_luma_values':pqcount,'relative_error':relative,'max_scrgb':pqmax},'layer_parity':picture,'full_hdr_display_qualified':False}
 (root/'native-precision.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('results',type=Path);main(p.parse_args())
