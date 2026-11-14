import unittest
from types import SimpleNamespace
from unittest.mock import patch
import render_engine as e
class WorkerBudgetTests(unittest.TestCase):
 def test_measured_budget_is_bounded_and_other_paths_keep_four(self):
  with patch.object(e.os,'cpu_count',return_value=24),patch.object(e.psutil,'virtual_memory',return_value=SimpleNamespace(available=8*1024**3)):
   self.assertEqual(e.encode_workers('libx264',3840,2160,'60000/1001'),8)
   for encoder,w,h,rate in [('libx264',1920,1080,60),('libx264',3840,2160,120),('libx264',7680,4320,60),('h264_amf',3840,2160,60)]:
    self.assertEqual(e.encode_workers(encoder,w,h,rate),4)
  with patch.object(e.os,'cpu_count',return_value=8):
   self.assertEqual(e.encode_workers('libx264',3840,2160,60),4)
  with patch.object(e.os,'cpu_count',return_value=24),patch.object(e.psutil,'virtual_memory',return_value=SimpleNamespace(available=2*1024**3)):
   self.assertEqual(e.encode_workers('libx264',3840,2160,60),4)
