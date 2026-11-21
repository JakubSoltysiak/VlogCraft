"""Alpha-bearing layers for the float32 linear Rec.2020 reference compositor."""
from functools import lru_cache
import hashlib
import io
import os
from pathlib import Path
import re

from PIL import Image, ImageCms, ImageDraw, ImageFont

import animation


FLOAT_ALPHA = 'gbrapf32le'
SRGB = ('bt709','iec61966-2-1','gbr','full','srgb')
STILL_SUFFIXES = {'.png','.jpg','.jpeg'}
EXIF_ORIENTATION = {
    1:'',2:'hflip',3:'hflip,vflip',4:'vflip',
    5:'transpose=clock,hflip',6:'transpose=clock',7:'transpose=clock,vflip',8:'transpose=cclock',
}
VIDEO_ORIENTATION = {0:'',90:'transpose=clock',180:'hflip,vflip',270:'transpose=cclock'}
GEOMETRY = {'x':0,'y':0,'scale':1,'rotation':0}
TITLE_FONTS = {'segoe':'segoeui.ttf','arial':'arial.ttf','georgia':'georgia.ttf'}


def parameter(clip, name, initial, start):
    return re.sub(r'\bt\b','T',animation.expression({name:initial,**clip},name,start))


def uses_geometry(clip):
    return any(clip.get(key,initial)!=initial or clip.get('keys',{}).get(key)
               for key,initial in GEOMETRY.items())


def photo_info(path):
    stat=Path(path).stat()
    return _photo_info(path,stat.st_size,stat.st_mtime_ns)


@lru_cache(maxsize=128)
def _photo_info(path, size, modified):
    with Image.open(path) as photo:
        if photo.format not in ('PNG','JPEG') or getattr(photo,'is_animated',False):
            raise ValueError('Managed HDR stills require a single PNG or JPEG picture')
        if photo.mode=='CMYK':
            raise ValueError('Convert CMYK stills to sRGB before using them in managed HDR')
        profile=photo.info.get('icc_profile')
        if profile:
            try:
                detail=ImageCms.getProfileDescription(ImageCms.ImageCmsProfile(io.BytesIO(profile))).strip()
            except (OSError,ValueError) as error:
                raise ValueError('The photograph has an unreadable color profile') from error
            if 'srgb' not in detail.lower():
                raise ValueError('Convert this embedded photograph profile to sRGB before managed HDR export')
        gamma=photo.info.get('gamma')
        if (gamma is not None and not profile and 'srgb' not in photo.info
            and abs(gamma-.45455)>.002):
            raise ValueError('This PNG has a non-sRGB gamma declaration')
        orientation=photo.getexif().get(274,1)
        if orientation not in EXIF_ORIENTATION:
            raise ValueError('Unsupported photograph orientation')
        w,h=photo.size
        return (h,w,EXIF_ORIENTATION[orientation]) if orientation>=5 else (w,h,EXIF_ORIENTATION[orientation])


def title_image(clip, width, height, folder):
    text=clip.get('text','')
    size=max(15,int(width*clip.get('fontScale',.048)))
    appearance=(text,width,height,size,clip.get('titleAlign','center'),clip.get('color','white'),
                clip.get('titleFont','segoe'))
    token=hashlib.sha256(repr(appearance).encode()).hexdigest()
    path=Path(folder)/f'hdr-title-{token}.png'
    if path.exists():
        return path
    if os.name=='nt':
        font=ImageFont.truetype(str(Path(os.environ['WINDIR'])/'Fonts'/TITLE_FONTS[appearance[-1]]),size)
    else:
        try:
            font=ImageFont.truetype('DejaVuSans.ttf',size)
        except OSError:
            font=ImageFont.load_default(size=size)
    canvas=Image.new('RGBA',(width,height))
    if text:
        draw=ImageDraw.Draw(canvas)
        left,top,right,bottom=draw.multiline_textbbox((0,0),text,font=font,align='center')
        tw,th=right-left,bottom-top
        x=(width-tw)//2
        y=int(height*.78) if appearance[4]=='lower' else (height-th)//2
        border=round(width*14/1920)
        draw.rectangle((x-border,y-border,x+tw+border,y+th+border),fill=(0,0,0,89))
        # Draw glyph coverage on its own layer so anti-aliased edges preserve
        # the translucent title box underneath.
        glyphs=Image.new('RGBA',canvas.size)
        ImageDraw.Draw(glyphs).multiline_text((x-left,y-top),text,font=font,align='center',fill=appearance[5])
        canvas.alpha_composite(glyphs)
    canvas.save(path)
    return path


def picture_alpha(filters, label, result, number):
    colors=[f'{result}{plane}{number}' for plane in ('r','g','b','a')]
    r,g,b,a=colors
    filters.append(label+'extractplanes=r+g+b+a'+''.join(f'[{plane}]' for plane in colors))
    filters.append(f'[{g}][{b}][{r}]mergeplanes=0x001020:format=gbrpf32le[{result}]')
    duplicates=[f'{a}{item}' for item in range(3)]
    planes=''.join(f'[{item}]' for item in duplicates)
    filters.append(f'[{a}]split=3{planes}')
    filters.append(f'{planes}mergeplanes=0x001020:format=gbrpf32le[{result}mask]')


