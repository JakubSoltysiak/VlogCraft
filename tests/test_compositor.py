from pathlib import Path
import subprocess
import tempfile
import unittest

import numpy as np
from PIL import Image
import server
import render_engine as engine


class CompositorTests(unittest.TestCase):
    def test_animated_transform_mask_chroma_and_reference_match(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'layer.png'
            pixels=np.zeros((64,96,3),np.uint8);pixels[:,:,1]=255
            pixels[26:38,18:78]=[255,12,8];Image.fromarray(pixels).save(source)
            a={'kind':'image','id':'a'*32,'path':str(source),'name':source.name,'duration':0,'hasAudio':False,
               'width':96,'height':64,'size':source.stat().st_size}
            s=server.default_state();s['output'].update(width=96,height=64,fps=24,preset='ultrafast',crf=15)
            s['assets']=[a];c=server.default_clip(a)
            def curve(lo,hi):return [{'time':0.,'value':lo,'mode':'linear'},{'time':.5,'value':hi,'mode':'hold'}]
            c.update(end=.75,chroma=True,mask='ellipse',maskRadius=.49,feather=.1,
                     keys={'opacity':curve(.4,1),'rotation':curve(0,90),'scale':curve(.65,1),'maskRadius':curve(.36,.49)})
            s['tracks'][1]['clips']=[c]
            out=root/'comp.mp4';engine.render(s,out,root/'export')
            raw=subprocess.check_output(['ffmpeg','-v','error','-i',str(out),'-an','-pix_fmt','rgb24','-f','rawvideo','-'])
            frames=np.frombuffer(raw,np.uint8).reshape(-1,64,96,3).astype(float)
            self.assertEqual(len(frames),18)
            for frame_id in (0,6,12):
                frame=root/f'ref{frame_id}.png'
                engine._run(engine.segment_command(s,frame_id/24,(frame_id+1)/24,frame,root,'frame'),str(root))
                reference=np.array(Image.open(frame).convert('RGB'),dtype=float)
                self.assertLess(np.mean(np.abs(reference-frames[frame_id])),5,(frame_id,'reference mismatch'))
            red=lambda f:(f[:,:,0]-f[:,:,1])>55
            y,x=np.where(red(frames[0]));self.assertGreater(np.ptp(x),np.ptp(y)*2)
            y,x=np.where(red(frames[12]));self.assertGreater(np.ptp(y),np.ptp(x)*2)
            self.assertGreater(frames[12,32,48,0],frames[0,32,48,0]+80)
            self.assertLess(frames[12,5,5,1],50)
