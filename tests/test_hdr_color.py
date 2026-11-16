import copy,json,subprocess,tempfile,unittest
from pathlib import Path
import numpy as np
import color_management as color,hdr_render,render_engine as engine,server,preview_dependencies

CONTRACT={'version':1,'workingSpace':color.WORKING,'output':'hdr10','sdrWhiteNits':100,
 'mastering':{'primaries':[[.708,.292],[.170,.797],[.131,.046]],'whitePoint':[.3127,.3290],'minLuminance':.005,'maxLuminance':1000},'maxCLL':1000,'maxFALL':400}

def run(cmd):return subprocess.run(cmd,check=True,capture_output=True)
def source(root,name,nits=100,width=128,height=72,ramp=False,sdr=False,rgb=None):
 path=root/(name+'.mkv');raw=root/(name+'.yuv')
 values=np.linspace(64,940,width).round() if ramp else np.full(width,940 if sdr else round(64+876*float(color.nits_to_pq(nits))))
 y=np.tile(values,(height,1)).astype('<u2');uv=np.full_like(y,512);raw.write_bytes(y.tobytes()+uv.tobytes()+uv.tobytes())
 if rgb is not None:
  r,g,b=np.asarray(rgb) if sdr else color.nits_to_pq(rgb);kr,kb=(.2126,.0722) if sdr else (.2627,.0593);yy=kr*r+(1-kr-kb)*g+kb*b
  raw.write_bytes(b''.join(np.full((height,width),round(v),dtype='<u2').tobytes() for v in (64+876*yy,512+896*(b-yy)/(2*(1-kb)),512+896*(r-yy)/(2*(1-kr)))))
 tags=['-color_primaries','bt709' if sdr else 'bt2020','-color_trc','bt709' if sdr else 'smpte2084','-colorspace','bt709' if sdr else 'bt2020nc','-color_range','tv']
 params='setsar=1,setparams=range=limited:color_primaries='+('bt709:color_trc=bt709:colorspace=bt709' if sdr else 'bt2020:color_trc=smpte2084:colorspace=bt2020nc')
 run(['ffmpeg','-v','error','-y','-stream_loop','11','-f','rawvideo','-pixel_format','yuv444p10le','-video_size',f'{width}x{height}','-framerate','24','-i',str(raw),'-frames:v','12','-vf',params,'-c:v','libx265','-preset','ultrafast','-x265-params','lossless=1:pools=1:frame-threads=1',*tags,str(path)])
 return dict(id=name,kind='video',name=path.name,path=str(path),size=path.stat().st_size,**server.probe(path))
def project(assets,width=128,height=72):
 s=server.default_state();s['assets']=assets;s['output'].update(width=width,height=height,fps=24,encoder='libx265',crf=15,preset='ultrafast',color=copy.deepcopy(CONTRACT))
 s['tracks']=[]
 for n,a in enumerate(assets):
  c=server.default_clip(a);c.update(end=.5,opacity=.5 if n==0 and len(assets)>1 else 1)
  s['tracks'].append({'id':'t'+str(n),'type':'video','name':'V','volume':1,'clips':[c]})
 return s
def probe(path):return json.loads(run(['ffprobe','-v','error','-show_streams','-show_frames','-of','json',str(path)]).stdout)
def decoded_y(path,w,h):
 b=run(['ffmpeg','-v','error','-i',str(path),'-frames:v','1','-pix_fmt','yuv444p10le','-f','rawvideo','pipe:1']).stdout
 return np.frombuffer(b,dtype='<u2')[:w*h].reshape(h,w)

