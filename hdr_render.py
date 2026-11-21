"""First managed reference slice: full-canvas float32 linear blends -> HDR10 or SDR monitor."""
from fractions import Fraction
from pathlib import Path
import animation,color_management as color,sequences,timing
from hdr10plus_bitstream import packet_records
import hdr_layers


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
 if c.get('grade','neutral')!='neutral' or c.get('look') or c.get('lutId') or c.get('chroma') or c.get('wipe','none')!='none':
  raise ValueError('Managed HDR does not support this grade, LUT, chroma key or clip wipe')
 if c.get('brightness',0)!=0 or set(c.get('keys',{}))-{'opacity','volume','scale','rotation','x','y','maskRadius','contrast','saturation'}:
  raise ValueError('Unsupported HDR creative adjustment; use linear exposure')
 if c.get('mask','none') not in ('none','ellipse','rectangle'):
  raise ValueError('Unsupported managed HDR mask')
 kind=c.get('kind')
 if kind=='title':
  return None,(w,h),'',hdr_layers.SRGB
 a=assets[c['assetId']]
 if kind=='image':
  if c.get('inputColor') or Path(a['path']).suffix.lower() not in hdr_layers.STILL_SUFFIXES:
   raise ValueError('Managed HDR photographs use sRGB PNG or JPEG')
  aw,ah,orientation=hdr_layers.photo_info(a['path'])
  return a,(aw,ah),orientation,hdr_layers.SRGB
 if kind!='video':raise ValueError('Unsupported layer in managed HDR')
 angle=(-float(a.get('rotation',0)))%360
 if angle not in hdr_layers.VIDEO_ORIENTATION:raise ValueError('Only exact right-angle source orientation is qualified in managed HDR')
 aw,ah=a.get('width',0),a.get('height',0)
 if angle in (90,270):aw,ah=ah,aw
 square=a.get('sampleAspectRatio') in ('1:1','1/1') or c.get('inputColor',{}).get('pixelAspect')=='square'
 if min(aw,ah)<=0 or not square:raise ValueError('Managed HDR requires known square source pixels; an explicit pixel-aspect override is available')
 return a,(aw,ah),hdr_layers.VIDEO_ORIENTATION[angle],color.interpretation(a,c)

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
  a,source,orientation,(p,t,m,r,profile)=layer_contract(assets,c,w,h)
  at=max(start,float(timing.frame_at(c['position'],fps)/fps));until=min(end,float(timing.frame_at(engine.clip_finish(c),fps)/fps));delay=at-start
  seek=float(c['start'])+max(0,at-float(c['position']))*float(c.get('speed',1))
  still=c.get('kind') in ('image','title')
  path=hdr_layers.title_image(c,w,h,jobdir) if a is None else a['path']
  cmd+=['-noautorotate'];engine._media_input(cmd,path,'image' if still else 'video',seek,c.get('speed',1),end-start,fps,'video')
  transform=hdr_layers.uses_geometry(c)
  has_mask=c.get('mask','none')!='none'
  adjusted=any(c.get(key,1)!=1 or c.get('keys',{}).get(key) for key in ('contrast','saturation'))
  spatial=still or transform or has_mask or adjusted or source[0]*h!=source[1]*w
  local_first,local_last=timing.frame_at(at,fps),timing.frame_at(until,fps)
  count=local_last-local_first
  alpha_start=at if spatial else start
  alpha=hdr_layers.parameter(c,'opacity',1,alpha_start);off=alpha_start-c['position']
  if c.get('fadeIn',0):alpha+=f'*min(1,max(0,(T+{engine._num(off)})/{engine._num(c["fadeIn"])}))'
  if c.get('fadeOut',0):alpha+=f'*min(1,max(0,({engine._num(engine.clip_length(c)-off)}-T)/{engine._num(c["fadeOut"])}))'
  gain=2**color.number(c.get('hdrExposure',0),-8,8)*(contract['sdrWhiteNits']/100 if profile in ('rec709','srgb') else 1)
  cadence=f'setpts=PTS/{engine._num(c.get("speed",1))},fps={fps}:start_time=0:round=up,'
  convert=hdr_layers.luma_linear(p,t,m,r)
  oriented=(orientation+',' if orientation else '')+'setsar=1'
  if spatial:
   input_chain=(hdr_layers.linear_still(filters,n,convert) if still else
                f'[{n}:v]{cadence}{convert},format=gbrapf32le')
   chain=input_chain+f',{oriented},premultiply=inplace=1'
   chain=hdr_layers.canvas_fit(filters,chain,f'fit{n}',source=source,canvas=(w,h),fit=c.get('fit','contain'),fps=fps)
   if still:
    chain+=f',loop=loop={max(0,count-1)}:size=1:start=0,setpts=N/({fps}*TB)'
   if has_mask:chain+=','+hdr_layers.soft_mask(c,at)
   if transform:chain+=','+hdr_layers.transform(c,at)
   chain+=',unpremultiply=inplace=1,'+hdr_layers.matte_expression(c,at,alpha,gain)
   chain+=f',trim=end_frame={count},setpts=PTS-STARTPTS'
   if local_first>first or local_last<last:
    chain+=f',tpad=start={local_first-first}:start_mode=clone:stop={last-local_last}:stop_mode=clone'
   hdr_layers.picture_alpha(filters,chain+f'[raw{n}];[raw{n}]',f'lay{n}',n)
   filters.append(f"[{back}][lay{n}][lay{n}mask]maskedmerge=enable='gte(n,{local_first-first})*lt(n,{local_last-first})'[base{n}]")
  else:
   filters.append(f'[{n}:v]{cadence}{convert},format=gbrpf32le,'
    f'{oriented},zscale=agamma=0:w={w}:h={h}:filter=bilinear,format=gbrpf32le,'
    f'trim=end_frame={count},setpts=PTS+{engine._num(delay)}/TB[lay{n}]')
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
