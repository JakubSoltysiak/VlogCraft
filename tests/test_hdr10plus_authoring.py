import unittest

import numpy as np

from hdr10plus_authoring import PAYLOAD_BYTES, payload, prefix_sei, statistics
from hdr10plus_bitstream import conformance_issues, parse_payload, sei_payloads


def linear_units(code):
    # Scalar ST 2084 reference, independent of the production lookup table.
    power = (int(code)/65535)**(1/78.84375)
    return (max(power-0.8359375,0)/(18.8515625-18.6875*power))**(1/0.1593017578125)


class HDR10PlusAuthoringTests(unittest.TestCase):
    def test_black_mid_gray_and_distinct_component_maxima(self):
        for codes in ((0, 0, 0), (32768, 32768, 32768), (36000, 44000, 50500)):
            g, b, r = codes
            frame = np.broadcast_to(np.array(codes, dtype=np.uint16)[:,None,None], (3, 20, 32))
            encoded = payload(frame)
            self.assertEqual(len(encoded), PAYLOAD_BYTES)
            self.assertEqual(list(sei_payloads(prefix_sei(encoded, 1)[2:])), [encoded])
            block = parse_payload(encoded)
            self.assertEqual(conformance_issues(block), [])
            self.assertEqual(block['peak'], 0)
            self.assertIsNone(block['knee'])
            self.assertEqual(block['maxrgb'], tuple(round(linear_units(x)*100000) for x in (r,g,b)))
            self.assertEqual(block['average'], round(linear_units(max(codes))*100000))
            self.assertEqual(list(dict(block['distribution']).items())[1:3], [(5,0),(10,255)])

    def test_nearest_rank_duplicates_and_small_moving_highlight(self):
        dark, middle, bright = 18000, 38000, 65000
        frame = np.full((3,100,100), dark, dtype=np.uint16)
        frame[1,50:,:] = middle
        frame[0,99,-4:] = bright
        (red,green,blue), average, distribution = statistics(frame)
        expect = lambda x:round(linear_units(x)*100000)
        self.assertEqual((red,green,blue), (expect(dark),expect(bright),expect(middle)))
        self.assertEqual(average, round((5000*linear_units(dark)+4996*linear_units(middle)+
                                        4*linear_units(bright))*10))
        self.assertEqual(dict(distribution)[50], expect(dark))
        self.assertEqual(dict(distribution)[95], expect(middle))
        self.assertEqual(dict(distribution)[99], expect(bright))
        next_frame = frame.copy()
        next_frame[0,99,-4:] = dark
        next_frame[2,0,:4] = middle
        self.assertEqual(dict(statistics(next_frame)[2])[99], expect(middle))
