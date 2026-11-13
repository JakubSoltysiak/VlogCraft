import tempfile,unittest
from pathlib import Path
from unittest import mock
import performance_profile as p
class ProfileTests(unittest.TestCase):
 def test_sanitizer_rejects_machine_identifiers(self):
  data=p.sanitize({'cpu':{'Name':'CPU','SerialNumber':'private','UserName':'private'},'storage':[{'FriendlyName':'SSD','SerialNumber':'secret'}],'hostname':'private'})
  self.assertEqual(data['cpu'],[{'Name':'CPU'}]);self.assertEqual(data['storage'],[{'FriendlyName':'SSD'}]);self.assertNotIn('hostname',data)
 def test_low_memory_recommendation_does_not_change_export(self):
  r=p.recommend({'hardware':{'available_memory_MiB':2048}})
  self.assertEqual(r['preview_width'],960);self.assertFalse(r['export_settings_changed']);self.assertTrue(r['native_experimental'])
 def test_diagnostics_is_single_owned_worker_and_atomic_local_result(self):
  with tempfile.TemporaryDirectory() as folder:
   d=p.Diagnostics(folder,folder)
   with mock.patch.object(p,'inventory',return_value={'available':True,'available_memory_MiB':4096}):
    d.start();d.thread.join(5)
   self.assertEqual(d.status()['status'],'complete');self.assertTrue((Path(folder)/'performance-profile.json').is_file());d.close()
   with self.assertRaises(ValueError):d.start()

 def test_close_reaps_owned_diagnostic_process(self):
  import sys,time
  with tempfile.TemporaryDirectory() as folder:
   d=p.Diagnostics(folder,folder)
   def busy(bundle,cache,runner):
    runner([sys.executable,'-c','import time;time.sleep(60)'],capture_output=True,text=True,timeout=65)
    return {'available_memory_MiB':4096}
   with mock.patch.object(p,'inventory',side_effect=busy):
    d.start();deadline=time.monotonic()+5
    while not d.processes and time.monotonic()<deadline:time.sleep(.01)
    owned=list(d.processes);self.assertTrue(owned);d.close()
   self.assertTrue(all(child.poll() is not None for child in owned));self.assertFalse(d.thread.is_alive());self.assertFalse(d.processes)
