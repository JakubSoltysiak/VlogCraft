"""Bounded reference color qualification. Only selected technical numbers are public."""
import argparse,copy,json,subprocess,sys,time
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from test_hdr_color import source,project,probe,decoded_y,run
import color_management as color,render_engine as engine,server,project_store
from tools.performance_record import fingerprint,PROTOCOL_FILES

def main(a):
 root=a.results.resolve();root.mkdir(parents=True,exist_ok=True)
 assert not (root/'color-results.json').exists(),'Preserve prior results'
 rows=[];identity=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
 def render(name,s):
  target=root/(name+'.mp4');began=time.perf_counter();engine.render(s,target,root/(name+'-job'));elapsed=time.perf_counter()-began;p=probe(target)
  v=next(x for x in p['streams'] if x['codec_type']=='video');aud=next(x for x in p['streams'] if x['codec_type']=='audio');frames=[x for x in p['frames'] if x['media_type']=='video']
  row={'case':name,'seconds':elapsed,'dimensions':[v['width'],v['height']],'pixel_format':v['pix_fmt'],'profile':v['profile'],'primaries':v.get('color_primaries'),'transfer':v.get('color_transfer'),'matrix':v.get('color_space'),'range':v.get('color_range'),'rate':v['r_frame_rate'],'decoded_video_frames':len(frames),'video_seconds':float(v['duration']),'audio_seconds':float(aud['duration']),'AV_endpoint_difference_seconds':abs(float(v['duration'])-float(aud['duration'])),
       'HDR10Plus_output':any('2094' in x['side_data_type'] for f in frames for x in f.get('side_data_list',[]))}
  assert v['pix_fmt']=='yuv420p10le' and row['transfer']=='smpte2084' and not row['HDR10Plus_output'];rows.append(row);return target,p,row
 ramp=project([source(root,'ramp',width=1024,height=32,ramp=True)],1024,32);ramp['output']['color']['mastering']['maxLuminance']=10000;ramp['output']['color']['maxCLL']=10000
 expected=np.linspace(64,940,1024).round();fall=round(float(np.mean(color.pq_to_nits((expected-64)/876))));ramp['output']['color']['maxFALL']=fall
 target,p,row=render('PQ-ramp',ramp);y=decoded_y(target,1024,32)[16];row.update(distinct_decoded_luma_codes=int(len(np.unique(y))),max_luma_code_error=float(abs(y.astype(float)-expected).max()),declared_MaxCLL=10000,declared_MaxFALL=fall,static_metadata_verified=True)
 assert row['distinct_decoded_luma_codes']>700 and row['max_luma_code_error']<8
 s=project([source(root,'pq1000',1000),source(root,'pq100',100)]);out,_,row=render('linear-PQ-blend',s);row['decoded_nits']=float(color.pq_to_nits((float(np.median(decoded_y(out,128,72)))-64)/876));row['expected_nits']=550;assert abs(row['decoded_nits']-550)<16
 s=project([source(root,'SDR-white',sdr=True),source(root,'PQ-white',1000)]);out,_,row=render('mixed-SDR-PQ',s);row['decoded_nits']=float(color.pq_to_nits((float(np.median(decoded_y(out,128,72)))-64)/876));row['expected_nits']=550;assert abs(row['decoded_nits']-550)<16
 if a.camera_manifest:
  originals=json.loads(a.camera_manifest.read_text('utf8'))
  for n,original in enumerate(originals[:2]):
   asset=dict(id='cam'+str(n),kind='video',name='Private original',path=original['path'],**server.probe(Path(original['path'])))
   angle=abs(asset.get('rotation',0))%180;w,h=(144,256) if angle==90 else (256,144)
   s=project([asset],w,h);s['output'].update(fps=60,preset='ultrafast');s['output']['color']={k:v for k,v in s['output']['color'].items() if k not in ('mastering','maxCLL','maxFALL')};s['tracks'][0]['clips'][0].update(end=.2,inputColor={'profile':'source','range':'auto','pixelAspect':'square'})
   out,p,row=render('Camera'+chr(65+n)+'-bounded-HDR10',s);assert row['decoded_video_frames']==12 and row['AV_endpoint_difference_seconds']<1/48000
   row['source_dynamic_sample_detected']=asset['colorMetadata']['dynamicHDR10PlusDetected'];row['static_metadata_scope']='Unknown output mastering/content levels omitted; source dynamic/static picture metadata not copied'
   row['pixel_aspect_scope']='Source SAR unspecified; explicit square-pixel interpretation selected for this bounded test, not verified camera SAR metadata'
   # Store private source associations only in the ignored local project, and verify exact persistence.
   checked=server.validate_state(s,s);path=root/('private-project-'+str(n)+'.json');project_store.save(path,checked,lambda d:server.validate_state(d,checked));restored,_=project_store.load(path,lambda d:server.validate_state(d,checked));assert restored==checked
 result={'source_commit':identity,'source_fingerprint':fingerprint(),'protocol_fingerprint':fingerprint(PROTOCOL_FILES),'source_dirty':bool(subprocess.check_output(['git','status','--porcelain'])),
 'working':'float32 linear Rec.2020,1.0=100cd/m²','rows':rows,'scope':'Short reference precision and bounded real-camera HDR10 output; no calibrated display, sustained 4K60 or HDR10+ authoring acceptance. Private paths/frames and complete metadata stay local.'}
 (root/'color-results.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('results',type=Path);p.add_argument('--camera-manifest',type=Path);main(p.parse_args())
