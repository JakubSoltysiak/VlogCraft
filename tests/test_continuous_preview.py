import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import numpy as np
import render_engine as engine
import server


class ContinuousPreviewTests(unittest.TestCase):
    def test_single_graph_matches_segmented_timeline_and_audio_placement(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source.mp4'
            subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=s=128x72:r=24:d=1',
                            '-f','lavfi','-i','sine=f=440:r=48000:d=1','-c:v','libx264','-preset','ultrafast',
                            '-c:a','aac','-shortest',str(source)],check=True,capture_output=True)
            a=dict(id='a'*32,kind='video',name=source.name,path=str(source),size=source.stat().st_size,**server.probe(source))
            s=server.default_state();s['assets']=[a];s['output'].update(width=128,height=72,fps=24,crf=26,preset='ultrafast')
            first=server.default_clip(a);first.update(position=.25,start=.125,end=.625,volume=.5)
            first['keys']={'rotation':[{'time':.125,'value':-5,'mode':'linear'},{'time':.625,'value':5,'mode':'linear'}]}
            second=server.default_clip(a);second.update(position=.75,start=.25,end=.5,grade='warm',volume=.2)
            s['tracks'][1]['clips']=[first,second]
            linked_audio=server.default_clip(a,.25,'audio');linked_audio.update(start=.125,end=.625,volume=.1)
            s['tracks'][2]['clips']=[linked_audio]
            title=server.default_title(.125);title.update(end=.5,text='Preview',fadeIn=.25,fadeOut=.125)
            s['tracks'][0]['clips']=[title]
            segmented=root/'reference.mp4';engine.render(s,segmented,root/'reference')
            continuous=root/'continuous.mp4';work=root/'continuous';work.mkdir()
            command=engine.segment_command(s,0,1,continuous,work,'preview','video')
            self.assertEqual(sum(arg==str(source) for arg in command),2,'Matching ranges share decoders within each stream type')
            engine.render_range(s,0,1,continuous,work,'preview',lambda c,w:subprocess.run(c,cwd=w,capture_output=True,check=True,timeout=20))
            def video(path):
                raw=subprocess.check_output(['ffmpeg','-v','error','-i',str(path),'-an','-pix_fmt','rgb24','-f','rawvideo','-'])
                return np.frombuffer(raw,np.uint8).reshape(-1,72,128,3).astype(float)
            expected,actual=video(segmented),video(continuous)
            self.assertEqual(actual.shape,expected.shape)
            for n in (0,2,3,5,6,12,17,18,23):
                self.assertLess(np.mean(np.abs(actual[n]-expected[n])),7,(n,'range compositor mismatch'))
            raw=subprocess.check_output(['ffmpeg','-v','error','-i',str(continuous),'-vn','-ac','1','-f','f32le','-'])
            pcm=np.frombuffer(raw,np.float32)
            rms=lambda lo,hi:float(np.sqrt(np.mean(pcm[int(lo*48000):int(hi*48000)]**2)))
            self.assertLess(rms(.05,.15),.001)
            self.assertGreater(rms(.35,.55),.02)
            meta=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(continuous)]))['streams']
            self.assertLess(abs(float(meta[0]['duration'])-float(meta[1]['duration'])),1/24)
