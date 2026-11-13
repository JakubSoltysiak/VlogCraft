"""Conservative contract for the experimental native slice; unsupported ranges use reference."""
from fractions import Fraction
from pathlib import Path
import math,re
import animation,sequences,timing,render_engine
VIDEO_KEYS={'x','y','scale','rotation','opacity'}
class Unsupported(ValueError):pass
def compile_plan(state,width=960):
 state=sequences.playback(state);fps=timing.rate(state['output']['fps'])
 width=int(width)
 if width not in (640,960,1280,1920,3840):raise Unsupported('Choose a supported native monitor size')
 height=width*9//16;assets={a['id']:a for a in state['assets']};clips=[];used={}
 for track in reversed(state['tracks']):
  if track['type']!='video' or track.get('hidden'):continue
  for c in sorted(track['clips'],key=lambda c:c['position']):
   if c['kind']!='video':raise Unsupported('Titles and still pictures require the reference compositor')
   a=assets[c['assetId']]
   if not re.fullmatch(r'[a-zA-Z0-9_/-]+',c['id']) or not re.fullmatch(r'[a-zA-Z0-9_-]+',a['id']):raise Unsupported('Invalid native media identifier')
   if a.get('codec') not in (None,'h264','hevc'):raise Unsupported('This codec requires the reference renderer')
   if str(a.get('pixelFormat','')).startswith(('yuva','rgba','argb','gbrap')):raise Unsupported('Alpha-bearing sources require the reference compositor')
   if c.get('grade','neutral')!='neutral' or c.get('look') or c.get('lutId'):raise Unsupported('Grading and LUTs require the reference compositor')
   if c.get('chroma') or c.get('mask','none')!='none' or c.get('wipe','none')!='none':raise Unsupported('Masks, chroma and wipes require the reference compositor')
   if any(c.get(k,d)!=d for k,d in [('brightness',0),('contrast',1),('saturation',1)]):raise Unsupported('Color effects require the reference compositor')
   if any(p not in VIDEO_KEYS|{'volume'} for p in c.get('keys',{})):raise Unsupported('This effect animation requires the reference compositor')
   if any(k.get('mode')=='bezier' for p,keys in c.get('keys',{}).items() if p in VIDEO_KEYS for k in keys):raise Unsupported('Bezier transform keys require the reference compositor')
   if a.get('colorPrimaries')=='bt2020' and a.get('colorTransfer')!='smpte2084':raise Unsupported('This wide-gamut transfer is not qualified in native mode')
   if a.get('colorTransfer')=='arib-std-b67':raise Unsupported('HLG display transforms are not qualified in native mode')
   if c.get('fit')=='cover' and (c.get('rotation',0) or c.get('keys',{}).get('rotation')):raise Unsupported('Rotated cropped clips require the reference compositor')
   start=timing.frame_at(c['position'],fps);end=timing.frame_at(render_engine.clip_finish(c),fps)
   clips.append((c,a,start,end));used[a['id']]=a
 # Explicit channel policy: no implicit multichannel folding in the new transport.
 _,audio=render_engine.active_clips(state,0,render_engine.sequence_duration(state))
 for t,c in audio:
  a=assets.get(c.get('assetId'),{})
  if a.get('hasAudio') and int(a.get('audioChannels') or 2)>2:raise Unsupported('Native audio currently supports mono/stereo; choose an explicit multichannel policy')
 hdr=any(a.get('hdr') or a.get('colorTransfer')=='smpte2084' for a in used.values())
 if hdr and any(a.get('colorTransfer')!='smpte2084' or a.get('colorPrimaries')!='bt2020' for a in used.values()):raise Unsupported('Mixed HDR/SDR working-space conversion requires the reference compositor')
 events=[]
 for c,a,start,end in clips:
  if end>start:events.extend([(start,1,c,a),(end,-1,c,a)])
 active=[]
 for at,kind,c,a in sorted(events,key=lambda e:(e[0],e[1])):
  if kind<0:active=[x for x in active if x[0]['id']!=c['id']]
  else:
   if len(active)>=3:raise Unsupported('More than three overlapping video layers requires the reference compositor')
   if any(x[1]['id']==a['id'] for x in active):raise Unsupported('Overlapping offsets of the same source require the reference compositor')
   active.append((c,a))
 total=timing.frame_at(render_engine.sequence_duration(state),fps)
 if total<=0:raise Unsupported('Add video before starting native preview')
 lines=['VLOGCRAFT_NATIVE 1',f'RATE {fps.numerator} {fps.denominator}',f'CANVAS {width} {height}',f'END {total}','COLOR '+('PQ' if hdr else 'SDR')]
 for aid,a in used.items():
  path=str(Path(a['path']).resolve())
  if any(ch in path for ch in '\r\n\t'):raise Unsupported('Unsupported source path characters')
  lines.append('SOURCE '+aid+'\t'+path)
 for c,a,start,end in clips:
  base=timing.base_for(a);speed=Fraction(str(c['speed']));rotation=float(a.get('rotation',0))
  fields=[c['id'],a['id'],start,end,timing.nearest(timing.rational(c['start'])/base),base.numerator,base.denominator,speed.numerator,speed.denominator,
          c.get('x',0),c.get('y',0),c.get('scale',1),c.get('rotation',0),c.get('opacity',1),c.get('fadeIn',0),c.get('fadeOut',0),rotation,int(c.get('fit')=='cover'),timing.nearest(timing.rational(c['end'])/base)]
  lines.append('CLIP '+' '.join(map(str,fields)))
  for prop,keys in c.get('keys',{}).items():
   if prop in VIDEO_KEYS:
    for k in keys:lines.append(f"KEY {c['id']} {prop} {k['time']:.12g} {k['value']:.12g} {k['mode']}")
 return {'text':'\n'.join(lines)+'\n','hdr':hdr,'rate':str(fps),'endFrame':total,'width':width,'height':height,
         'colorPolicy':'PQ/scRGB; HDR10+ metadata is retained at decode but not applied/authored' if hdr else 'SDR encoded-domain parity path',
         'audioPolicy':'48 kHz stereo PCM from the reference audio compiler'}
