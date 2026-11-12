from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import server


class FallbackTests(unittest.TestCase):
    def test_hardware_failure_retries_software_without_changing_project(self):
        s=server.default_state()
        s['tracks'][0]['clips']=[server.default_title()]
        s['output']['encoder']='h264_amf'
        calls=[]
        def render(state,dest,*args,**kwargs):
            calls.append(state['output']['encoder'])
            if len(calls)==1:raise RuntimeError('AMF device removed')
            Path(dest).write_bytes(b'completed replacement')
        with tempfile.TemporaryDirectory() as folder, patch.object(server.encoders,'available',return_value={'h264_amf':'AMF'}),patch.object(server.engine,'render',side_effect=render):
            server.CANCEL['export'].clear()
            server.run_export(server.deepcopy(s),str(Path(folder)/'delivery.mp4'))
            self.assertEqual(calls,['h264_amf','libx264'])
            self.assertEqual(server.JOBS['export']['status'],'done')
            self.assertIn('after hardware encoder failure',server.JOBS['export']['message'])
            self.assertEqual(s['output']['encoder'],'h264_amf')
