import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'benchmarks'))
import performance_gate
def contract(**changes):return dict(dict.fromkeys(performance_gate.COMPATIBILITY,'fixture'),**changes)
class PerformanceGateTests(unittest.TestCase):
 def test_missing_workload_contract_is_not_assumed_compatible(self):
  self.assertFalse(performance_gate.compare({'contract':{},'trials':[]},{'contract':{},'trials':[]})['compatible'])
 def test_incompatible_resolutions_are_not_compared(self):
  a={'contract':contract(composition=[960,540]),'trials':[{'present_fps':60}]}
  b={'contract':contract(composition=[3840,2160]),'trials':[{'present_fps':20}]}
  result=performance_gate.compare(a,b);self.assertFalse(result['compatible'])
 def test_repeated_regression_is_an_investigation_trigger(self):
  a={'contract':contract(power='AC'),'trials':[{'present_fps':60,'seek_p95_ms':100}]*3}
  b={'contract':contract(power='AC'),'trials':[{'present_fps':56,'seek_p95_ms':120}]*3}
  r=performance_gate.compare(a,b);self.assertTrue(r['compatible']);self.assertTrue(r['investigate'])
  self.assertTrue(r['metrics']['present_fps']['repeated']);self.assertTrue(r['metrics']['seek_p95_ms']['investigate'])
 def test_variation_is_retained_for_review(self):
  a={'contract':contract(),'trials':[{'present_fps':50},{'present_fps':59},{'present_fps':60}]}
  b={'contract':contract(),'trials':[{'present_fps':57},{'present_fps':60},{'present_fps':61}]}
  r=performance_gate.compare(a,b);self.assertFalse(r['investigate']);self.assertEqual(r['metrics']['present_fps']['baseline_range'],[50,60])
