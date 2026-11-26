import contextlib,io,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from tools import performance_record as record

class EvidenceBindingTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
  (self.root/'app.py').write_bytes(b'app = 1\n');(self.root/'driver.py').write_bytes(b'quality = 540\n')
  self.path=self.root/'record.json';self.path.write_text(json.dumps({'qualification':'partial'}))
  self.scope=contextlib.ExitStack();self.addCleanup(self.scope.close)
  for key,value in [('ROOT',self.root),('FILES',['app.py']),('PROTOCOL_FILES',['driver.py'])]:self.scope.enter_context(patch.object(record,key,value))
 def invoke(self,stamp=False):
  with patch.object(sys,'argv',['performance_record',str(self.path),*(['--stamp'] if stamp else [])]),contextlib.redirect_stdout(io.StringIO()):record.main()
 def test_driver_change_is_rejected_even_when_application_is_unchanged(self):
  self.invoke(True);self.invoke();source=record.fingerprint()
  (self.root/'driver.py').write_text('quality = 360\n')
  self.assertEqual(record.fingerprint(),source)
  with self.assertRaisesRegex(AssertionError,'benchmark protocol'):self.invoke()
 def test_windows_checkout_line_endings_do_not_invalidate_either_binding(self):
  self.invoke(True)
  for name in ('app.py','driver.py'):
   path=self.root/name;path.write_bytes(path.read_bytes().replace(b'\n',b'\r\n'))
  self.invoke();data=json.loads(self.path.read_text());self.assertIn('benchmark_protocol_fingerprint',data)

 def test_detailed_measurements_cannot_change_during_a_restamp(self):
  self.invoke(True)
  data=json.loads(self.path.read_text())
  name='delivery.json'
  (self.root/name).write_text('{"subthreshold_pictures":19}')
  data['measurement_files']={name:record.fingerprint([name])}
  self.path.write_text(json.dumps(data))
  self.invoke()
  (self.root/name).write_text('{"subthreshold_pictures":0}')
  for stamp in (False,True):
   with self.assertRaisesRegex(ValueError,'measurement file'):
    self.invoke(stamp)

 def test_follow_up_can_update_bindings_and_append_results_without_replacing_trials(self):
  previous={'source_fingerprint':'old','benchmark_protocol_fingerprint':'old protocol',
            'playback':{'failed':{'skipped_frames':152}},'unavailable':None}
  candidate={**previous,'source_fingerprint':'new','benchmark_protocol_fingerprint':'new protocol',
             'follow_up':{'trial':{'skipped_frames':0}}}
  record.check_history(candidate,previous)
  with self.assertRaisesRegex(ValueError,'playback'):
   record.check_history({**candidate,'playback':{'failed':{'skipped_frames':0}}},previous)
  del candidate['unavailable']
  with self.assertRaisesRegex(ValueError,'unavailable'):
   record.check_history(candidate,previous)

 def test_append_a_new_measurement_file_preserves_every_previous_digest(self):
  previous={'measurement_files':{'camera.json':'previous'}}
  record.check_history({'measurement_files':{'camera.json':'previous','mixed.json':'new'}},previous)
  for revised in ({'mixed.json':'new'},{'camera.json':'changed'}):
   with self.assertRaisesRegex(ValueError,'measurement_files'):
    record.check_history({'measurement_files':revised},previous)
