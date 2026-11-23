import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks"))
from phase3b_stall_evidence import reduce_record


def sample(t):
    def lane(stage, identity, waiting, owned):
        return [stage, "idle", [100000, 1, 0, 0, 0, 0, t // 100, 1, 190000 + identity],
                [identity, identity, 1, 15360], [1, 0, 2, 3, 6, 1, 4, 1, 0, 0, t],
                [42, 3, 1, 0, 2, 2], [0, 0, 4], [waiting, owned, 100000]]

    return [t, 8 if t == 200000 else 0, 100000, [0, 3, 1, t], [42, 3, t, 711000, 100000],
            [41, 3, 100000], [72, 72, 41, 3], 72,
            lane("wait_source_retry", 0, 0, 0), lane("receive_picture", 1, 0, 1),
            lane("send_packet", 2, 1, 0), lane("private raw value", 3, 1, 0)]


def capture(samples):
    return {"version": 1, "incidents": [
        {"last_frame": 41, "generation": 3, "observed_age_us": 600000, "recovered": 1, "transition": 0,
         "truncated": 0, "dropped_middle_samples": 0, "samples": samples}]}


class Phase3BStallEvidence(unittest.TestCase):
    def test_parallel_observations_respect_torn_lanes(self):
        result = reduce_record(capture([sample(t) for t in range(50000, 850001, 10000)]))
        incident = result["incidents"][0]
        self.assertEqual(incident["prefix_us"], 50000)
        self.assertEqual(incident["post_stall_us"], 150000)
        attributed = incident["attributed_intervals"]
        self.assertEqual(attributed["globally_coherent_us"], 600000)
        self.assertEqual(attributed["coverage_by_lane"]["source_1"]["receive_picture"], 600000)
        self.assertEqual(attributed["coverage_by_lane"]["source_2"]["send_packet"], 580000)
        wait = next(row for row in attributed["device_wait_overlaps"] if row["waiter_lane"] == "source_2")
        self.assertEqual(wait["observed_us"], 580000)
        self.assertEqual(attributed["observed_progress_by_lane"]["source_1"]["packet_reads"], 0)
        self.assertEqual(attributed["gpu_submissions"], 0)
        self.assertEqual(incident["source_state"]["source_1"]["queue_depth_range"], [3, 3])
        encoded = json.dumps(result)
        self.assertNotIn("190001", encoded)
        self.assertNotIn("private raw value", encoded)

    def test_sampling_hole_remains_unattributed(self):
        samples = [sample(t) for t in range(50000, 850001, 10000) if not 550000 <= t <= 590000]
        incident = reduce_record(capture(samples))["incidents"][0]
        self.assertEqual(incident["largest_retained_poll_gap_us"], 60000)
        attribution = incident["attributed_intervals"]
        self.assertEqual(attribution["sparse_us"], 60000)
        self.assertEqual(attribution["globally_coherent_us"], 540000)
        self.assertEqual(attribution["device_wait_overlaps"][0]["observed_us"], 540000)


if __name__ == "__main__":
    unittest.main()
