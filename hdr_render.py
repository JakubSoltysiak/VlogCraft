"""First managed reference slice: full-canvas float32 linear blends -> HDR10 or SDR monitor."""
import re
from fractions import Fraction
from pathlib import Path
import animation,color_management as color,sequences,timing
from hdr10plus_bitstream import packet_records


def final_clock(files, fps, frames, cancelled):
 """Give the concatenated video a continuous decode clock across closed GOPs."""
 ticks=int(Fraction(120000)/fps)
 if ticks*fps!=120000:raise ValueError('Managed HDR frame rate does not fit the delivery clock')
 seen=bytearray(frames);offset=0
 with packet_records(files,'v:0',input_options=('-f','concat','-safe','0')) as packets:
  for index,packet in enumerate(packets):
   if cancelled():raise RuntimeError('Export cancelled')
   pts=int(packet[b'pts'])
   frame,remainder=divmod(pts,ticks)
   if remainder or not 0<=frame<frames or seen[frame]:
    raise ValueError('Managed HDR segment does not match the output frame clock')
   seen[frame]=1
   offset=max(offset,index*ticks-pts)
 if not all(seen):raise ValueError('Managed HDR segment is missing output pictures')
 return ['-bsf:v',f'setts=pts=PTS:dts=N*{ticks}-{offset}:duration={ticks}:time_base=1/120000']

def layer_contract(assets,c,w,h):
 if c.get('kind')!='video':raise ValueError('Managed HDR currently supports video layers; titles/stills require a qualified HDR implementation')
 a=assets[c['assetId']]
 if any(c.get(k,d)!=d or c.get('keys',{}).get(k) for k,d in [('x',0),('y',0),('scale',1),('rotation',0)]):raise ValueError('Spatial HDR transforms are not yet qualified in the reference compositor')
 angle=(-float(a.get('rotation',0)))%360
 if angle not in (0,90,180,270):raise ValueError('Only exact right-angle source orientation is qualified in managed HDR')
 aw,ah=a.get('width',0),a.get('height',0)
 if angle in (90,270):aw,ah=ah,aw
 square=a.get('sampleAspectRatio') in ('1:1','1/1') or c.get('inputColor',{}).get('pixelAspect')=='square'
 if aw*h!=ah*w or not square:raise ValueError('Managed HDR requires matching oriented aspect and known square pixels; an explicit pixel-aspect override is available')
 if c.get('grade','neutral')!='neutral' or c.get('look') or c.get('lutId') or c.get('chroma') or c.get('mask','none')!='none' or c.get('wipe','none')!='none':raise ValueError('SDR LUTs, masks, keys and wipes cannot be silently applied to HDR')
 if any(c.get(k,d)!=d for k,d in [('brightness',0),('contrast',1),('saturation',1)]) or set(c.get('keys',{}))-{'opacity','volume'}:raise ValueError('Unsupported HDR creative adjustment; use linear exposure')
 return a,angle,color.interpretation(a,c)

