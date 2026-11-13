import unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'benchmarks'))
from cadence import cadence
class CadenceTests(unittest.TestCase):
 def test_sixty_on_120_repeats_each_source_frame_twice(self):
  r=cadence(60,120);self.assertEqual(r['unique_source_frames'],600);self.assertEqual(r['refreshes_per_frame_values'],[2]);self.assertEqual(r['interpolated_frames'],0)
 def test_fractional_rate_preserves_rational_hold(self):
  r=cadence('60000/1001',120,100);self.assertEqual(r['unique_source_frames'],5994);self.assertEqual(r['refreshes_per_frame_values'],[2,3])
