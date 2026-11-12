from pathlib import Path
import subprocess
import tempfile
import unittest

import server
import timing
import render_engine
import sequences


class NestedTests(unittest.TestCase):
    def test_nested_title_and_audio_reopen_and_render_identically(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path=root/'sound.wav'
            subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=f=321:d=0.5',str(path)],check=True)
            asset={'id':'s','name':'sound','path':str(path),'kind':'audio','size':path.stat().st_size,**server.probe(path)}
            s=server.default_state();s['assets']=[asset];s['output'].update(width=128,height=72,fps=24,preset='ultrafast')
            t=server.default_title();t['end']=.5;t['text']='Nest'
            v=server.make_track('video',1);v['clips']=[t]
            a=server.make_track('audio',1);a['clips']=[server.default_clip(asset)]
            child={'id':'nest1','assetId':None,'kind':'sequence','start':0,'end':.5,'speed':1,'position':.25,'children':[v,a]}
            s['tracks'][0]['clips']=[child]
            s=server.validate_document(timing.encode(s))
            flat=sequences.playback(s)
            self.assertEqual(flat['tracks'][0]['clips'][0]['position'],.25)
            self.assertNotEqual(s['tracks'][0]['clips'][0]['children'][0]['clips'][0]['position'],.25)
            raw=[]
            for i,state in enumerate((s,flat)):
                out=root/f'{i}.mp4';render_engine.render(state,out,root/f'tmp{i}')
                raw.append(subprocess.check_output(['ffmpeg','-v','error','-i',str(out),'-f','framemd5','-']))
            self.assertEqual(raw[0],raw[1])
