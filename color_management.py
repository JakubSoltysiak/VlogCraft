"""Versioned, non-destructive technical color interpretation; no creative SDR LUTs."""
import math,re
from fractions import Fraction
import numpy as np

WORKING='linear-rec2020-100nits'
STILL_SRGB_OVERRIDE='srgb'
PROFILES={'rec709':('bt709','bt709','bt709'),'pq2020':('bt2020','smpte2084','bt2020nc'),
          'hlg2020':('bt2020','arib-std-b67','bt2020nc'),'samsung-log':None}
def number(value,low,high):
 if isinstance(value,bool):raise ValueError('Invalid color number')
 try:v=float(value)
 except (ValueError,TypeError):raise ValueError('Invalid color number')
 if not math.isfinite(v) or not low<=v<=high:raise ValueError('Color value outside supported range')
 return v

def validate_input(value):
 if not isinstance(value,dict) or set(value)-{'profile','range','pixelAspect'}:raise ValueError('Invalid technical input transform')
 if value.get('profile') not in {*PROFILES,'source',STILL_SRGB_OVERRIDE} or value.get('range','auto') not in ('auto','limited','full') or value.get('pixelAspect','source') not in ('source','square'):raise ValueError('Unknown technical input transform')
 if value['profile']==STILL_SRGB_OVERRIDE and value.get('range','auto')=='limited':raise ValueError('An sRGB still override requires full range')
 out={'profile':value['profile'],'range':value.get('range','auto')}
 if 'pixelAspect' in value:out['pixelAspect']=value['pixelAspect']
 return out

def validate_output(value):
 if not isinstance(value,dict) or set(value)-{'version','workingSpace','output','sdrWhiteNits','mastering','maxCLL','maxFALL'}:raise ValueError('Invalid color contract')
 if value.get('version')!=1 or value.get('workingSpace')!=WORKING:raise ValueError('Unsupported color contract version/working space')
 if value.get('output')=='hdr10plus':raise ValueError('HDR10+ export requires validated dynamic metadata authoring; no HDR10 downgrade is performed')
 if value.get('output') not in ('sdr','hdr10'):raise ValueError('Unsupported output color space')
 out={'version':1,'workingSpace':WORKING,'output':value['output'],'sdrWhiteNits':number(value.get('sdrWhiteNits',100),80,300)}
 if value.get('mastering') is not None:
  m=value['mastering']
  if not isinstance(m,dict) or set(m)!={'primaries','whitePoint','minLuminance','maxLuminance'}:raise ValueError('Invalid mastering display metadata')
  def xy(p):
   if not isinstance(p,list) or len(p)!=2:raise ValueError('Invalid mastering chromaticity')
   x,y=[number(v,0,1) for v in p]
   if y<=0 or x+y>1.000001:raise ValueError('Invalid mastering chromaticity')
   return [x,y]
  if not isinstance(m['primaries'],list) or len(m['primaries'])!=3:raise ValueError('Three mastering primaries required')
  primaries=[xy(p) for p in m['primaries']];white=xy(m['whitePoint'])
  if abs(np.linalg.det(np.array([[p[0],p[1],1] for p in primaries])))<1e-8:raise ValueError('Degenerate mastering primaries')
  lo=number(m['minLuminance'],0,10);hi=number(m['maxLuminance'],1,10000)
  if lo>=hi:raise ValueError('Mastering minimum must be below maximum')
  out['mastering']={'primaries':primaries,'whitePoint':white,'minLuminance':lo,'maxLuminance':hi}
 for k in ('maxCLL','maxFALL'):
  if value.get(k) is not None:
   v=number(value[k],1,10000)
   if v!=int(v):raise ValueError('Content light levels use integer cd/m²')
   out[k]=int(v)
 if 'maxCLL' in out and 'maxFALL' in out and out['maxFALL']>out['maxCLL']:raise ValueError('MaxFALL exceeds MaxCLL')
 if ('maxCLL' in out)!=('maxFALL' in out):raise ValueError('Provide both content light levels or leave both unknown')
 return out

def interpretation(asset,clip):
 override=clip.get('inputColor')
 if override and override.get('profile')!='source':
  override=validate_input(override);profile=override['profile']
  if profile==STILL_SRGB_OVERRIDE:raise ValueError('The sRGB interpretation override applies to still pictures')
  if PROFILES[profile] is None:raise ValueError('Samsung Log input transform is not implemented; original/profile association is preserved')
  p,t,m=PROFILES[profile];r=override['range']
 else:
  p,t,m=(asset.get(k,'unknown') for k in ('colorPrimaries','colorTransfer','colorSpace'));r=validate_input(override)['range'] if override else 'auto';profile=None
  if (p,t,m) not in [x for x in PROFILES.values() if x]:raise ValueError('Missing/inconsistent source color tags; choose an explicit technical input interpretation')
  profile=next(k for k,v in PROFILES.items() if v==(p,t,m))
 if profile=='hlg2020':raise ValueError('HLG OOTF/display adaptation is not qualified; HLG metadata is preserved but rendering is unsupported')
 if r=='auto':r={'tv':'limited','pc':'full','limited':'limited','full':'full'}.get(asset.get('colorRange'))
 if r is None:raise ValueError('Unknown source color range; choose limited or full explicitly')
 return p,t,m,r,profile

