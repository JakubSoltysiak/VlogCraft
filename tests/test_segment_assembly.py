from fractions import Fraction
import unittest

from benchmarks.phase3a_segment_assembly import tile_durations


class SegmentTilingTests(unittest.TestCase):
    def test_round_absolute_endpoints_at_fractional_rates(self):
        spans = [(i,i+1) for i in range(24)]
        durations = tile_durations(spans,24,Fraction(24000,1001))
        self.assertEqual(sum(durations),1_001_000)
        self.assertEqual(set(durations),{41708,41709})

    def test_reject_gap_overlap_empty_or_missing_tail(self):
        for spans in ([(0,2),(3,4)],[(0,2),(1,4)],[(0,0),(0,4)],[(0,3)],[]):
            with self.subTest(spans=spans), self.assertRaises(ValueError):
                tile_durations(spans,4,Fraction(60))
