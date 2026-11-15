import sys,unittest
from pathlib import Path
from benchmarks.memory_metrics import slope

class MemoryMetrics(unittest.TestCase):
 def test_known_linear_growth_uses_minutes_and_exact_slope(self):
  result=slope([(n*30,100+n) for n in range(12)])
  self.assertAlmostEqual(result['MiB_per_minute'],2,places=8)
  self.assertLess(abs(result['approximate_95_percent_interval'][0]-2),1e-7)
 def test_constant_series_and_insufficient_evidence(self):
  self.assertFalse(slope([(0,1),(30,2)])['available'])
  self.assertAlmostEqual(slope([(n*30,500) for n in range(12)])['MiB_per_minute'],0,places=8)
