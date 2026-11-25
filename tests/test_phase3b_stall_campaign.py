import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks"))
from phase3b_stall_campaign import (
    BASELINES, DIAGNOSTIC_KEYS, IMAGE, LEGACY_POLL_KEY, PICTURE_HANDOFF_KEY, PUBLISHED, REFILL_IMAGE, effective_policy,
    export_refill, prepare_refill, read, refill_baselines, refill_plan, run, run_refill_pair, run_refill_trial, save,
    summarize_refill_attempt,
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

    def test_picture_handoff_can_only_be_declared_on_ordinary_candidate(self):
        order, environment = refill_plan("ordinary", "B", False, candidate_picture_handoff=True)
        self.assertEqual(order, (("R", "F"), ("F", "R")))
        self.assertEqual(environment["R"], dict.fromkeys((*DIAGNOSTIC_KEYS, PICTURE_HANDOFF_KEY)))
        self.assertEqual(environment["F"], {**environment["R"], PICTURE_HANDOFF_KEY: "1"})
        for comparison in ("refill", "bounded", "poll-order"):
            with self.subTest(comparison=comparison), self.assertRaisesRegex(ValueError, "requires --comparison ordinary"):
                refill_plan(comparison, "B", True, candidate_picture_handoff=True)
        with TemporaryDirectory() as folder:
            results = Path(folder)
            worker = results / "worker.exe"
            worker.write_bytes(b"historical worker")
            with self.assertRaisesRegex(ValueError, "support for picture handoff"):
                prepare_refill(results, worker, results, {}, comparison="ordinary", candidate_picture_handoff=True)
            with self.assertRaisesRegex(ValueError, "requires source-first polling"):
                prepare_refill(results, worker, results, {}, comparison="ordinary", candidate_poll_policy="eager",
                               candidate_picture_handoff=True)

    def test_picture_handoff_flag_is_scrubbed_from_other_trials(self):
        with TemporaryDirectory() as folder, patch.dict(os.environ, {PICTURE_HANDOFF_KEY: "1"}), \
                patch("phase3b_stall_campaign.verify"), patch("phase3b_stall_campaign.media_stats", return_value=[]), \
                patch("phase3b_stall_campaign.conditions", return_value={"ac": True}), \
                patch("phase3b_stall_campaign.subprocess.run", return_value=SimpleNamespace(returncode=0)) as launch:
            results = Path(folder)
            image = {"diagnostic_host_baseline": "cand4", "packages": {"cand4": {"executable": "frozen"}},
                     "diagnostic_executable": "candidate", "diagnostic_worker_sha256": "worker",
                     "media": folder, "media_stats": []}
            for comparison, arm, opt_in in (("ordinary", "R", True), ("ordinary", "F", True),
                                             ("ordinary", "F", False), ("poll-order", "D", False)):
                with self.subTest(comparison=comparison, arm=arm, opt_in=opt_in):
                    _, environment = refill_plan(comparison, "D", True, candidate_picture_handoff=opt_in)
                    label = f"{comparison}-{arm}-{opt_in}"
                    run_refill_trial(results, {**image, "comparison": comparison, "arm_environment": environment},
                                     label, 1, 1, arm)
                    expected = "1" if arm == "F" and opt_in else None
                    self.assertEqual(launch.call_args.kwargs["env"].get(PICTURE_HANDOFF_KEY), expected)
                    receipt = read(results / f"{label}-conditions.json")
                    self.assertEqual(receipt["diagnostic_flag"].get(PICTURE_HANDOFF_KEY), expected)
            save(results / IMAGE, {"baseline_label": "cand4", "frozen_msi_sha256": BASELINES["cand4"]["msi_sha256"],
                                   "control": "frozen", "media": folder, "media_stats": []})
            self.assertEqual(run(results, "frozen", 1), 0)
            self.assertNotIn(PICTURE_HANDOFF_KEY, launch.call_args.kwargs["env"])

    def test_picture_handoff_candidate_needs_observed_active_draws_and_drain(self):
        policy = {"completion_poll_policy": "source_first", "refill_policy": "bounded", "stall_recording": False}
        _, environment = refill_plan("ordinary", "D", False, candidate_picture_handoff=True)
        image = {"comparison": "ordinary", "candidate_picture_handoff": True, "candidate_poll_policy": "source_first",
                 "diagnostic_worker_sha256": "worker", "physical_preview_px": [958, 539],
                 "diagnostic_host_baseline": "cand4", "packages": {"cand4": BASELINES["cand4"]},
                 "arm_environment": environment, "reverse_review_required": True}
        with TemporaryDirectory() as folder:
            results = Path(folder)
            for case, (initial, active, final), passed in (
                ("valid", ((True, 3), (True, 10), (True, 12)), True),
                ("fallback", ((True, 3), (True, 10), (False, 12)), False),
                ("equivalent_integer", ((1, 3), (1, 10), (1, 12)), False),
                ("no_drain", ((True, 3), (True, 10), None), False),
                ("paused_only", ((True, 3), (True, 3), (True, 3)), False),
                ("invalid_count", ((True, 0), (True, True), (True, 2)), False),
                ("decreasing_count", ((True, 3), (True, 10), (True, 9)), False),
            ):
                with self.subTest(case=case):
                    trial = results / case
                    trial.mkdir()
                    save(trial / "native-playback.json", {
                        name: {**policy, "picture_handoff": values[0], "handoff_draws": values[1]}
                        for name, values in zip(("base", "last", "drained_last"), (initial, active, final))
                        if values is not None
                    })
                    report = summarize_refill_attempt(results, {"trial": case, "arm": "F", "supervisor_exit": 0}, image)
                    self.assertIs(report["controls"]["effective_picture_handoff"], passed)
                    if passed:
                        self.assertEqual(report["effective_policy"]["picture_handoff"]["active_draws"], 7)
                        self.assertEqual(report["effective_policy"]["picture_handoff"]["drained_draws"], 12)
            frozen = summarize_refill_attempt(results, {"trial": "historical", "arm": "R", "supervisor_exit": 0}, image)
            self.assertNotIn("effective_picture_handoff", frozen["controls"])

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
