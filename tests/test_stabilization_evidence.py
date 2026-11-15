import unittest
from benchmarks.stabilization_evidence import stalls,roles

class EvidenceTests(unittest.TestCase):
    def test_counter_reset_is_not_reported_as_negative_lost_frames(self):
        rows=[{'wall_seconds':t,'skipped_sequence_frames':n} for t,n in [(5,0),(6,4),(7,0),(8,2)]]
        d=stalls({'base':{'wall_seconds':5},'status_trace':rows,'last':{'skipped_sequence_frames':2},'window_condition':{'samples':[]}})
        self.assertEqual(d['observed_counter_increases'],6);self.assertIsNone(d['first_visibility_violation_seconds'])
        self.assertEqual(d['largest_counter_increases'][0]['native_elapsed_begin'],0)
    def test_reports_visibility_separately_without_inventing_event_alignment(self):
        d=stalls({'base':{'wall_seconds':10},'status_trace':[],'last':{'skipped_sequence_frames':3},'window_condition':{'samples':[{'seconds':99,'foreground_owned':False}]}})
        self.assertEqual(d['first_visibility_violation_seconds'],99);self.assertEqual(d['observed_counter_increases'],0)
    def test_post_stop_release_does_not_distort_active_role_comparison(self):
        d=roles({'rows':[{'stage':s,'WebView_roles':{'renderer':{'private_commit_MiB':n}}} for s,n in [('active',20),('active',30),('diagnostic_GC',2)]]})
        self.assertEqual(d['renderer'],{'first_MiB':20,'last_MiB':30})
