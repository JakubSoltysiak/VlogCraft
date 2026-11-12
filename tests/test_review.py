import json
from pathlib import Path
import tempfile
import unittest
import zipfile

import review_packet
import server


class PacketTests(unittest.TestCase):
    def test_nested_proposal_and_rendered_review_frame(self):
        s=server.default_state();s['output'].update(width=1280,height=720,fps='30000/1001')
        c=server.default_title();c['end']=.5
        track=server.make_track('video',1);track['clips']=[c]
        parent={'id':'seq','kind':'sequence','assetId':None,'start':0,'end':.5,'speed':1,'position':0,'children':[track]}
        s['tracks'][0]['clips']=[parent]
        s=server.validate_document(s)
        prop={'schema':'vlogcraft.timeline/1','actions':[{'type':'edit_clip','sequencePath':['seq'],
              'trackId':track['id'],'clipId':c['id'],'set':{'opacity':.5}}]}
        result,_=server.prepare_proposal(prop,s)
        self.assertEqual(result['tracks'][0]['clips'][0]['children'][0]['clips'][0]['opacity'],.5)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'review.zip'
            review_packet.create(s,path,{},[3])
            with zipfile.ZipFile(path) as z:
                data=json.loads(z.read('multitrack_manifest.json'))
                self.assertEqual(data['output']['width'],1280)
                self.assertEqual(data['tracks'][0]['clips'][0]['tracks'][0]['clips'][0]['clipId'],c['id'])
                self.assertTrue(z.read('frames/program_0000000003.jpg').startswith(b'\xff\xd8'))
        s['tracks'][0]['locked']=True
        with self.assertRaises(ValueError):server.prepare_proposal(prop,s)
