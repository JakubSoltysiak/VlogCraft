from pathlib import Path
import subprocess
import tempfile
import unittest

import numpy as np
import audio_edit
import server
import render_engine as engine


class AudioTests(unittest.TestCase):
    def test_duck_normalize_pan_and_reference_audio(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);assets=[]
            for name,source in [('music','sine=f=440:d=1:r=48000'),('voice','sine=f=260:d=0.3:r=48000')]:
                path=root/(name+'.wav')
                subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i',source,str(path)],check=True)
                assets.append({'id':name,'kind':'audio','path':str(path),'name':path.name,'size':path.stat().st_size,**server.probe(path)})
            state=server.default_state();state['assets']=assets
            state['output'].update(width=64,height=64,fps=24,preset='ultrafast')
            music=server.default_clip(assets[0]);voice=server.default_clip(assets[1],.4)
            state['tracks'][2]['clips']=[music];state['tracks'][3]['clips']=[voice]
            norm=audio_edit.analysis(state,{'clipId':music['id'],'mode':'normalize'})
            self.assertAlmostEqual(norm['peakDb'],-21.07,delta=.2)
            self.assertTrue(norm['capped'])
            duck=audio_edit.analysis(state,{'clipId':music['id'],'mode':'duck','voiceTrack':state['tracks'][3]['id']})
            self.assertEqual(duck['regions'],1);self.assertEqual(min(k['value'] for k in duck['keys']),.25)
            music.update(keys={'volume':duck['keys']},pan=-1,bass=2,treble=-2,compress=2)
            state['tracks'][3]['muted']=True
            dest=root/'mix.mp4';engine.render(state,dest,root/'work')
            raw=subprocess.check_output(['ffmpeg','-v','error','-i',str(dest),'-vn','-ac','2','-ar','48000','-f','f32le','-'])
            samples=np.frombuffer(raw,'<f4').reshape(-1,2)
            rms=lambda a:np.sqrt(np.mean(a*a))
            self.assertGreater(rms(samples[:,0]),rms(samples[:,1])*20)
            self.assertLess(rms(samples[23000:30000,0]),rms(samples[2000:11000,0])*.4)