class ColorContractTests(unittest.TestCase):
 def test_pq_reference_values_and_roundtrip(self):
  n=np.array([0,.005,.1,1,100,203,1000,10000]);v=color.nits_to_pq(n)
  np.testing.assert_allclose(color.pq_to_nits(v),n,atol=1e-7);self.assertAlmostEqual(float(color.nits_to_pq(100)),.5080784215,places=9)
  for v in [float('nan'),-1,10001]:
   with self.assertRaises(ValueError):color.nits_to_pq(v)
 def test_contract_rejects_false_hdr10plus_and_invalid_metadata(self):
  for change in [{'output':'hdr10plus'},{'workingSpace':'8bit'},{'maxFALL':1001},{'maxCLL':float('nan')}]:
   with self.assertRaises(ValueError):color.validate_output({**CONTRACT,**change})
 def test_source_detection_does_not_infer_hdr10plus_from_ten_bit(self):
  m=color.metadata({'pix_fmt':'yuv420p10le','color_transfer':'smpte2084'})
  self.assertEqual(m['bitDepth'],10);self.assertFalse(m['dynamicHDR10PlusDetected'])
  m=color.metadata({'pix_fmt':'p010le'}, {'best_effort_timestamp':123,'side_data_list':[{'side_data_type':'HDR Dynamic Metadata SMPTE2094-40 (HDR10+)','application_version':1},{'side_data_type':'User Data Unregistered SEI message','private':'not-published'}]})
  self.assertTrue(m['dynamicHDR10PlusDetected']);self.assertEqual(len(m['sideData']),1);self.assertEqual(m['framePTS'],123)
 def test_project_roundtrip_and_preview_cache_bind_color_and_originals(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);a=source(root,'round');s=project([a]);s['tracks'][0]['clips'][0].update(inputColor={'profile':'pq2020','range':'limited'},hdrExposure=.5)
   v=server.validate_state(s,s);self.assertEqual(v['output']['color'],CONTRACT);self.assertEqual(v['tracks'][0]['clips'][0]['inputColor'],s['tracks'][0]['clips'][0]['inputColor'])
   restored=server.validate_state(json.loads(json.dumps(v)),v);self.assertEqual(v,restored)
   k,p=preview_dependencies.project(v,0,12,128);self.assertEqual(p['output']['color'],CONTRACT)
   v['output']['color']['sdrWhiteNits']=203;self.assertNotEqual(k,preview_dependencies.project(v,0,12,128)[0])
 def test_unknown_color_and_unsupported_effects_fail_before_encoding(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);s=project([source(root,'gates')]);c=s['tracks'][0]['clips'][0]
   for key,value in [('mask','ellipse'),('x',.1),('grade','warm'),('rotation',1),('brightness',.1)]:
    old=c.get(key);c[key]=value
    with self.assertRaises(ValueError):hdr_render.command(s,0,.5,root/'out.mov',root)
    if old is None:c.pop(key)
    else:c[key]=old
   s['assets'][0]['colorTransfer']='unknown'
   with self.assertRaises(ValueError):hdr_render.command(s,0,.5,root/'out.mov',root)
   c['inputColor']={'profile':'pq2020','range':'limited'};hdr_render.command(s,0,.5,root/'out.mov',root)
 def test_missing_pixel_aspect_needs_explicit_override_and_future_profiles_survive(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);s=project([source(root,'par')]);a=s['assets'][0];a['sampleAspectRatio']='unknown';c=s['tracks'][0]['clips'][0]
   with self.assertRaises(ValueError):hdr_render.command(s,0,.5,root/'out.mov',root)
   c['inputColor']={'profile':'source','range':'auto','pixelAspect':'square'};hdr_render.command(s,0,.5,root/'out.mov',root)
   for profile in ('hlg2020','samsung-log'):
    c['inputColor']={'profile':profile,'range':'limited'};restored=server.validate_state(s,s);self.assertEqual(restored['tracks'][0]['clips'][0]['inputColor']['profile'],profile)
    with self.assertRaises(ValueError):hdr_render.command(s,0,.5,root/'out.mov',root)

