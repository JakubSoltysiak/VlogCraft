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
