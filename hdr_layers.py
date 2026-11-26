"""Alpha-bearing layers for the float32 linear Rec.2020 reference compositor."""
from functools import lru_cache
import hashlib
import os
from pathlib import Path
import re
import struct

import numpy as np
from PIL import Image, ImageDraw, ImageFont

import animation


FLOAT_ALPHA = 'gbrapf32le'
SRGB = ('bt709','iec61966-2-1','gbr','full','srgb')
DISPLAY_P3 = ('smpte432','iec61966-2-1','gbr','full','display-p3')
STILL_SUFFIXES = {'.png','.jpg','.jpeg'}
EXIF_ORIENTATION = {
    1:'',2:'hflip',3:'hflip,vflip',4:'vflip',
    5:'transpose=clock,hflip',6:'transpose=clock',7:'transpose=clock,vflip',8:'transpose=cclock',
}
VIDEO_ORIENTATION = {0:'',90:'transpose=clock',180:'hflip,vflip',270:'transpose=cclock'}
GEOMETRY = {'x':0,'y':0,'scale':1,'rotation':0}
TITLE_FONTS = {'segoe':'segoeui.ttf','arial':'arial.ttf','georgia':'georgia.ttf'}

# Linear RGB to XYZ relative to D65. ICC colorants are expressed in D50 PCS.
D65 = np.array([.9504559271, 1., 1.0890577508])
D50 = np.array([.9642, 1., .8249])
SRGB_XYZ_D65 = np.array([[.41239080, .35758434, .18048079],
                        [.21263901, .71516868, .07219232],
                        [.01933082, .11919478, .95053215]])
P3_XYZ_D65 = np.array([[.48657095, .26566769, .19821729],
                      [.22897456, .69173852, .07928691],
                      [0., .04511338, 1.04394437]])
D65_TO_D50 = np.array([[1.0478112, .0228866, -.0501270],
                      [.0295424, .9904844, -.0170491],
                      [-.0092345, .0150436, .7521316]])
SRGB_CHROMATICITY = (.3127, .3290, .64, .33, .30, .60, .15, .06)
SRGB_TRC = (2.4, 1/1.055, .055/1.055, 1/12.92, .04045)
ICC_TOLERANCE = .001
P3_PCS_TOLERANCE = .0003


def parameter(clip, name, initial, start):
    return re.sub(r'\bt\b','T',animation.expression({name:initial,**clip},name,start))


def uses_geometry(clip):
    return any(clip.get(key,initial)!=initial or clip.get('keys',{}).get(key)
               for key,initial in GEOMETRY.items())


def still_needs_frame_clock(clip, *, include_opacity=True):
    keys=clip.get('keys',{})
    if any(keys.get(name) for name in (*GEOMETRY, 'maskRadius', 'contrast', 'saturation')):
        return True
    return include_opacity and bool(clip.get('fadeIn') or clip.get('fadeOut') or keys.get('opacity'))


def icc_tags(profile):
    if (len(profile) < 132 or struct.unpack_from('>I',profile)[0] != len(profile) or profile[36:40] != b'acsp'
            or profile[8] not in (2,4) or profile[12:16] not in (b'mntr',b'scnr',b'spac')
            or profile[16:24]!=b'RGB XYZ '):
        raise ValueError('Expected a matrix RGB ICC profile with XYZ connection space')
    tags={}
    count=struct.unpack_from('>I',profile,128)[0]
    end=132+12*count
    if end>len(profile):
        raise ValueError('Truncated ICC tag table')
    for idx in range(count):
        name,offset,size=struct.unpack_from('>4sII',profile,132+12*idx)
        if (name in tags or offset%4 or offset<end or size<8 or offset+size>len(profile)
                or name.startswith((b'A2B',b'B2A',b'D2B',b'B2D'))):
            raise ValueError('Unsupported ICC tag table or alternate LUT transform')
        tags[name]=profile[offset:offset+size]
    return tags


def icc_fixed(tag,kind,count,offset=8):
    if len(tag)!=offset+count*4 or tag[:4]!=kind or tag[4:8]!=bytes(4):
        raise ValueError('Invalid ICC numeric tag')
    return np.frombuffer(tag[offset:],dtype='>i4').astype(np.float64)/65536


