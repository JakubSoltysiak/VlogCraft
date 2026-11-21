"""Deterministic Windows/browser icons from the owner's unmodified approved artwork."""
import hashlib,json
from pathlib import Path
from PIL import Image
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'assets/branding/vlogcraft-original.png'
TARGET=ROOT/'web/branding'
SIZES=(16,24,32,48,64,128,256)

def build():
    original=Image.open(SOURCE).convert('RGBA')
    # Keep the approved artwork and its proportions. Crop only around the
    # meaningful alpha bounds, leaving breathing room for the translucent glow.
    bounds=original.getchannel('A').point(lambda alpha:255 if alpha>=4 else 0).getbbox()
    if not bounds:
        raise ValueError('Approved icon artwork has no visible alpha')
    left,top,right,bottom=bounds
    border=round(max(right-left,bottom-top)*.035)
    crop=(max(0,left-border),max(0,top-border),
          min(original.width,right+border),min(original.height,bottom+border))
    artwork=original.crop(crop)
    side=max(artwork.size)
    square=Image.new('RGBA',(side,side))
    square.paste(artwork,((side-artwork.width)//2,(side-artwork.height)//2))
    TARGET.mkdir(parents=True,exist_ok=True)
    # Filter premultiplied color and alpha together to preserve translucent glow edges.
    frames=[square.convert('RGBa').resize((n,n),Image.Resampling.LANCZOS).convert('RGBA') for n in SIZES]
    for n,frame in zip(SIZES,frames):frame.save(TARGET/f'vlogcraft-{n}.png')
    frames[-1].save(TARGET/'vlogcraft-approved.ico',sizes=[(n,n) for n in SIZES],append_images=frames[:-1])
    manifest={'source_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
              'source_dimensions':list(original.size),'sizes':list(SIZES),
              'render_crop':list(crop),
              'method':'Crop near-invisible alpha margins only, center with safe padding and scale with premultiplied-alpha Lanczos. Original RGBA unchanged.'}
    (TARGET/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf8')
    return manifest
if __name__=='__main__':print(json.dumps(build()))
