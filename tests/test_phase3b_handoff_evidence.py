import copy
import json
from pathlib import Path
import tempfile
import unittest

from benchmarks.phase3b_handoff_evidence import aggregates, paired, stage_summary, stall_window, summarize_trial


class HandoffEvidence(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory=Path(temporary.name)/"test"
        self.directory.mkdir()
        self.supervisor=self.directory.with_name("test-supervisor")
        self.supervisor.mkdir()
        self.save(self.supervisor/"supervisor.json",{"exit_code":0,"process_ownership":{"remaining_owned_processes":0}})
        self.save(self.directory.with_name("test-conditions.json"),{"conditions":{"desktop_hz":120}})
        self.receipt={
            "rate":"60/1","seconds":60,"original_resolution":[3840,2160],"program_resolution":[3840,2160],
            "samples":2880000,"expected_samples":2880000,"underruns":0,"reached_end":True,"proxies":False,
            "cut_seconds":.5,"source_switches":False,"video_tracks":3,"audio_tracks":3,
            "distinct_sequence_fps":59.8,"physical_alignment":{"window_dpi":168},
            "gpu_counter_observer":"legacy high-frequency PDH GPU observer; cost recorded separately",
            "base":{"skipped_sequence_frames":5,"source_wait_iterations":7},
            "last":{"surface_width":356,"surface_height":200,"completed_sequence_frame":3599,
                    "timings":{"playback_present_interval":{"count":3598,"max_ms":50,"p99_upper_ms":28}},
                    "skipped_sequence_frames":5,"source_wait_iterations":19,"selected":[{"clip":"private-id"}]},
            "conditions":{"samples":[{"ac_power":True}]},"window_condition":{"condition_held":True},
            "source_path":"private-files-camera","browser_errors":["private-project-details"],
            "resources":{"peak_summed_working_set_MiB":3000},
        }

    @staticmethod
    def save(path,data):
        path.write_text(json.dumps(data),encoding="utf-8")

    def summarize(self):
        self.save(self.directory/"native-playback.json",self.receipt)
        return summarize_trial("control","composition","trial",self.directory)

    def test_true_zero_counters_use_preplay_base_and_ignore_private_fields(self):
        row=self.summarize()
        self.assertEqual(row["outcome"],"passed")
        self.assertEqual(row["playback"]["counter_delta"]["skipped_sequence_frames"],0)
        self.assertEqual(row["playback"]["counter_delta"]["source_wait_iterations"],12)
        self.assertNotIn("private-",json.dumps(row))

    def test_missing_window_audio_and_supervisor_do_not_count_as_passing(self):
        self.receipt["conditions"]["samples"]=[]
        self.receipt.pop("samples")
        self.receipt["last"]["timings"]["playback_present_interval"]={"count":0,"max_ms":0}
        (self.supervisor/"supervisor.json").unlink()
        row=self.summarize()
        self.assertEqual(row["outcome"],"unverified")
        self.assertIsNone(row["screen"]["exact_pcm"]);self.assertIsNone(row["conditions"]["ac_all"])
        self.assertIsNone(row["screen"]["at_most_100ms_gap"])

    def test_functional_success_with_stall_remains_in_aggregate(self):
        row=self.summarize()
        self.receipt["last"]["timings"]["playback_present_interval"]["max_ms"]=1000
        self.receipt["last"]["skipped_sequence_frames"]=35
        bad=self.summarize()
        self.assertFalse(bad["screen"]["under_30_skips"])
        self.assertTrue(bad["screen"]["functional_receipt"])
        result=aggregates([row,bad])[0]
        self.assertEqual(result["screens"]["failed"],1)
        self.assertEqual(result["max_gap_ms"]["max"],1000)

    def test_failed_attempt_without_data_is_retained_and_unmatched(self):
        self.save(self.supervisor/"supervisor.json",{"exit_code":1})
        row=summarize_trial("candidate","switch","incomplete",self.directory)
        self.assertTrue(row["receipt_missing"]);self.assertEqual(row["outcome"],"failed")
        self.assertFalse(paired(row,row)["comparable"])

    def test_pairing_requires_geometry_and_observer_equivalence(self):
        before=self.summarize()
        after=copy.deepcopy(before);after["playback"]["actual_surface_px"]=[960,540]
        self.assertIn("actual_surface_px",paired(before,after)["mismatches"])
        after["playback"]["actual_surface_px"]=[356,200];after["playback"]["distinct_sequence_fps"]=59.9
        self.assertAlmostEqual(paired(before,after)["after_minus_before"]["distinct_fps"],.1)
        after["conditions"]["desktop_hz"]=None
        self.assertIn("refresh_hz",paired(before,after)["unverified_contract"])

    def test_duplicate_native_stage_entry_in_two_rings_counted_once(self):
        event={"stage":"create_decoder","start_us":10,"duration_us":3000,"frame":24,"decoder":1}
        out=stage_summary({"recent_stages":[event],"longest_stages":[event]})
        self.assertEqual(out["retained_stage_maxima"]["create_decoder"]["retained_count"],1)

    def test_simultaneous_packet_calls_never_exceed_clipped_wall_time(self):
        gap={"begin_us":10,"end_us":100,"frame":24,"lost":2,"matching_recent_events":3,
             "stages":[{"stage":"send_packet","start_us":1,"duration_us":30},
                       {"stage":"send_packet","start_us":20,"duration_us":90},
                       {"stage":"device_lock_owned","start_us":20,"duration_us":90}]}
        bounded=stall_window(gap)["overlapping_by_stage"]
        self.assertEqual(bounded["send_packet"]["covered_wall_us"],90)
        self.assertEqual(bounded["device_lock_owned"]["covered_wall_us"],80)
