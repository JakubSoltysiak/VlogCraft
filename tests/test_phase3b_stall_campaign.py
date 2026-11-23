from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks"))
from phase3b_stall_campaign import (
    BASELINES, DIAGNOSTIC_KEYS, LEGACY_POLL_KEY, PUBLISHED, REFILL_IMAGE, effective_policy, export_refill, read,
    refill_baselines, refill_plan, run_refill_pair, save,
)


class PollingCampaignTests(unittest.TestCase):
    def test_bounded_poll_comparison_changes_only_polling_order(self):
        order, environment = refill_plan("poll-order", "D", legacy_refill_supported=True)
        self.assertEqual(order, (("C", "D"), ("D", "C")))
        self.assertEqual(refill_baselines("poll-order", "D"), ("cand4", "cand3"))
        self.assertEqual(environment["D"], dict.fromkeys(DIAGNOSTIC_KEYS))
        self.assertEqual(environment["C"], {**environment["D"], LEGACY_POLL_KEY: "1"})
        with self.assertRaisesRegex(ValueError, "expiring refill policy"):
            refill_plan("poll-order", "D", legacy_refill_supported=False)

    def test_policy_and_counters_come_from_status_and_drained_receipt(self):
        paused = {"completion_poll_policy": "source_first", "refill_policy": "bounded", "stall_recording": True,
                  "combined_poll_opportunities": 1, "source_wait_poll_bypasses": 2}
        active = {**paused, "combined_poll_opportunities": 11, "source_wait_poll_bypasses": 2}
        playback = {"base": paused, "last": active, "drained_last": active}
        observed = effective_policy(playback)
        self.assertTrue(observed["consistent_through_drain"])
        self.assertEqual(observed["combined_poll_opportunities"], 10)
        self.assertEqual(observed["source_wait_poll_bypasses"], 0)
        playback["drained_last"] = {**active, "refill_policy": "unlimited"}
        self.assertFalse(effective_policy(playback)["consistent_through_drain"])
        self.assertFalse(effective_policy({})["consistent_through_drain"])

    def test_reverse_poll_pair_needs_prior_valid_explicit_review(self):
        with TemporaryDirectory() as folder:
            results = Path(folder)
            save(results / REFILL_IMAGE, {"order": [["C", "D"], ["D", "C"]], "reverse_review_required": True})
            with self.assertRaisesRegex(ValueError, "valid review"):
                run_refill_pair(results, 2, reverse_reviewed=True)
            save(results / "pair-1-review.json", {"comparison_valid": True})
            with self.assertRaisesRegex(ValueError, "--reverse-reviewed"):
                run_refill_pair(results, 2)

    def test_ordinary_candidate_failure_gates_reverse_pair(self):
        order, environment = refill_plan("ordinary", "B", legacy_refill_supported=False)
        self.assertEqual(order, (("R", "F"), ("F", "R")))
        self.assertEqual(environment["R"], environment["F"])
        self.assertTrue(all(value is None for value in environment["R"].values()))
        with TemporaryDirectory() as folder:
            results = Path(folder)
            save(results / REFILL_IMAGE, {"order": order, "comparison": "ordinary", "reverse_review_required": True})
            save(results / "pair-1-review.json", {"comparison_valid": True, "attempts": [
                {"arm": "F", "performance_screens": {"at_most_100ms_gap": False}},
            ]})
            with self.assertRaisesRegex(ValueError, "missed a timing screen"):
                run_refill_pair(results, 2, reverse_reviewed=True)

    def test_interrupted_pair_exports_the_observed_attempt_without_paths(self):
        order, environment = refill_plan("poll-order", "D", legacy_refill_supported=True)
        with TemporaryDirectory() as folder:
            results = Path(folder)
            save(results / REFILL_IMAGE, {
                "order": order, "comparison": "poll-order", "reference_hold_arm": "D", "reverse_review_required": True,
                "arm_environment": environment, "diagnostic_host_baseline": "cand4", "diagnostic_build": None,
                "diagnostic_worker_sha256": "1" * 64, "declared_trial_seconds": 60,
                "media_sha256": ["2" * 64] * 3, "media": str(results), "physical_preview_px": [958, 539],
                "stopping_rule": "No more than two pairs.", "packages": {
                    label: {**BASELINES[label], "published_commit": PUBLISHED[label], "msi": str(results / label)}
                    for label in ("cand4", "cand3")
                },
            })
            save(results / "pair-1-start.json", {"pair": 1, "order": order[0]})
            save(results / "pair-1-1-c-conditions.json", {"executable": str(results / "private-host")})
            output = results / "evidence.json"
            export_refill(results, output)
            self.assertNotIn("private-host", output.read_text(encoding="utf-8"))
            pairs = read(output)["pairs"]
            self.assertEqual([pair["pair"] for pair in pairs], [1])
            self.assertFalse(pairs[0]["comparison_valid"])
            self.assertEqual([attempt["trial"] for attempt in pairs[0]["attempts"]], ["pair-1-1-c"])
            self.assertIsNone(pairs[0]["attempts"][0]["supervisor_exit"])
