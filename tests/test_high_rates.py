from pathlib import Path
import json
import subprocess
import tempfile
import unittest

import server
import timing
import render_engine


class HighRateTests(unittest.TestCase):
    def test_rational_120_clocks_and_legacy_project_roundtrip(self):
        for rate in (100,120,'120000/1001','119.88'):
            state=server.default_state();state['output']['fps']=rate
            clip=server.default_title();clip['end']=float(13/timing.rate(rate))
            state['tracks'][0]['clips']=[clip]
            saved=timing.encode(state);opened=server.validate_document(saved)
            self.assertEqual(timing.frame_at(opened['tracks'][0]['clips'][0]['end'],timing.rate(rate)),13)
            self.assertEqual(timing.sample_at(1200000,timing.rate('120000/1001')),480480000)

    def test_8k60_native_import_edit_export_and_decoded_frame(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'8k.mp4'
            subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=s=7680x4320:r=60000/1001',
                            '-frames:v','6','-c:v','libx264','-threads','2','-preset','ultrafast',str(source)],check=True,capture_output=True)
            asset=dict(id='b'*32,kind='video',path=str(source),name=source.name,size=source.stat().st_size,**server.probe(source))
            self.assertEqual((asset['width'],asset['height']),(7680,4320))
            state=server.default_state();state['assets']=[asset]
            clip=server.default_clip(asset);clip.update(start=1001/60000,end=5*1001/60000)
            state['tracks'][1]['clips']=[clip]
            state['output'].update(width=7680,height=4320,fps='60000/1001',preset='ultrafast')
            dest=root/'8k-delivery.mp4'
            render_engine.render(state,dest,root/'job')
            meta=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(dest)]))['streams'][0]
            self.assertEqual((meta['width'],meta['height'],meta['nb_frames'],meta['r_frame_rate']),(7680,4320,'4','60000/1001'))
            def frame(path,at):
                return subprocess.check_output(['ffmpeg','-v','error','-ss',str(at),'-i',str(path),'-frames:v','1',
                                                '-vf','scale=96:54','-pix_fmt','rgb24','-f','rawvideo','-'])
            original=frame(source,1001/60000);delivered=frame(dest,0)
            self.assertLess(sum(abs(a-b) for a,b in zip(original,delivered))/len(original),8)
            subprocess.run(['ffmpeg','-v','error','-i',str(dest),'-f','null','-'],check=True,capture_output=True)

    def test_4k120_original_import_slow_motion_and_high_rate_export(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'camera.mov'
            subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=s=3840x2160:r=120000/1001',
                            '-f','lavfi','-i','sine=f=420:r=48000','-t','0.1001','-c:v','libx264',
                            '-preset','ultrafast','-threads','4','-c:a','aac',str(source)],check=True,capture_output=True)
            asset=dict(id='a'*32,kind='video',path=str(source),name=source.name,size=source.stat().st_size,**server.probe(source))
            self.assertEqual(asset['nominalRate'],'120000/1001');self.assertEqual(asset['width'],3840)
            state=server.default_state();state['assets']=[asset]
            clip=server.default_clip(asset);clip['end']=.1001
            state['tracks'][1]['clips']=[clip]
            for rate,speed in [('120000/1001',1),(120,1),(60,.5),(30,.25),(24,.2)]:
                with self.subTest(rate=rate,speed=speed):
                    clip['speed']=speed;state['output'].update(width=3840,height=2160,fps=rate,preset='ultrafast',crf=20)
                    output=root/('out'+str(rate).replace('/','_')+'.mp4')
                    render_engine.render(state,output,root/('job'+str(rate).replace('/','_')))
                    streams=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(output)]))['streams']
                    video=next(s for s in streams if s['codec_type']=='video')
                    self.assertEqual(timing.rational(video['r_frame_rate']),timing.rate(rate))
                    expected=timing.frame_at(clip['end']/speed,timing.rate(rate))
                    self.assertEqual(int(video['nb_frames']),expected)
                    subprocess.run(['ffmpeg','-v','error','-i',str(output),'-f','null','-'],check=True,capture_output=True)