def is_srgb_curve(tag):
    if tag[:8]==b'para'+bytes(4):
        kind=tag[8:12]
        expected={b'\0\3\0\0':SRGB_TRC,b'\0\4\0\0':(*SRGB_TRC,0.,0.)}.get(kind)
        return expected is not None and np.allclose(
            icc_fixed(tag,b'para',len(expected),12),expected,rtol=0,atol=2/65536)
    if tag[:8]==b'curv'+bytes(4) and len(tag)>=12:
        count=struct.unpack_from('>I',tag,8)[0]
        if count>=256 and len(tag)==12+2*count:
            encoded=np.linspace(0.,1.,count)
            expected=np.where(encoded<=.04045,encoded/12.92,((encoded+.055)/1.055)**2.4)
            actual=np.frombuffer(tag[12:],dtype='>u2')/65535
            return np.allclose(actual,expected,rtol=0,atol=2/65535)
    return False


def photograph_icc(profile):
    """Recognize the colorants and transfer function, independent of the ICC description."""
    tags=icc_tags(profile)
    if not all(is_srgb_curve(tags[key]) for key in (b'rTRC',b'gTRC',b'bTRC')):
        raise ValueError('ICC transfer curves are not sRGB')
    white=icc_fixed(tags[b'wtpt'],b'XYZ ',3)
    colorants=np.column_stack([icc_fixed(tags[key],b'XYZ ',3) for key in (b'rXYZ',b'gXYZ',b'bXYZ')])
    tolerance=ICC_TOLERANCE
    if b'chad' in tags:
        adaptation=icc_fixed(tags[b'chad'],b'sf32',9).reshape((3,3))
        if not np.allclose(adaptation@D65,D50,rtol=0,atol=ICC_TOLERANCE):
            raise ValueError('ICC chromatic adaptation does not connect D65 to D50')
        colorants=np.linalg.solve(adaptation,colorants)
        candidates=((SRGB_XYZ_D65,SRGB),(P3_XYZ_D65,DISPLAY_P3))
    elif profile[8]==2:
        # Legacy IEC sRGB profiles sometimes omit chad and declare the native
        # white in wtpt. Require the standard D50-adapted sRGB colorants.
        candidates=((D65_TO_D50@SRGB_XYZ_D65,SRGB),)
    else:
        # Some v4 Display P3 profiles store the full Bradford-adapted transform
        # in the D50 colorants without recording the adaptation separately.
        illuminant=np.frombuffer(profile[68:80],dtype='>i4')/65536
        if (not np.allclose(illuminant,D50,rtol=0,atol=P3_PCS_TOLERANCE)
                or not np.allclose(white,D50,rtol=0,atol=P3_PCS_TOLERANCE)):
            raise ValueError('ICC without explicit chromatic adaptation requires a D50 PCS and media white')
        candidates=((D65_TO_D50@P3_XYZ_D65,DISPLAY_P3),)
        tolerance=P3_PCS_TOLERANCE
    if (not np.allclose(white,D50,rtol=0,atol=ICC_TOLERANCE)
            and (profile[8]!=2 or not np.allclose(white,D65,rtol=0,atol=ICC_TOLERANCE))):
        raise ValueError('ICC white point is outside the qualified profiles')
    for expected,color in candidates:
        if np.allclose(colorants,expected,rtol=0,atol=tolerance):
            if b'cicp' in tags:
                primaries=1 if color==SRGB else 12
                if tags[b'cicp']!=b'cicp'+bytes(4)+bytes((primaries,13,0,1)):
                    raise ValueError('ICC video color signaling conflicts with its RGB colorants or transfer')
            return color
    raise ValueError('ICC colorants do not match the qualified sRGB or Display P3 primaries')


def photo_info(path):
    return photo_contract(path)[:3]


def photo_contract(path):
    path=Path(path).resolve(strict=True)
    stat=path.stat()
    return _photo_contract(path,stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns,stat.st_ino)


