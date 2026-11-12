"""Bounded-memory peak overview, independent of project or preview resolution."""
import subprocess
import tempfile

import numpy as np
from PIL import Image,ImageDraw


def build(asset,dest):
    if not asset.get('hasAudio') or dest.exists():return
    width,height,rate=1200,50,8000
    total=max(1,round(asset['duration']*rate))
    peaks=np.zeros(width,np.int32)
    position=0
    cmd=['ffmpeg','-nostdin','-v','error','-i',asset['path'],'-map','0:a:0','-vn','-ac','1','-ar',str(rate),
         '-f','s16le','pipe:1']
    with subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)) as proc:
        try:
            while data:=proc.stdout.read(65536):
                block=np.frombuffer(data,dtype='<i2').astype('int32')
                bins=np.minimum(width-1,(np.arange(len(block),dtype=np.int64)+position)*width//total)
                np.maximum.at(peaks,bins,np.abs(block))
                position+=len(block)
            if proc.wait() or not position:return
        finally:
            if proc.poll() is None:proc.kill()
    image=Image.new('RGBA',(width,height))
    draw=ImageDraw.Draw(image)
    for x,level in enumerate(peaks):
        amplitude=max(1,round(height/2*(level/32768)**.68))
        draw.line((x,height//2-amplitude,x,height//2+amplitude),fill=(174,153,227,205))
    dest.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix='.png',dir=dest.parent,delete=False) as file:
        from pathlib import Path
        temp=Path(file.name)
    try:
        image.save(temp,'PNG');temp.replace(dest)
    finally:temp.unlink(missing_ok=True)
