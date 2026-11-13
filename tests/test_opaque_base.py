import json
from pathlib import Path
import subprocess,tempfile,unittest
from unittest import mock
import numpy as np
import render_engine as engine
import server

class OpaqueBaseTests(unittest.TestCase):
    def test_opaque_picture_uses_direct_base_and_matches_reference(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);src=root/'source.mp4'
            subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','testsrc2=s=160x90:r=24:d=0.5',
                            '-c:v','libx264','-pix_fmt','yuv420p',str(src)],capture_output=True,check=True)
            a=dict(id='a'*32,kind='video',name=src.name,path=str(src),size=src.stat().st_size,**server.probe(src))
            self.assertEqual(a['sampleAspectRatio'],'1:1');self.assertEqual(a['pixelFormat'],'yuv420p')
            s=server.default_state();s['assets']=[a];s['output'].update(width=160,height=90,fps=24,preset='ultrafast',crf=15)
            clip=server.default_clip(a);s['tracks'][1]['clips']=[clip]
            optimized=root/'optimized.mp4';original=root/'original.mp4'
            work=root/'work';work.mkdir()
            cmd=engine.segment_command(s,0,.5,optimized,work,'preview','video')
            graph=(work/f'graph_{optimized.stem}.txt').read_text()
            self.assertIn('setsar=1[base',graph);self.assertNotIn('overlay=',graph);self.assertNotIn('format=rgba',graph)
            engine.render(s,optimized,root/'optimized')
            with mock.patch.object(engine,'_opaque_base',return_value=False):engine.render(s,original,root/'original')
            def decode(path):
                return np.frombuffer(subprocess.check_output(['ffmpeg','-v','error','-i',str(path),'-an','-pix_fmt','rgb24','-f','rawvideo','-']),np.uint8).astype(float)
            got,want=decode(optimized),decode(original)
            self.assertEqual(got.shape,want.shape);self.assertEqual(len(got),12*160*90*3)
            self.assertLess(np.abs(got-want).mean(),3)
            for prop,value in [('opacity',.8),('scale',.8),('rotation',10),('fadeIn',.1),('mask','ellipse'),('x',.1)]:
                changed={**clip,prop:value};s['tracks'][1]['clips']=[changed]
                engine.segment_command(s,0,.5,optimized,work,'preview','video')
                self.assertIn('overlay=',(work/f'graph_{optimized.stem}.txt').read_text(),prop)
            s['tracks'][1]['clips']=[clip];a.pop('sampleAspectRatio')
            engine.segment_command(s,0,.5,optimized,work,'preview','video')
            self.assertIn('overlay=',(work/f'graph_{optimized.stem}.txt').read_text(),'Unknown legacy aspect takes the existing path')