def pq_to_nits(signal):
 v=np.asarray(signal,dtype=np.float64)
 if not np.all(np.isfinite(v)) or np.any((v<0)|(v>1)):raise ValueError('PQ signal outside [0,1]')
 a=v**(32/2523);return 10000*(np.maximum(a-3424/4096,0)/(2413/128-2392/128*a))**(16384/2610)

def nits_to_pq(nits):
 v=np.asarray(nits,dtype=np.float64)
 if not np.all(np.isfinite(v)) or np.any((v<0)|(v>10000)):raise ValueError('PQ luminance outside [0,10000]')
 a=(v/10000)**(2610/16384);return ((3424/4096+2413/128*a)/(1+2392/128*a))**(2523/32)

def bit_depth(pixel,raw=None):
 m=re.search(r'(?:p|gray)(9|10|12|14|16)(?:le|be)$',pixel or '')
 if m:return int(m[1])
 if pixel in ('p010le','p010be'):return 10
 if pixel in ('p016le','p016be','rgb48le','rgb48be','rgba64le','rgba64be'):return 16
 if pixel in ('yuv420p','yuvj420p','yuv422p','yuv444p','nv12','rgb24','bgr24','rgba','bgra'):return 8
 try:return int(raw) if 0<int(raw)<=32 else None
 except (ValueError,TypeError):return None

SIDE_TYPES={'Mastering display metadata','Content light level metadata','HDR Dynamic Metadata SMPTE2094-40 (HDR10+)'}
def metadata(stream,frame=None):
 def clean(v,depth=0):
  if depth>12:raise ValueError('Color metadata nesting limit')
  if isinstance(v,dict):return {k:clean(x,depth+1) for k,x in v.items() if re.fullmatch(r'[a-zA-Z0-9_ ]{1,80}',k)}
  if isinstance(v,list):
   if len(v)>256:raise ValueError('Color metadata array limit')
   return [clean(x,depth+1) for x in v]
  if isinstance(v,(bool,int,float)):
   if isinstance(v,float) and not math.isfinite(v):raise ValueError('Invalid metadata number')
   return v
  if isinstance(v,str) and (v in SIDE_TYPES or re.fullmatch(r'-?\d+(?:/\d+|\.\d+)?',v)):return v
  return None
 side=[clean(d) for d in [*stream.get('side_data_list',[]),*(frame or {}).get('side_data_list',[])] if d.get('side_data_type') in SIDE_TYPES]
 # Preserve provenance and coverage, not a claim that one frame describes a VFR program.
 pixel=stream.get('pix_fmt','unknown')
 return {'version':1,'pixelFormat':pixel,'codecProfile':stream.get('profile','unknown'),'bitDepth':bit_depth(pixel,stream.get('bits_per_raw_sample')),
         'chroma':next((x for x in ('420','422','444') if x in pixel), 'unknown'),
         'primaries':stream.get('color_primaries','unknown'),'transfer':stream.get('color_transfer','unknown'),
         'matrix':stream.get('color_space','unknown'),'range':stream.get('color_range','unknown'),
         'sideData':side,'dynamicHDR10PlusDetected':any(d.get('side_data_type')=='HDR Dynamic Metadata SMPTE2094-40 (HDR10+)' for d in side),
         'coverage':'stream_and_first_decoded_frame' if frame else 'stream_only_first_frame_unavailable','framePTS':(frame or {}).get('best_effort_timestamp'),
         'dynamicAssociation':'original-bitstream; must be re-timed or regenerated after edits; never implicitly copied to output'}

def x265_metadata(contract):
 options=['hdr10=1','repeat-headers=1','pools=2','frame-threads=2']
 if 'mastering' in contract:
  m=contract['mastering'];r,g,b=m['primaries'];w=m['whitePoint']
  xy=lambda p:','.join(str(round(v*50000)) for v in p)
  options.append(f'master-display=G({xy(g)})B({xy(b)})R({xy(r)})WP({xy(w)})L({round(m["maxLuminance"]*10000)},{round(m["minLuminance"]*10000)})')
 if 'maxCLL' in contract:options.append(f'max-cll={contract["maxCLL"]},{contract["maxFALL"]}')
 return ':'.join(options)
