import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'benchmarks'))
from consistency import summary,percentile
from runtime_trace import windows,active_windows
class ConsistencyTests(unittest.TestCase):
 def test_failed_and_poor_trials_remain_visible(self):
  result=summary([{'exit_code':0,'fps':60,'skips':0,'underruns':0},{'exit_code':0,'fps':55,'skips':600,'underruns':0},{'exit_code':1}])
  self.assertEqual(result['fps_worst'],55);self.assertEqual(result['failed_trials'],1)
  self.assertEqual(result['at_least_59_5'],1);self.assertEqual(result['skips_all'],[0,600])
 def test_time_windows_expose_stalls_instead_of_full_run_average(self):
  rows=[{'wall_seconds':n/10,'present_calls':n*6 if n<10 else 60+(n-10)*3} for n in range(21)]
  result=windows(rows,1)
  self.assertEqual(result['minimum_fps'],30);self.assertGreater(result['count'],1)
 def test_percentile_retains_low_tail(self):
  self.assertAlmostEqual(percentile([60]*9+[55],.05),57.25)


 def test_terminal_hold_is_reported_separately_from_active_playback(self):
  rows=[{'wall_seconds':n/2,'present_calls':min(n*30,120),'sequence_frame':min(n*30,120)} for n in range(7)]
  self.assertLess(windows(rows,1)['minimum_fps'],60)
  self.assertEqual(active_windows(rows,1,120)['minimum_fps'],60)
