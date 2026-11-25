import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks"))
from phase3b_stall_evidence import NO_PTS, ownership_window, reduce_record


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


def request(sequence, frame, generation, ready_mask):
    due = frame * 10000
    t = sequence * 10000
    layers = []
    for index in range(3):
        selected = bool(ready_mask & (1 << index))
        layers.extend([index + 1, index, index + 1, 5, frame, 1, 60, frame, 1, 60,
                       frame, frame + 1 if selected else NO_PTS, 3 if selected else 2, t - 30, t - 5,
                       int(selected), frame + 1 if selected else NO_PTS, NO_PTS, NO_PTS, NO_PTS,
                       6, 0, 0, 0, sequence, sequence, sequence, -1, 5])
    return [sequence, t, frame, generation, 1, due - 1, due, 7, ready_mask | 8, frame - 1, generation, 0, *layers]


def ownership_sample(t, *, pending=True, query=None, retired=None):
    row = sample(t)
    pool = 987654321
    row[6] = [72, 71 if pending else 72, 41, 3]
    for index in range(4):
        row[8 + index].extend([[0] * 7, [0] * 8, [0] * 5])
    row[9][9] = [pool, 64, 2, 6, 4, -(1 << 63), 0, t]
    row[9][10] = [pool, 1, 120, t, 4 + (t >= 240000)]
    selected = [t, pool, 4, 188, 0, 0, 0, 0, 0, 0]
    holds = [int(pending), 41, 2, 190000 if pending else t, pool, 1, 120, pool, 3, 144, 0, 0, 0]
    slots = [[holds, query or [41, 3, 195000, 196000, 0], retired or [0] * 3]]
    row.append([selected, [1, 24, 3, t], slots])
    return row


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

    def test_source_deadline_uses_one_request_and_reports_capture_limits(self):
        encoded = capture([sample(50000), sample(70000)])
        encoded.update(source_request_counts=[8, 8, 1], qpc_anchor="private anchor", first_source_miss={
            "frame": 42, "generation": 3, "overwritten": 0, "samples": encoded["incidents"][0]["samples"],
            "requests": [request(5, 41, 3, 7), request(6, 42, 3, 5),
                         request(7, 43, 3, 2), request(8, 44, 3, 7), ["private malformed row"]],
        })
        result = reduce_record(encoded)
        miss = result["first_source_miss"]
        self.assertEqual(miss["invalid_requests"], 1)
        self.assertEqual(miss["preceding_requests"][0]["frame"], 41)
        self.assertTrue(miss["first_missing_request"]["deadline_due_at_clock_sample"])
        self.assertEqual(miss["first_missing_request"]["layers"][1]["reason"], "missing_successor")
        self.assertIsNone(miss["first_missing_request"]["layers"][1]["successor_pts"])
        self.assertEqual(miss["first_all_intervals_verified"]["frame"], 44)
        self.assertIsNone(miss["ready_on_missed_frame"])
        self.assertEqual([row["sample_us"] for row in miss["watchdog_near_first_missing_request"]], [50000, 70000])
        self.assertEqual(result["source_request_counts"]["lost"], 1)
        self.assertNotIn("private", json.dumps(result))

    def test_source_recovery_does_not_cross_generations(self):
        encoded = {"version": 1, "incidents": [], "source_request_counts": [9, 9, 1], "first_source_miss": {
            "frame": 42, "generation": 3, "overwritten": 0,
            "requests": [request(6, 42, 3, 6), request(8, 42, 4, 7), request(9, 43, 3, 7)],
        }}
        miss = reduce_record(encoded)["first_source_miss"]
        self.assertEqual(miss["missing_request_sequences"], 1)
        self.assertIsNone(miss["first_all_layers_selected"])

    def test_playing_backstep_retains_contiguous_requests_and_decode_epochs(self):
        a, b, c = [request(sequence, frame, 3, 0) for sequence, frame in ((7, 42), (8, 41), (9, 42))]
        b[15] = c[15] = 6
        encoded = {"version": 1, "incidents": [], "source_request_counts": [13, 13, 0], "first_source_miss": {
            "frame": 42, "generation": 3, "overwritten": 0,
            "requests": [a, b, c, request(11, 41, 3, 0), request(12, 40, 4, 0)]}}
        backsteps = reduce_record(encoded)["first_source_miss"]["retained_playing_backsteps"]
        self.assertEqual(backsteps["count"], 1)
        span, = backsteps["reported_spans"]
        self.assertEqual([row["frame"] for row in span], [42, 41, 42])
        self.assertEqual([row["layers"][0]["decode_epoch"] for row in span], [5, 6, 6])

    def test_refill_edges_distinguish_present_overlap_and_wait_reasons(self):
        rows = []
        for t in range(90_000, 171_000, 10_000):
            row = sample(t)
            row[8][0] = "dxgi_present"
            row[8].append([100000, 41, 3, 0, 0, 0, 0] if t < 150000 else [
                0, 0, 0, 100000, 150000, 41, 3])
            row[9][0] = "refill_deferred"
            row[9][7] = [0, 0, 90000]
            row[9].append([90000, 0 if t < 160000 else 160000, 0 if t < 160000 else 2, 512, 768, 5, 1])
            row[10][0] = "queue_full"
            row[10][7] = [0, 0, 90000]
            row[10].append([0] * 7)
            row[11].append([0] * 7)
            rows.append(row)
        rows[4][1] = 4  # Source 1's torn sample excludes both adjacent pairs.
        encoded = {"version": 1, "incidents": [], "source_request_counts": [16, 16, 0], "first_source_miss": {
            "frame": 42, "generation": 3, "overwritten": 0, "samples": rows,
            "requests": [request(16, 42, 3, 6)]}}
        miss = reduce_record(encoded)["first_source_miss"]
        present = miss["pacing_near_first_missing_request"]["reported_present_intervals"][0]
        hold = present["refill_holds"][0]
        self.assertEqual(miss["first_retained_three_layer_missing_successor"]["layer_mask"], 7)
        self.assertTrue(present["latest_completed_before_request"])
        self.assertEqual(present["completed_duration_us"], 50_000)
        self.assertEqual(hold["observed_overlap_us"], 50_000)
        self.assertEqual(hold["release_reason"], "renderer")
        self.assertEqual(hold["headroom_pts"], 256)
        self.assertTrue(hold["known_held_at_present_return"])
        self.assertEqual(present["sampled_interval"]["coverage_by_lane"]["source_1"], {"refill_deferred": 30_000})
        self.assertEqual(present["sampled_interval"]["coverage_by_lane"]["source_2"], {"queue_full": 50_000})
        self.assertEqual(present["sampled_interval"]["device_wait_us_by_lane"], {"source_3": 50_000})

    def test_surface_ownership_deduplicates_references_and_fences_reused_slots(self):
        rows = [
            ownership_sample(200000),
            ownership_sample(220000, query=[41, 2, 219000, 219100, 1]),
            ownership_sample(240000, pending=False, query=[41, 2, 238000, 239000, 0], retired=[41, 2, 239500]),
        ]
        result = reduce_record(capture(rows))["incidents"][0]["ownership_during_gap"]
        self.assertEqual(result["observed_query_attempts"], {"ready": 2, "unready": 1})
        self.assertEqual(result["observed_retirements"], 1)
        self.assertEqual(result["first_and_last_zero_pending_sample_us"], [240000, 240000])
        self.assertEqual(result["first_and_last_retirements"][0]["released_us"], 239500)
        span = result["longest_observed_pending_spans"][0]
        self.assertEqual(span["generation"], 2)
        self.assertEqual(span["sampled_query_states"], {"no_check_observed": 1, "unready": 1})
        pool = result["source_pools"][0]
        self.assertEqual(pool["pool_array_size"], 64)
        self.assertEqual(pool["peak_unique_slices"]["app_union"], 5)
        self.assertEqual(pool["peak_unique_slices"]["gpu_slots_only"], 1)
        self.assertEqual(pool["first_and_last_decoder_received_count"], [4, 5])
        self.assertEqual(pool["first_and_last_decoder_output_pts"], [120, 120])
        self.assertEqual(result["peak_cached_views_observed"], 24)
        self.assertNotIn("987654321", json.dumps(result))

    def test_ownership_omits_torn_tuples_and_mismatched_pending_counts(self):
        rows = [ownership_sample(t) for t in [210000, 220000, 230000, 240000]]
        rows[0][1] = 32
        rows[1][1] = 128
        rows[2][6][1] = rows[2][6][0]
        result = ownership_window(rows, 210000, 240000)
        self.assertEqual(result["coverage"], {
            "samples": 4, "torn_renderer_samples": 1, "transition_samples": 1, "coherent_renderer_samples": 2,
        })
        self.assertEqual(result["source_pools"][0]["samples"], 1)


if __name__ == "__main__":
    unittest.main()
