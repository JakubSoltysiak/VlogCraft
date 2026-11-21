from fractions import Fraction
import hashlib
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image

import color_management as color
import hdr10plus_master
import render_engine as engine
import server
from test_hdr_color import project, source
from test_hdr10plus_export import command
from test_hdr10plus_master import verify_master


def asset(path):
    return dict(id=path.stem,kind='image',name=path.name,path=str(path),**server.probe(path))


def luminance(path,w=128,h=72):
    raw=command('ffmpeg','-v','error','-i',str(path),'-map','0:v','-fps_mode','passthrough',
                '-pix_fmt','yuv420p10le','-f','rawvideo','-')
    raw=np.frombuffer(raw,dtype='<u2').reshape(-1,w*h*3//2)[:,:w*h].reshape(-1,h,w)
    return color.pq_to_nits(np.clip((raw.astype(float)-64)/876,0,1))


class ManagedEditingTests(unittest.TestCase):
    def test_transparent_png_blends_in_linear_light_and_preserves_highlights(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            photo=root/'alpha.png'
            Image.new('RGBA',(40,72),(255,255,255,128)).save(photo)
            state=project([asset(photo),source(root,'pq',1000)])
            foreground=state['tracks'][0]['clips'][0]
            foreground['opacity']=1
            output=root/'linear.mp4'
            engine.render(state,output,root/'render')
            nits=luminance(output)
            self.assertEqual(len(nits),12)
            np.testing.assert_allclose(nits[:,36,64],548.2,rtol=.025)
            np.testing.assert_allclose(nits[:,36,10],1000,rtol=.025)

    def test_exif_srgb_jpeg_and_title_motion_author_final_pictures(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            photo=root/'portrait.jpg'
            pixels=np.full((128,72,3),128,dtype=np.uint8)
            pixels[:64,:,:]=255
            metadata=Image.Exif()
            metadata[274]=6
            Image.fromarray(pixels).save(photo,exif=metadata,quality=100)
            original=hashlib.sha256(photo.read_bytes()).digest()
            still=asset(photo)
            state=project([still])
            state['output']['color']['sdrWhiteNits']=200
            title=server.default_title(.25)
            title.update(text='HDR',fontScale=.16,end=.25,fadeIn=0,fadeOut=0,
                         keys={'rotation':[{'time':0,'value':-10,'mode':'ease-in-out'},
                                           {'time':.24,'value':10,'mode':'linear'}],
                               'x':[{'time':0,'value':-.12,'mode':'linear'},
                                    {'time':.24,'value':.12,'mode':'linear'}]})
            state['tracks'].insert(0,{'id':'titles','type':'video','clips':[title]})
            output=root/'photo.mp4'
            engine.render(state,output,root/'render')
            nits=luminance(output)
            np.testing.assert_allclose(nits[0,14,100],200,rtol=.025)
            np.testing.assert_allclose(nits[0,14,20],43.17,rtol=.05)
            self.assertGreater(np.mean(np.abs(nits[6]-nits[11])),.5)
            self.assertEqual(hashlib.sha256(photo.read_bytes()).digest(),original)
            master=root/'photo-hdr10plus.mp4'
            self.assertEqual(hdr10plus_master.author(output,master,root,24,12,engine._run,
                                                     lambda *_:None,lambda:False),12)
            verify_master(self,output,master,Fraction(24),12)

    def test_animated_footage_geometry_and_mask_keep_pq_precision(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            state=project([source(root,'background',100),source(root,'foreground',800)])
            state['tracks'].reverse()
            foreground=state['tracks'][0]['clips'][0]
            foreground.update(mask='rectangle',maskRadius=.27,feather=.3,opacity=1,
                              scale=.8,rotation=15,
                              keys={'x':[{'time':0,'value':-.25,'mode':'linear'},
                                         {'time':.5,'value':.25,'mode':'linear'}]})
            state['tracks'][1]['clips'][0]['opacity']=1
            dest=root/'move.mp4'
            engine.render(state,dest,root/'render')
            nits=luminance(dest)
            self.assertGreater(nits[0,36,33],750)
            self.assertLess(nits[0,36,94],120)
            self.assertGreater(nits[11,36,94],750)
            self.assertLess(nits[11,36,33],120)
