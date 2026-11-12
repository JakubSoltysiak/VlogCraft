import json
from fractions import Fraction
from pathlib import Path
import subprocess
import tempfile
import unittest

import server
import timing
import render_engine as engine


class RationalClocks(unittest.TestCase):
    def test_storage_legacy_migration_and_long_sequence_clock(self):
        s=server.default_state()
        clip=server.default_title(3600)
        s['tracks'][0]['clips']=[clip]
        old=server.validate_document(s)
        for fps in ('24000/1001','30000/1001','60000/1001'):
            old['output']['fps']=fps
            doc=timing.encode(old)
            self.assertEqual(doc['version'],4)
            stamp=doc['tracks'][0]['clips'][0]['timing']
            self.assertIsInstance(stamp['positionFrame'],int)
            self.assertEqual(timing.encode(server.validate_document(doc))['tracks'][0]['clips'][0]['timing'],stamp)
            f=timing.rate(fps)
            end=timing.frame_at(18*3600,f)
            self.assertEqual(timing.frame_at(end/f,f),end)
            self.assertLess(abs(Fraction(timing.sample_at(end,f),48000)-end/f),Fraction(1,48000))

    def fixture(self,root,rate,vfr=False):
        path=root/'frame-id.mkv' if vfr else root/'frame-id.mov'
        filt="geq=lum='24+8*N':cb=128:cr=128"
        if vfr:filt+=",setpts='(N+floor(N/2)*3)'"
        subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-f','lavfi','-i',f'nullsrc=s=64x64:r={rate}',
                        '-frames:v','20','-vf',filt,'-fps_mode','vfr','-c:v','ffv1',str(path)],capture_output=True,check=True)
        a={'kind':'video','id':'a'*32,'name':path.name,'path':str(path),'size':path.stat().st_size,**server.probe(path)}
        s=server.default_state();s['assets']=[a]
        s['output'].update(width=64,height=64,crf=15,preset='ultrafast')
        return s,a

    def test_fractional_one_frame_joins_keep_identifiers_and_rate(self):
        for fps in ('24000/1001','30000/1001','60000/1001'):
            with self.subTest(rate=fps),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);s,a=self.fixture(root,fps);rate=timing.rate(fps);s['output']['fps']=fps
                order=[7,2,11,5,1,9,4,12]
                for i,n in enumerate(order):
                    c=server.default_clip(a);c.update(start=float(n/rate),end=float((n+1)/rate),position=float(i/rate))
                    s['tracks'][1]['clips'].append(c)
                output=root/'joined.mp4';engine.render(s,output,root/'work')
                meta=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(output)]))
                v,au=meta['streams'];self.assertEqual(v['r_frame_rate'],fps)
                self.assertEqual(int(v['nb_frames']),len(order))
                expected=float(len(order)/rate)
                self.assertAlmostEqual(float(v['duration']),expected,places=5)
                self.assertLess(abs(float(au['duration'])-expected),.002)
                raw=subprocess.check_output(['ffmpeg','-v','error','-i',str(output),'-an','-fps_mode','passthrough','-pix_fmt','yuv420p','-f','rawvideo','-'])
                values=list(raw[::64*64*3//2])
                for got,n in zip(values,order):self.assertLessEqual(abs(got-(24+8*n)),2,(fps,values,order))

    def test_original_vfr_index_and_exclusive_outpoint(self):
        import source_frames
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);_,asset=self.fixture(root,100,True)
            index=source_frames.FrameIndex(root/'pts')
            held=index.locate(asset,.022,0)
            self.assertEqual((held['index'],held['count'],held['start'],held['end']),(1,20,.01,.05))
            nxt=index.locate(asset,held['start'],1)
            self.assertEqual(nxt['start'],held['end'])
            self.assertEqual(index.locate(asset,nxt['start'],-1),held)
            self.assertTrue(source_frames.preview(asset,nxt).startswith('data:image/jpeg;base64,'))
            self.assertEqual(index.path(asset).stat().st_size,8*held['count'])

    def test_vfr_cut_starts_inside_held_frame(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);s,a=self.fixture(root,100,True);s['output']['fps']=50
            # Original PTS run 0, .01, .05, .06, .10, .11, ...
            c=server.default_clip(a);c.update(start=.02,end=.10);s['tracks'][1]['clips']=[c]
            dest=root/'vfr-cut.mp4';engine.render(s,dest,root/'work')
            raw=subprocess.check_output(['ffmpeg','-v','error','-i',str(dest),'-an','-pix_fmt','yuv420p','-f','rawvideo','-'])
            values=list(raw[::6144])
            self.assertEqual(len(values),4)
            for got,n in zip(values,[1,1,3,3]):self.assertLessEqual(abs(got-(24+8*n)),2,values)
