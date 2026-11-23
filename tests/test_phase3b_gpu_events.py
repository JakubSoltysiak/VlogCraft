import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks"))
from phase3b_gpu_events import describe_buffer, etl_clock, intervals


class GPUEventEvidence(unittest.TestCase):
    def test_filetime_precision_and_date_rollover(self):
        stats = ("Start time (UTC)     : 2026/11/23:23:59:59.9999999\n"
                 "End time (UTC)       : 2026/11/24:00:00:00.0000001")
        self.assertEqual(etl_clock(stats, "End") - etl_clock(stats, "Start"), 2)

    def test_wait_attribution_requires_stable_bracketed_edges(self):
        def sample(time, torn=0, owner_since=80):
            devices = ([0, 0, 0], [0, 1, owner_since], [1, 0, 90], [0, 0, 0])
            return [time, torn, *([0]*6), *([[0]*7+[device] for device in devices])]

        rows = [sample(500), sample(4000), sample(7000, 8), sample(9000), sample(10000, owner_since=9500)]
        call = (15000, "source_1", 6, 0, 15000)
        observation = describe_buffer(call, rows)
        self.assertEqual(observation["bracketed_shared_device_wait_us_by_peer"], {"source_2": 3500})

    def test_no_invented_span_without_a_missing_request(self):
        self.assertEqual(intervals({"incidents": [], "first_source_miss": {
            "frame": -1, "generation": -1, "requests": [], "samples": []}}), [])