def linear_still(filters, index, transfer):
    original=f'photo{index}'
    r,g,b,a=[original+plane for plane in 'rgba']
    filters.append(f'[{index}:v]scale=in_range=auto:out_range=full,format=gbrap16le,'
                   f'extractplanes=r+g+b+a[{r}][{g}][{b}][{a}]')
    # zimg's alpha-aware transfer associates straight RGB in its input
    # encoding. Decode RGB independently so linearization precedes premultiply.
    filters.append(f'[{g}][{b}][{r}]mergeplanes=0x001020:format=gbrp16le,'
                   f'{transfer},format=gbrpf32le,extractplanes=r+g+b[{r}32][{g}32][{b}32]')
    filters.append(f'[{a}]scale=in_range=full:out_range=full,format=grayf32le[{original}a32]')
    return f'[{g}32][{b}32][{r}32][{a}32]mergeplanes=0x00102030:format={FLOAT_ALPHA}'


def luma_linear(p,t,m,r):
    return f'zscale=agamma=0:pin={p}:tin={t}:min={m}:rin={r}:p=2020:t=linear:m=gbr:r=full:npl=100'


def canvas_fit(filters, chain, label, *, source, canvas, fit, fps):
    sw,sh=source
    w,h=canvas
    scale=(max if fit=='cover' else min)(w/sw,h/sh)
    rw,rh=max(1,round(sw*scale)),max(1,round(sh*scale))
    if (rw,rh)!=(sw,sh):
        chain+=f',zscale=w={rw}:h={rh}:filter=bilinear,format={FLOAT_ALPHA}'
    if fit=='cover':
        return chain+f',crop={w}:{h}'
    if (rw,rh)==(w,h):
        return chain
    matte=luma_linear(*SRGB[:4])

    def padded(input_label, edges, sizes, horizontal):
        pads=[]
        for suffix,extent in zip(('left','right'),edges):
            if extent:
                ww,hh=sizes(extent)
                name=label+('h' if horizontal else 'v')+suffix
                filters.append(f'color=black@0:s={ww}x{hh}:r={fps},format=gbrap16le,{matte},'
                               f'format={FLOAT_ALPHA}[{name}]')
                pads.append(f'[{name}]')
            else:
                pads.append('')
        sources=pads[0]+f'[{input_label}]'+pads[1]
        filter_name='hstack' if horizontal else 'vstack'
        return sources+f'{filter_name}=inputs={1+sum(map(bool,pads))}:shortest=1'

    original=label+'source'
    filters.append(chain+f'[{original}]')
    if rw<w:
        ahead=(w-rw)//2
        chain=padded(original,(ahead,w-rw-ahead),lambda extent:(extent,rh),True)
        if rh==h:
            return chain
        original=label+'wide'
        filters.append(chain+f'[{original}]')
    ahead=(h-rh)//2
    return padded(original,(ahead,h-rh-ahead),lambda extent:(w,extent),False)


def transform(clip, start):
    scale=parameter(clip,'scale',1,start)
    x=parameter(clip,'x',0,start)
    y=parameter(clip,'y',0,start)
    degrees=parameter(clip,'rotation',0,start)
    # The four planes use exactly the same reverse mapping. Work on
    # premultiplied linear values so transparent edges do not acquire halos.
    angle=f'({degrees})*PI/180'
    setup=(f'st(0,(X-(W-1)/2-W*({x}))/({scale}));'
           f'st(1,(Y-(H-1)/2-H*({y}))/({scale}));'
           f'st(2,cos({angle}));st(3,sin({angle}));'
           'st(4,(W-1)/2+ld(0)*ld(2)+ld(1)*ld(3));'
           'st(5,(H-1)/2-ld(0)*ld(3)+ld(1)*ld(2));')
    inside='between(ld(4),-0.5,W-0.5)*between(ld(5),-0.5,H-0.5)'
    return 'geq='+':'.join(
        f"{name}='{setup}if({inside},{plane}(ld(4),ld(5)),0)'"
        for name,plane in (('r','r'),('g','g'),('b','b'),('a','alpha')))


def soft_mask(clip,start):
    radius=parameter(clip,'maskRadius',.5,start)
    x=f'abs((X+.5)/W-.5)/({radius})'
    y=f'abs((Y+.5)/H-.5)/({radius})'
    distance=f'hypot({x},{y})' if clip['mask']=='ellipse' else f'max({x},{y})'
    mask=f'clip((1-({distance}))/{max(.00001,clip.get("feather",.1)):.12g},0,1)'
    return 'geq='+':'.join(f"{plane}='{fn}(X,Y)*({mask})'"
                           for plane,fn in (('r','r'),('g','g'),('b','b'),('a','alpha')))


def matte_expression(clip, start, alpha, gain):
    contrast=parameter(clip,'contrast',1,start)
    saturation=parameter(clip,'saturation',1,start)
    if contrast=='1' and saturation=='1':
        channels=[f"{p}='{p}(X,Y)*{gain:.12g}'" for p in 'rgb']
    else:
        setup=('st(0,r(X,Y));st(1,g(X,Y));st(2,b(X,Y));'
               'st(3,.2627*ld(0)+.6780*ld(1)+.0593*ld(2));'
               'st(4,min(ld(0),min(ld(1),ld(2))));'
               f'st(5,min(({saturation}),ld(3)/max(1e-12,ld(3)-ld(4))));'
               f'st(6,max(0,.18+(ld(3)*{gain:.12g}-.18)*({contrast})));')
        channels=[f"{p}='{setup}if(gt(ld(3),1e-12),ld(6)*(ld(3)+(ld({i})-ld(3))*ld(5))/ld(3),ld(6))'"
                  for i,p in enumerate('rgb')]
    return 'geq='+':'.join([*channels,f"a='clip(alpha(X,Y)*({alpha}),0,1)'"])
