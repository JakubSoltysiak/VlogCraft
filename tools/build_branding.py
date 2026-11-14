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
    side=max(original.size)
    square=Image.new('RGBA',(side,side))
    square.paste(original,((side-original.width)//2,(side-original.height)//2))
    TARGET.mkdir(parents=True,exist_ok=True)
    # Filter premultiplied color and alpha together to preserve translucent glow edges.
    frames=[square.convert('RGBa').resize((n,n),Image.Resampling.LANCZOS).convert('RGBA') for n in SIZES]
    for n,frame in zip(SIZES,frames):frame.save(TARGET/f'vlogcraft-{n}.png')
    frames[-1].save(TARGET/'vlogcraft-approved.ico',sizes=[(n,n) for n in SIZES],append_images=frames[:-1])
    manifest={'source_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
              'source_dimensions':list(original.size),'sizes':list(SIZES),
              'method':'Unmodified RGBA original, centered transparent square; premultiplied-alpha Lanczos; no crop, recolor or redraw.'}
    (TARGET/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf8')
    return manifest
if __name__=='__main__':print(json.dumps(build()))