def command(state,start,end,target,jobdir,quality='final'):
 import render_engine as engine
 state=sequences.playback(state);o=state['output'];contract=color.validate_output(o['color'])
 w,h=int(o['width']),int(o['height']);fps=timing.rate(o['fps']);first,last=timing.frame_at(start,fps),timing.frame_at(end,fps)
 video,_=engine.active_clips(state,start,end);assets={a['id']:a for a in state['assets']}
 cmd=['ffmpeg','-hide_banner','-nostdin','-loglevel','error','-noauto_conversion_filters','-filter_complex_threads','1','-y',
      '-f','lavfi','-i',f'color=black:s={w}x{h}:r={fps}:d={engine._num(end-start)}']
 linear='zscale=agamma=0:pin=709:tin=709:min=709:rin=limited:p=2020:t=linear:m=gbr:r=full:npl=100,format=gbrpf32le'
 filters=['[0:v]'+linear+'[base0]'];back='base0'
 for n,(_,c) in enumerate(video,1):
  a,angle,(p,t,m,r,profile)=layer_contract(assets,c,w,h)
  at=max(start,float(timing.frame_at(c['position'],fps)/fps));until=min(end,float(timing.frame_at(engine.clip_finish(c),fps)/fps));delay=at-start
  seek=float(c['start'])+max(0,at-float(c['position']))*float(c.get('speed',1))
  cmd+=['-noautorotate'];engine._media_input(cmd,a['path'],'video',seek,c.get('speed',1),end-start,fps,'video')
  orientation={0:'',90:'transpose=clock,',180:'hflip,vflip,',270:'transpose=cclock,'}[angle]
  filters.append(f'[{n}:v]setpts=PTS/{engine._num(c.get("speed",1))},fps={fps}:start_time=0:round=up,'
    f'zscale=agamma=0:pin={p}:tin={t}:min={m}:rin={r}:p=2020:t=linear:m=gbr:r=full:npl=100,format=gbrpf32le,'
    f'{orientation}setsar=1,zscale=agamma=0:w={w}:h={h}:filter=bilinear,format=gbrpf32le,'
    f'trim=end_frame={timing.frame_at(until,fps)-timing.frame_at(at,fps)},setpts=PTS+{engine._num(delay)}/TB[lay{n}]')
  alpha=re.sub(r'\bt\b','T',animation.expression(c,'opacity',start));off=start-c['position']
  if c.get('fadeIn',0):alpha+=f'*min(1,max(0,(T+{engine._num(off)})/{engine._num(c["fadeIn"])}))'
  if c.get('fadeOut',0):alpha+=f'*min(1,max(0,({engine._num(engine.clip_length(c)-off)}-T)/{engine._num(c["fadeOut"])}))'
  gain=2**color.number(c.get('hdrExposure',0),-8,8)*(contract['sdrWhiteNits']/100 if profile=='rec709' else 1)
  filters.append(f"[{back}][lay{n}]blend=all_expr='A*(1-({alpha}))+B*{gain:.12g}*({alpha})':eof_action=pass:repeatlast=0:enable='gte(t,{engine._num(delay)})*lt(t,{engine._num(until-start)})'[base{n}]")
  back=f'base{n}'
 # Picture-dependent/source-master metadata is deliberately removed before fresh signalling.
 tail=',sidedata=mode=delete'
 hdr=contract['output']=='hdr10' and quality=='final'
 if hdr:
  tail+=',zscale=agamma=0:pin=2020:tin=linear:min=gbr:rin=full:p=2020:t=smpte2084:m=2020_ncl:r=limited:npl=100:dither=error_diffusion,format=yuv420p10le'
 else:
  tail+=',zscale=agamma=0:pin=2020:tin=linear:min=gbr:rin=full:p=709:t=linear:m=gbr:r=full,format=gbrpf32le,tonemap=hable:desat=0:peak=100,zscale=agamma=0:pin=709:tin=linear:min=gbr:rin=full:p=709:t=709:m=709:r=limited:npl=100:dither=error_diffusion,format=yuv420p'
 filters.append(f'[{back}]trim=end_frame={last-first}{tail}[finished]')
 script=Path(jobdir)/('hdr_graph_'+Path(target).stem+'.txt');script.write_text(';\n'.join(filters)+'\n',encoding='utf8')
 cmd+=['-/filter_complex',str(script),'-map','[finished]','-an','-frames:v',str(1 if quality=='frame' else last-first),'-r',str(fps)]
 if quality=='frame':
  # PNG requires explicit conversion, never an implicit conversion inside HDR composition.
  cmd.remove('-noauto_conversion_filters');return cmd+['-c:v','png','-threads','1',str(target)]
 if hdr:
  cmd+=['-c:v','libx265','-preset',o.get('preset','medium'),'-crf',str(o.get('crf',20)),'-profile:v','main10','-pix_fmt','yuv420p10le',
        '-x265-params',color.x265_metadata(contract),'-color_primaries','bt2020','-color_trc','smpte2084','-colorspace','bt2020nc','-color_range','tv','-tag:v','hvc1']
  if o.get('bitrate'):cmd+=['-b:v',str(round(o['bitrate']*1000000))]
 else:
  import encoders
  encoder=o.get('encoder','libx264') if quality=='final' else 'libx264'
  cmd+=encoders.options(encoder,'ultrafast' if quality=='preview' else o.get('preset','medium'),26 if quality=='preview' else o.get('crf',20),o.get('bitrate',0) if quality=='final' else 0)
  cmd+=['-pix_fmt','yuv420p','-color_primaries','bt709','-color_trc','bt709','-colorspace','bt709','-color_range','tv']
 return cmd+['-threads','4','-movie_timescale','120000','-video_track_timescale','120000','-movflags','+faststart',str(target)]
