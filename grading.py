"""Portable SDR .cube assets and shared RGB transforms for FFmpeg and the monitor."""
import base64
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import zlib

import numpy as np

AXIS=np.linspace(0,1,5)
BANDS=('shadows','midtones','highlights')
CHANNELS=('master','red','green','blue')


def import_cube(text,name):
    size=None;rows=[]
    for line in text.splitlines():
        words=line.partition('#')[0].split()
        if not words:continue
        tag=words[0]
        if tag=='TITLE':continue
        if tag=='LUT_3D_SIZE':
            if size or len(words)!=2:raise ValueError('Invalid LUT size header')
            size=int(words[1])
            if not 2<=size<=65:raise ValueError('Choose an SDR cube with 2–65 grid points per channel')
        elif tag in ('DOMAIN_MIN','DOMAIN_MAX'):
            expected=0 if tag=='DOMAIN_MIN' else 1
            if list(map(float,words[1:]))!=[expected]*3:raise ValueError('This SDR workspace requires a 0–1 LUT domain')
        else:
            if not size or len(rows)>=size**3 or len(words)!=3:raise ValueError('Invalid cube sample count')
            rows.append(tuple(map(float,words)))
    if not size or len(rows)!=size**3:raise ValueError('Incomplete 3D LUT')
    samples=np.asarray(rows,dtype='<f4')
    if not np.isfinite(samples).all():raise ValueError('Non-finite LUT sample')
    raw=samples.tobytes();ident=hashlib.sha256(raw).hexdigest()
    return ident,{'name':Path(name).name[:150],'size':size,'data':base64.b64encode(zlib.compress(raw)).decode('ascii')}


@lru_cache(maxsize=4)
def unpack(ident,size,payload):
    if type(size) is not int or not 2<=size<=65:raise ValueError('Invalid stored LUT size')
    decoder=zlib.decompressobj()
    try:raw=decoder.decompress(base64.b64decode(payload,validate=True),size**3*12+1)
    except (ValueError,zlib.error) as exc:raise ValueError('Damaged LUT encoding') from exc
    if len(raw)!=size**3*12 or not decoder.eof or decoder.unused_data or hashlib.sha256(raw).hexdigest()!=ident:
        raise ValueError('Damaged stored LUT')
    table=np.frombuffer(raw,dtype='<f4').reshape(size,size,size,3)
    if not np.isfinite(table).all():raise ValueError('Invalid stored LUT values')
    return table


def validate(look):
    if not isinstance(look,dict) or set(look)-set(CHANNELS+BANDS):raise ValueError('Unknown color control')
    result={}
    for key,v in look.items():
        curve=key in CHANNELS
        if not isinstance(v,list) or len(v)!=(5 if curve else 2):raise ValueError('Invalid color control shape')
        if not all(type(x) in (int,float) and (-int(not curve))<=x<=1 for x in v):raise ValueError('Invalid color control value')
        if v!=(list(AXIS) if curve else [0,0]):result[key]=v
    return result


def table(look,ident,library):
    entry=library.get(ident) if ident else None
    src=unpack(ident,entry['size'],entry['data']) if entry else None
    n=len(src) if src is not None else 33
    if src is None:
        b,g,r=np.meshgrid(*([np.linspace(0,1,n)]*3),indexing='ij')
        pixels=np.stack((r,g,b),axis=-1)
    elif look and n<33:
        # Preserve nonlinear curves between the input LUT's grid points.
        axis=np.linspace(0,n-1,33)
        z,y,x=np.meshgrid(axis,axis,axis,indexing='ij')
        xi,yi,zi=(np.minimum(t.astype(int),n-2) for t in (x,y,z))
        dx,dy,dz=x-xi,y-yi,z-zi
        pixels=np.zeros((*x.shape,3),dtype=float)
        for k,wz in enumerate((1-dz,dz)):
            for j,wy in enumerate((1-dy,dy)):
                for i,wx in enumerate((1-dx,dx)):
                    pixels+=src[zi+k,yi+j,xi+i]*(wx*wy*wz)[...,None]
        np.clip(pixels,0,1,out=pixels)
    else:pixels=np.clip(src,0,1).astype(float)
    if any(k in look for k in BANDS):
        y=pixels@np.array([.2126,.7152,.0722])
        weights=((1-y)**2,4*y*(1-y),y*y)
        for key,weight in zip(BANDS,weights):
            x,v=look.get(key,(0,0))
            color=np.array([x,-.5*x+.8660254*v,-.5*x-.8660254*v])
            pixels+=.22*weight[...,None]*(color-color@[.2126,.7152,.0722])
    for i,key in enumerate(CHANNELS[1:]):
        if key in look:pixels[...,i]=np.interp(pixels[...,i],AXIS,look[key])
    if 'master' in look:pixels=np.interp(pixels,AXIS,look['master'])
    return np.clip(pixels,0,1).astype(np.float32)


def filter_for(clip,state,jobdir):
    look=clip.get('look',{});ident=clip.get('lutId')
    if not look and not ident:return ''
    key=hashlib.sha256(json.dumps([look,ident],sort_keys=True).encode()).hexdigest()[:24]
    path=jobdir/f'grade_{key}.cube'
    if not path.exists():
        values=table(look,ident,state.get('luts',{}))
        with path.open('w',encoding='ascii') as f:
            f.write(f'LUT_3D_SIZE {len(values)}\n')
            np.savetxt(f,values.reshape(-1,3),fmt='%.7f')
    return f',lut3d=file={path.name}:interp=trilinear'
