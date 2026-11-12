import errno
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import cv2
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import animation
import motion
import project_store
import render_engine
import server
import timeline_proposal


class PersistenceTests(unittest.TestCase):
    def test_recovery_and_disk_full_publication(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'travel.vlogcraft'
            a=server.default_state()
            b={**a,'name':'Second cut'}
            project_store.save(p,a,server.validate_document)
            project_store.save(p,b,server.validate_document)
            original_replace=os.replace
            def disk_full(src,dst):
                if Path(dst)==p:raise OSError(errno.ENOSPC,'injected disk full')
                original_replace(src,dst)
            with mock.patch.object(os,'replace',side_effect=disk_full):
                with self.assertRaises(OSError):project_store.save(p,{**a,'name':'Third'},server.validate_document)
            self.assertEqual(project_store.load(p,server.validate_document)[0]['name'],'Second cut')
            p.write_bytes(b'{"interrupted":')
            recovered,flag=project_store.load(p,server.validate_document)
            self.assertTrue(flag)
            self.assertEqual(recovered['name'],'Second cut')
            p.with_name(p.name+'.bak').write_text('{}')
            with self.assertRaises(ValueError):project_store.load(p,server.validate_document)
            self.assertEqual(p.read_bytes(),b'{"interrupted":')

    def test_multitrack_patch_validation_and_frame_partition(self):
        state=server.default_state()
        track=state['tracks'][0]
        clip=server.default_title(20000)
        clip['end']=.4
        track['clips']=[clip]
        action={'type':'edit_clip','trackId':track['id'],'clipId':clip['id'],'set':{'opacity':.35,'x':.25}}
        prop={'schema':timeline_proposal.SCHEMA,'actions':[action]}
        edited,audit=server.prepare_proposal(prop,state)
        self.assertEqual(len(audit),2)
        self.assertEqual(edited['tracks'][0]['clips'][0]['opacity'],.35)
        self.assertEqual(clip['opacity'],1)
        track['locked']=True
        with self.assertRaises(ValueError):server.prepare_proposal(prop,state)
        track['locked']=False
        for invalid in ({'opacity':float('nan')},{'path':'x'},{'opacity':'0.5'}):
            with self.assertRaises(ValueError):
                server.prepare_proposal({**prop,'actions':[{**action,'set':invalid}]},state)
        state['output']['fps']=60
        self.assertEqual(round((render_engine.boundaries(state,60)[-1][1]-20000)*60),24)
        clip['position']=0;clip['end']=5-4.6
        self.assertEqual(render_engine.boundaries(state,60),[(0,.4)])

    def test_large_track_inventory_and_source_anchored_keys(self):
        s=server.default_state()
        for i in range(100):s['tracks'].append(server.make_track('video',i))
        s['tracks'][0]['clips']=[server.default_title(i*16.7) for i in range(1500)]
        saved=server.validate_document(s)
        self.assertEqual(len(saved['tracks']),104)
        self.assertGreater(render_engine.sequence_duration(saved),6*3600)
        keys={'x':[{'time':2,'value':0,'mode':'bezier','handles':[.2,.05,.7,.9]},
                   {'time':3,'value':.5,'mode':'hold'}]}
        self.assertAlmostEqual(animation.bezier(.5,[0,0,1,1]),.5,places=5)
        c={'keys':animation.validate(keys),'start':2,'position':1,'speed':1,'x':0}
        self.assertEqual(animation.expression(c,'x',1.5),animation.expression({**c,'position':4,'start':2.5},'x',4))
        with self.assertRaises(ValueError):animation.validate({'x':keys['x'][::-1]})


class MotionAndColorTests(unittest.TestCase):
    def test_point_track_and_visible_stabilization_from_encoded_original(self):
        # A textured flat target moves ±4 pixels. Measure decoded rendered
        # translation independently with phase correlation on the central area.
        w,h,n,fps=192,108,24,24
        base=np.random.default_rng(17).integers(0,256,(h,w),dtype=np.uint8)
        shifts=[(4 if i%2 else -4,2 if i%2 else -2) for i in range(n)]
        frames=[np.roll(base,(dy,dx),axis=(0,1)) for dx,dy in shifts]
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);src=root/'jitter.mov'
            subprocess.run(['ffmpeg','-v','error','-f','rawvideo','-pixel_format','gray','-video_size',f'{w}x{h}',
                            '-framerate',str(fps),'-i','pipe:0','-c:v','libx264','-crf','8','-pix_fmt','yuv420p',str(src)],
                           input=b''.join(f.tobytes() for f in frames),check=True,capture_output=True)
            a={'id':'1'*32,'name':src.name,'kind':'video','path':str(src),'size':src.stat().st_size,**server.probe(src)}
            s=server.default_state();s['assets']=[a]
            s['output'].update(width=w,height=h,fps=fps,crf=18,preset='ultrafast')
            clip=server.default_clip(a);s['tracks'][1]['clips']=[clip]
            analysis=motion.analyze(a,clip,{'mode':'track','point':[.51,.49]},lambda:False,lambda _:None)
            self.assertEqual(analysis['samples'],n)
            self.assertAlmostEqual(analysis['points'][1][1],8/w,delta=.012)
            stable=motion.analyze(a,clip,{'mode':'stabilize','strength':1},lambda:False,lambda _:None)
            clip['keys']={p:[{'time':pt[0],'value':pt[j],'mode':'linear'} for pt in stable['points']]
                          for j,p in [(1,'x'),(2,'y')]}
            dest=root/'stable.mp4'
            render_engine.render(s,dest,root/'temp')
            raw=subprocess.check_output(['ffmpeg','-v','error','-i',str(dest),'-an','-pix_fmt','gray','-f','rawvideo','-'])
            result=np.frombuffer(raw,np.uint8).reshape(-1,h,w)
            def jitter(images):
                region=[np.float32(f[16:-16,16:-16]) for f in images]
                return float(np.median([np.linalg.norm(cv2.phaseCorrelate(a,b)[0]) for a,b in zip(region,region[1:])]))
            self.assertEqual(len(result),n)
            self.assertLess(jitter(result),jitter(frames)*.45)

    def test_hevc_mov_monochrome_grade_and_silent_track(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);src=root/'hevc.mov'
            subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=s=128x72:r=50:d=0.4',
                            '-f','lavfi','-i','sine=f=500:d=0.4','-c:v','libx265','-preset','ultrafast',
                            '-x265-params','pools=2','-tag:v','hvc1','-c:a','aac',str(src)],check=True,capture_output=True)
            asset={'id':'a'*32,'name':src.name,'kind':'video','path':str(src),'size':src.stat().st_size,**server.probe(src)}
            self.assertEqual(asset['codec'],'hevc')
            s=server.default_state();s['assets']=[asset];s['output'].update(width=128,height=72,fps=50,preset='ultrafast')
            clip=server.default_clip(asset);clip.update(grade='mono',end=.4)
            s['tracks'][1].update(muted=True,clips=[clip])
            out=root/'mono.mp4';render_engine.render(s,out,root/'work')
            raw=subprocess.check_output(['ffmpeg','-v','error','-i',str(out),'-frames:v','1','-an','-pix_fmt','rgb24','-f','rawvideo','-'])
            pix=np.frombuffer(raw,np.uint8).reshape(-1,3).astype(float)
            self.assertLess(np.mean(np.ptp(pix,axis=1)),2.5)
            pcm=subprocess.check_output(['ffmpeg','-v','error','-i',str(out),'-vn','-f','s16le','-'])
            self.assertEqual(max(np.abs(np.frombuffer(pcm,np.int16))),0)


if __name__=='__main__':unittest.main()
