from fractions import Fraction
from pathlib import Path
import tempfile
import unittest
import wave
import time

import numpy as np

import hdr10plus_master
import preview_dependencies
from preview_cache import PreviewCache
import render_engine as engine
import server
import timeline_transitions
import timing
from test_hdr_color import project, source
from test_hdr_editing import luminance
from test_hdr10plus_export import command
from test_hdr10plus_master import verify_master


def settings(left,frames,kind='dissolve',**extra):
    return {'from':left['id'],'frames':frames,'kind':kind,'ease':'linear',**extra}


class BoundaryEditTests(unittest.TestCase):
    def test_dissolve_uses_pq_handles_and_preserves_final_picture_association(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            a,b=source(root,'low',100),source(root,'high',900)
            state=project([a])
            state['assets'].append(b)
            left=state['tracks'][0]['clips'][0]
            left['end']=.25
            right=server.default_clip(b,.25)
            right.update(start=.125,end=.375,transitionIn=settings(left,4))
            state['tracks'][0]['clips'].append(right)
            self.assertEqual(engine.sequence_duration(state),.5)
            p,_=timeline_transitions.plan(state)
            self.assertEqual((p[0].start,p[0].cut,p[0].end),(4,6,8))
            static=root/'hdr10.mp4'
            engine.render(state,static,root/'render')
            frames=luminance(static)
            np.testing.assert_allclose(frames[:,36,64],[100]*5+[366.67,633.33]+[900]*5,rtol=.035)
            authored=root/'hdr10plus.mp4'
            self.assertEqual(hdr10plus_master.author(static,authored,root,24,12,engine._run,
                                                     lambda *_:None,lambda:False),12)
            verify_master(self,static,authored,Fraction(24),12)
            _,preview=preview_dependencies.project(state,0,12,128)
            target=root/'preview.mp4'
            engine.render_range(preview,0,.5,target,root,'preview')
            raw=command('ffmpeg','-v','error','-i',str(target),'-map','0:v','-fps_mode','passthrough',
                        '-pix_fmt','yuv420p','-f','rawvideo','-')
            shade=np.frombuffer(raw,dtype=np.uint8).reshape(12,128*72*3//2)[:,128*36+64]
            self.assertTrue(np.all(np.diff(shade[4:8].astype(int))>0),shade)
            cache=PreviewCache(root/'cache')
            try:
                job=cache.prepare(state,5,640)
                deadline=time.monotonic()+20
                while job['status'] in ('queued','rendering') and time.monotonic()<deadline:
                    time.sleep(.05)
                    job=cache.status(job['id'])
                self.assertEqual(job['status'],'ready',job)
            finally:
                cache.close()
            right['transitionIn']['kind']='dip-black'
            right['transitionIn']['frames']=5
            dip=root/'dip.mp4'
            engine.render(state,dip,root/'dip-render')
            self.assertLess(luminance(dip)[6,36,64],1)
            right['transitionIn']['kind']='dip-white'
            engine.render(state,dip,root/'dip-render')
            self.assertAlmostEqual(luminance(dip)[6,36,64],100,delta=4)
            right['start']=0
            right['end']=.25
            with self.assertRaisesRegex(ValueError,'incoming clip has insufficient'):
                timeline_transitions.plan(state)

    def test_fractional_linear_and_equal_power_crossfade_sample_boundaries(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            sources=[]
            for name,level in [('a',6000),('b',12000)]:
                path=root/(name+'.wav')
                with wave.open(str(path),'wb') as pcm:
                    pcm.setparams((2,2,48000,48000,'NONE',''))
                    pcm.writeframes(np.full((48000,2),level,dtype='<i2').tobytes())
                sources.append(dict(id=name,kind='audio',name=name,path=str(path),**server.probe(path)))
            fps=Fraction(30000,1001)
            cut=float(12/fps)
            left,right=(server.default_clip(source) for source in sources)
            left['end']=cut
            right.update(position=cut,start=cut,end=cut*2)
            track={'id':'audio','name':'Audio','type':'audio','volume':1,'clips':[left,right]}
            state={'output':{'width':128,'height':72,'fps':str(fps)},'assets':sources,'tracks':[track]}
            first,last=timing.sample_at(9,fps),timing.sample_at(15,fps)
            for mode in ('linear','equal-power'):
                right['transitionIn']=settings(left,6,mode)
                audio=root/(mode+'.wav')
                engine._run(engine.segment_command(state,0,float(24/fps),audio,root,'preview','audio'),str(root))
                with wave.open(str(audio),'rb') as pcm:
                    self.assertEqual(pcm.getnframes(),timing.sample_at(24,fps))
                    values=np.frombuffer(pcm.readframes(pcm.getnframes()),dtype='<i2').reshape(-1,2)[:,0]
                self.assertTrue(np.all(values[:first]==6000))
                self.assertTrue(np.all(values[last:]==12000))
                progress=np.arange(last-first)/(last-first)
                expected=(6000*(1-progress)+12000*progress if mode=='linear' else
                          6000*np.cos(np.pi/2*progress)+12000*np.sin(np.pi/2*progress))
                np.testing.assert_allclose(values[first:last],expected,atol=3)
                chunks=[]
                for index,(a,b) in enumerate(engine.boundaries(state,fps)):
                    part=root/f'part-{index}.wav'
                    engine._run(engine.segment_command(state,a,b,part,root,'final','audio'),str(root))
                    with wave.open(str(part),'rb') as pcm:
                        chunks.append(np.frombuffer(pcm.readframes(pcm.getnframes()),dtype='<i2').reshape(-1,2)[:,0])
                np.testing.assert_array_equal(np.concatenate(chunks),values)
