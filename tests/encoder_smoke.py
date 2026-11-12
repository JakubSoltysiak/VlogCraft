"""Exercise end-to-end muxing with every encoder that passes the runtime probe."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import encoders
import render_engine
import server


def main():
    results={}
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)
        src=root/'source.mp4'
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=s=640x360:d=0.5:r=60',
                        '-c:v','libx264','-threads','2',str(src)],check=True)
        asset={'id':'a'*32,'kind':'video','name':src.name,'path':str(src),'size':src.stat().st_size,**server.probe(src)}
        state=server.default_state()
        state['assets']=[asset]
        state['tracks'][1]['clips']=[server.default_clip(asset)]
        for encoder in encoders.available():
            state['output'].update(encoder=encoder,width=640,height=360,fps=60,bitrate=3,preset='veryfast')
            dest=root/(encoder+'.mp4')
            start=time.monotonic()
            render_engine.render(state,dest,root/encoder)
            meta=server.probe(dest)
            assert meta['fps']==60 and meta['width']==640 and meta['hasAudio'],meta
            subprocess.run(['ffmpeg','-v','error','-i',str(dest),'-f','null','-'],check=True)
            results[encoder]={'codec':meta['codec'],'seconds':round(time.monotonic()-start,3)}
    print(json.dumps(results,indent=2))


if __name__=='__main__':main()
