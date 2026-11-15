import unittest
from benchmarks.observation_window import observe

class ObservationTests(unittest.TestCase):
    def exercise(self,cost):
        now=[0.];samples=[]
        def wait(seconds):now[0]+=seconds
        def sample():samples.append(now[0]);now[0]+=cost
        elapsed=observe(30,wait,sample,period=5,clock=lambda:now[0])
        return elapsed,samples
    def test_sampling_cost_consumes_the_wall_time_budget(self):
        elapsed,samples=self.exercise(2)
        self.assertEqual(elapsed,32);self.assertEqual(samples,[5,10,15,20,25,30])
    def test_long_callback_does_not_schedule_catch_up_bursts(self):
        elapsed,samples=self.exercise(8)
        self.assertEqual(elapsed,33);self.assertEqual(samples,[5,15,25])
    def test_zero_cost_waits_exactly_the_requested_window(self):
        self.assertEqual(self.exercise(0)[0],30)
    def test_invalid_duration_rejected(self):
        with self.assertRaises(ValueError):observe(0,lambda t:None,lambda:None)
