"""Acceptance checks for the isolated Phase 2 benchmark driver."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
from benchmarks import render_phase2 as lab


class Phase2HarnessTests(unittest.TestCase):
    def test_strict_quality_requires_independent_outputs(self):
        lab.validate_modes(['uhd-mask'],['ffmpeg','warp32'],True,False)
        for names,modes,skip in (
            (['uhd-mask'],['ffmpeg'],False), (['uhd-mask'],['gpu32'],False),
            (['uhd-mask'],['ffmpeg','simd'],True), (['uhd-sustained'],['ffmpeg','gpu32'],False),
        ):
            with self.subTest(names=names,modes=modes,skip=skip), self.assertRaises(ValueError):
                lab.validate_modes(names,modes,True,skip)

    def test_missing_ffmpeg_picture_timing_fails_the_trial(self):
        case=lab.Scenario('timing-check',16,16)
        with tempfile.TemporaryDirectory() as scratch:
            with patch.object(lab,'ffmpeg_graph',return_value='[0:v]null[output]'), \
                 patch.object(lab,'call',return_value=SimpleNamespace(stderr=b't:0.01 avg:')):
                with self.assertRaisesRegex(ValueError,'one processing sample per picture'):
                    lab.reference_trial(Path(scratch),case,[],2,0,[],None)

    def test_transient_power_change_fails_ac_even_with_matching_endpoints(self):
        receipt={'conditions_start':{'ac_power':True},'conditions_last':{'ac_power':True},
                 'observed_conditions':{'samples':[{'ac_power':True},{'ac_power':False},{'ac_power':True}]},
                 'results':[{'runs':{'gpu32':[{'ac_before':True,'ac_after':True}]}}]}
        self.assertFalse(lab.all_ac(receipt))
        receipt['observed_conditions']['samples'][1]['ac_power']=True
        self.assertTrue(lab.all_ac(receipt))

    def test_held_picture_checks_keep_hard_edge_and_alpha_errors_across_blocks(self):
        case=lab.Scenario('block-check',5,1)
        with tempfile.TemporaryDirectory() as scratch:
            baseline,tested=(Path(scratch)/name for name in ('base','candidate'))
            picture=np.ones((1,5,4),dtype='<f4')*.5
            picture.tofile(baseline)
            changed=picture.copy()
            changed[0,4,3]+=.01
            changed.tofile(tested)
            with patch.object(lab,'QUALITY_BLOCK_PIXELS',2):
                result=lab.compare_pictures(baseline,tested,case,1)
            self.assertFalse(result['passed'])
            self.assertAlmostEqual(result['max_alpha'],.01)
            self.assertAlmostEqual(result['mean_edge_alpha_error'],.002)

    def test_planar_reference_comparison_preserves_rgb_order_across_blocks(self):
        case=lab.Scenario('planar-check',3,1)
        with tempfile.TemporaryDirectory() as scratch:
            baseline,tested=(Path(scratch)/name for name in ('base','candidate'))
            np.array([.2]*3+[.3]*3+[.1]*3,dtype='<f4').tofile(baseline)
            np.tile(np.array([.1,.2,.3,1],dtype='<f4'),(3,1)).tofile(tested)
            with patch.object(lab,'QUALITY_BLOCK_PIXELS',2):
                result=lab.compare_pictures(baseline,tested,case,1,reference=True)
            self.assertTrue(result['passed'])
            self.assertEqual(result['max_rgb'],0.)