class HDRDecodedTests(unittest.TestCase):
 def test_known_primary_conversion_and_colored_hdr_luminance(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder)
   # zimg display-referred REC_709 selects ideal-black BT.1886, not inverse camera OETF.
   for label,asset,expected,tolerance in [('red709',source(root,'red709',sdr=True,rgb=[1,0,0]),np.array([.627404,.069097,.016391])*100,2),('gray709',source(root,'gray709',sdr=True,rgb=[.5,.5,.5]),np.full(3,.5**2.4*100),1),('colorPQ',source(root,'colorPQ',rgb=[1000,100,10]),np.array([1000,100,10]),18)]:
    s=project([asset]);out=root/(label+'.mp4');engine.render(s,out,root/(label+'job'))
    data=run(['ffmpeg','-v','error','-i',str(out),'-frames:v','1','-pix_fmt','yuv444p10le','-f','rawvideo','pipe:1']).stdout
    planes=np.frombuffer(data,dtype='<u2').reshape(3,72,128).mean(axis=(1,2));y=(planes[0]-64)/876;cb=(planes[1]-512)/896;cr=(planes[2]-512)/896
    r=y+2*(1-.2627)*cr;b=y+2*(1-.0593)*cb;g=(y-.2627*r-.0593*b)/(1-.2627-.0593)
    got=color.pq_to_nits(np.clip([r,g,b],0,1));self.assertLess(np.max(abs(got-expected)),tolerance,(label,got,expected))
 def test_vfr_held_frame_trim_uses_source_timestamps(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);raw=root/'vfr.yuv';values=[100,500,1000]
   raw.write_bytes(b''.join(np.full((72,128),round(64+876*float(color.nits_to_pq(n))),dtype='<u2').tobytes()+np.full((2,72,128),512,dtype='<u2').tobytes() for n in values))
   path=root/'vfr.mkv';run(['ffmpeg','-v','error','-y','-f','rawvideo','-pixel_format','yuv444p10le','-video_size','128x72','-framerate','10','-i',str(raw),'-vf','setpts=if(eq(N\,0)\,0\,if(eq(N\,1)\,2\,5)),setsar=1,setparams=range=limited:color_primaries=bt2020:color_trc=smpte2084:colorspace=bt2020nc','-fps_mode','vfr','-c:v','libx265','-preset','ultrafast','-x265-params','lossless=1:pools=1:frame-threads=1',str(path)])
   a=dict(id='vfr',kind='video',name='vfr',path=str(path),**server.probe(path));s=project([a]);s['output']['fps']=30;s['tracks'][0]['clips'][0].update(start=.1,end=.6)
   out=root/'trim.mp4';engine.render(s,out,root/'job');data=run(['ffmpeg','-v','error','-i',str(out),'-pix_fmt','yuv444p10le','-f','rawvideo','pipe:1']).stdout
   frames=np.frombuffer(data,dtype='<u2').reshape(-1,3,72,128);self.assertEqual(len(frames),15)
   got=color.pq_to_nits((frames[:,0].mean(axis=(1,2))-64)/876);np.testing.assert_allclose(got,[100]*3+[500]*9+[1000]*3,rtol=.03,atol=4)
   s['tracks'][0]['clips'][0]['speed']=2;fast=root/'speed.mp4';engine.render(s,fast,root/'speedjob')
   raw=run(['ffmpeg','-v','error','-i',str(fast),'-pix_fmt','yuv444p10le','-f','rawvideo','pipe:1']).stdout
   f=np.frombuffer(raw,dtype='<u2').reshape(-1,3,72,128);self.assertEqual(len(f),8)
   got=color.pq_to_nits((f[:,0].mean(axis=(1,2))-64)/876);np.testing.assert_allclose(got,[100]*2+[500]*4+[1000]*2,rtol=.03,atol=4)
 def test_right_angle_orientation_preserves_float32_pixel_values(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);asset=source(root,'rot',ramp=True)
   for angle,w,h in [(-90,72,128),(90,72,128),(180,128,72)]:
    s=project([copy.deepcopy(asset)]);s['assets'][0]['rotation']=angle;s['output'].update(width=w,height=h)
    out=root/(str(angle)+'.mp4');engine.render(s,out,root/('rotjob'+str(angle)));p=probe(out);v=next(x for x in p['streams'] if x['codec_type']=='video');self.assertEqual((v['width'],v['height']),(w,h))
    self.assertFalse(any(x['side_data_type']=='Display Matrix' for f in p['frames'] for x in f.get('side_data_list',[])))
    y=decoded_y(out,w,h).mean(axis=1 if w==72 else 0);expected=np.linspace(64,940,128).round()
    if angle!=-90:expected=expected[::-1]
    self.assertLess(np.max(abs(y-expected)),10)
 def test_unknown_mastering_does_not_invent_display_or_content_light_values(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);s=project([source(root,'unknown')]);s['output']['color']={k:v for k,v in CONTRACT.items() if k not in ('mastering','maxCLL','maxFALL')}
   out=root/'unknown.mp4';engine.render(s,out,root/'job');frames=probe(out)['frames']
   for f in frames:
    for side in f.get('side_data_list',[]):
     self.assertNotEqual(side['side_data_type'],'Mastering display metadata')
     if side['side_data_type']=='Content light level metadata':self.assertEqual((side['max_content'],side['max_average']),(0,0))
 def test_real_main10_ramp_metadata_and_exact_frame_audio_counts(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);s=project([source(root,'ramp',width=1024,height=32,ramp=True)],1024,32)
   s['output']['color']['mastering']['maxLuminance']=10000;s['output']['color']['maxCLL']=10000
   fall=round(float(np.mean(color.pq_to_nits((np.linspace(64,940,1024).round()-64)/876))));s['output']['color']['maxFALL']=fall
   target=root/'HDR10.mp4';engine.render(s,target,root/'job');p=probe(target);v=next(x for x in p['streams'] if x['codec_type']=='video')
   self.assertEqual((v['pix_fmt'],v['color_primaries'],v['color_transfer'],v['color_space']),('yuv420p10le','bt2020','smpte2084','bt2020nc'))
   frames=[x for x in p['frames'] if x['media_type']=='video'];self.assertEqual(len(frames),12)
   side=frames[0]['side_data_list'];master=next(x for x in side if x['side_data_type']=='Mastering display metadata');self.assertEqual(float(color.Fraction(master['max_luminance'])),10000);self.assertEqual(float(color.Fraction(master['min_luminance'])),.005);cll=next(x for x in side if x['side_data_type']=='Content light level metadata');self.assertEqual((cll['max_content'],cll['max_average']),(10000,fall))
   self.assertFalse(any('2094' in x['side_data_type'] for x in side))
   y=decoded_y(target,1024,32);expected=np.linspace(64,940,1024).round();self.assertLess(np.max(abs(y[16].astype(float)-expected)),8)
   self.assertGreater(len(np.unique(y[16])),700)
   self.assertAlmostEqual(float(frames[-1]['pts_time'])+float(frames[-1]['duration_time']),.5,places=5)
   pcm=run(['ffmpeg','-v','error','-i',str(target),'-map','0:a','-acodec','pcm_s16le','-f','s16le','pipe:1']).stdout
   # AAC may include padded final samples; timestamps define intended presentation duration.
   audio=next(x for x in p['streams'] if x['codec_type']=='audio');self.assertAlmostEqual(float(audio['duration']),.5,places=5);self.assertGreaterEqual(len(pcm)//4,24000)
 def test_fractional_rate_cuts_nested_tracks_fades_and_linear_exposure(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);a=source(root,'fraction',100);s=project([a]);s['output']['fps']='30000/1001';c=s['tracks'][0]['clips'][0];c.update(hdrExposure=1,fadeIn=.1)
   c2=copy.deepcopy(c);c2.update(id='second',position=.2,start=.2,end=.5,fadeIn=0)
   c['end']=.2;s['tracks'][0]['clips'].append(c2)
   children=s['tracks'];s['tracks']=[{'id':'outer','type':'video','clips':[{'id':'nest','kind':'sequence','children':children,'position':0}]}]
   out=root/'rational.mp4';engine.render(s,out,root/'work');p=probe(out);v=next(x for x in p['streams'] if x['codec_type']=='video');audio=next(x for x in p['streams'] if x['codec_type']=='audio')
   self.assertEqual(v['r_frame_rate'],'30000/1001');self.assertEqual(sum(x['media_type']=='video' for x in p['frames']),15)
   self.assertLessEqual(abs(float(v['duration'])-.5005),1/120000)
   self.assertLessEqual(abs(float(audio['duration'])-.5005),1/48000)
   b=run(['ffmpeg','-v','error','-i',str(out),'-vf','select=eq(n\\,10)','-frames:v','1','-pix_fmt','yuv444p10le','-f','rawvideo','pipe:1']).stdout
   y=float(np.median(np.frombuffer(b,dtype='<u2')[:128*72]));self.assertLess(abs(float(color.pq_to_nits((y-64)/876))-200),8)
 def test_linear_opacity_blend_and_sdr_input_reference_white(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder)
   sdr=source(root,'sdr',sdr=True);eight=root/'sdr8.mp4';run(['ffmpeg','-v','error','-y','-i',sdr['path'],'-vf','format=yuv420p,setparams=range=limited:color_primaries=bt709:color_trc=bt709:colorspace=bt709','-c:v','libx264','-preset','ultrafast',str(eight)])
   sdr8=dict(id='eight',kind='video',name='SDR8',path=str(eight),**server.probe(eight));self.assertEqual(sdr8['colorMetadata']['bitDepth'],8)
   pq=source(root,'pq',1000)
   for label,assets,expected in [('pq',[source(root,'high',1000),source(root,'low',100)],550),('mixed',[sdr,pq],550),('mixed8',[sdr8,pq],550)]:
    s=project(assets);out=root/(label+'.mp4');engine.render(s,out,root/label)
    y=float(np.median(decoded_y(out,128,72)));n=float(color.pq_to_nits((y-64)/876));self.assertLess(abs(n-expected),16,(label,n))
   s=project([assets[-1]]);s['tracks'][0]['clips'][0]['keys']={'opacity':[{'time':0,'value':0,'mode':'linear'},{'time':.5,'value':1,'mode':'linear'}]};out=root/'opacity-keys.mp4';engine.render(s,out,root/'keyjob')
   raw=run(['ffmpeg','-v','error','-i',str(out),'-pix_fmt','yuv444p10le','-f','rawvideo','pipe:1']).stdout;f=np.frombuffer(raw,dtype='<u2').reshape(-1,3,72,128)
   self.assertLessEqual(int(f[0,0].max()),66);n=float(color.pq_to_nits((float(f[6,0].mean())-64)/876));self.assertLess(abs(n-500),16)
 def test_tone_mapped_monitor_is_sdr_and_not_relabelled_hdr(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);s=project([source(root,'monitor',1000)]);out=root/'monitor.mp4'
   engine.render_range(s,0,.5,out,root,'preview');v=next(x for x in probe(out)['streams'] if x['codec_type']=='video')
   self.assertEqual((v['pix_fmt'],v['color_transfer'],v['color_primaries']),('yuv420p','bt709','bt709'))