@lru_cache(maxsize=128)
def _photo_contract(path, size, modified, changed, inode):
    with Image.open(path) as photo:
        if photo.format not in ('PNG','JPEG') or getattr(photo,'is_animated',False):
            raise ValueError('Managed HDR stills require a single PNG or JPEG picture')
        if photo.mode=='CMYK':
            raise ValueError('Convert CMYK stills to sRGB before using them in managed HDR')
        color=SRGB
        if 'icc_profile' in photo.info:
            profile=photo.info['icc_profile']
            if not isinstance(profile,bytes):
                raise ValueError('The photograph has an unreadable ICC profile')
            try:
                color=photograph_icc(profile)
            except (KeyError,ValueError,np.linalg.LinAlgError) as error:
                raise ValueError('Managed stills require a supported sRGB or Display P3 ICC profile') from error
        elif 'srgb' not in photo.info:
            gamma=photo.info.get('gamma')
            if gamma is not None and abs(gamma-.45455)>.002:
                raise ValueError('This PNG has a non-sRGB gamma declaration')
            chromaticity=photo.info.get('chromaticity')
            if chromaticity is not None and not np.allclose(
                    chromaticity,SRGB_CHROMATICITY,rtol=0,atol=ICC_TOLERANCE):
                raise ValueError('This PNG has non-sRGB chromaticities without a supported ICC profile')
        orientation=photo.getexif().get(274,1)
        if orientation not in EXIF_ORIENTATION:
            raise ValueError('Unsupported photograph orientation')
        w,h=photo.size
        if orientation>=5:
            w,h=h,w
        return w,h,EXIF_ORIENTATION[orientation],color


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


def picture_alpha(filters, label, result, number, *, hold='', tail='', opacity=None):
    rgb,alpha=f'picture{number}',f'alpha{number}'
    # Copy directly from GBRA planes. This preserves values above 1.0
    # without intermediate grayscale RGB buffers or swscale conversion.
    filters.append(f'{label}split=2[{rgb}][{alpha}]')
    filters.append(f'[{rgb}]mergeplanes=0x000102:format=gbrpf32le{hold}{tail}[{result}]')
    if opacity is None:
        filters.append(f'[{alpha}]mergeplanes=0x030303:format=gbrpf32le[{result}mask]')
    else:
        coverage=opacity_expression(opacity,'lum')
        filters.append(f'[{alpha}]extractplanes=a,setparams=colorspace=gbr:range=full{hold},'
                       f"geq=lum='{coverage}':i=nearest,format=grayf32le{tail},"
                       f'mergeplanes=0x000000:format=gbrpf32le[{result}mask]')


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
    return f'zscale=threads=1:agamma=0:pin={p}:tin={t}:min={m}:rin={r}:p=2020:t=linear:m=gbr:r=full:npl=100'


def canvas_fit(filters, chain, label, *, source, canvas, fit, fps, opaque_camera=False):
    sw,sh=source
    w,h=canvas
    scale=(max if fit=='cover' else min)(w/sw,h/sh)
    rw,rh=max(1,round(sw*scale)),max(1,round(sh*scale))
    pixel_format = 'gbrpf32le' if opaque_camera else FLOAT_ALPHA
    if (rw,rh)!=(sw,sh):
        chain+=f',zscale=threads=1:w={rw}:h={rh}:filter=bilinear,format={pixel_format}'
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
                hold = f',trim=end_frame=1,loop=loop=-1:size=1:start=0,setpts=N/(({fps})*TB)' if opaque_camera else ''
                filters.append(f'color=black@0:s={ww}x{hh}:r={fps},format=gbrap16le,{matte},'
                               f'format={pixel_format}{hold}[{name}]')
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
    # Each FFmpeg slice owns expression registers and starts every row at
    # X=0. Hoist row-invariant terms while preserving the bilinear mapping.
    angle=f'({degrees})*PI/180'
    setup=(f'ifnot(X,st(6,({scale}));st(7,W*({x}));'
           f'st(1,(Y-(H-1)/2-H*({y}))/ld(6));st(2,cos({angle}));st(3,sin({angle})));'
           'st(0,(X-(W-1)/2-ld(7))/ld(6));'
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
    channels=[f"{plane}='{fn}(X,Y)*({mask})'"
              for plane,fn in (('r','r'),('g','g'),('b','b'),('a','alpha'))]
    return 'geq='+':'.join(channels)+':i=nearest'


def opacity_expression(alpha, sample):
    value=f'{sample}(X,Y)'
    if 'T' in alpha:
        return f'ifnot(X,st(0,({alpha})));clip({value}*ld(0),0,1)'
    return f'clip({value}*({alpha}),0,1)'


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
    opacity = 'alpha(X,Y)' if alpha is None else opacity_expression(alpha,'alpha')
    return 'geq='+':'.join([*channels, f"a='{opacity}'"])+':i=nearest'
