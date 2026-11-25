import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks" / "windows"))
from calibrate_decoder_buffer import compare


class BufferCalibration(unittest.TestCase):
    observed = "42 7 1250 1200 256 1300 1400\n42 7 1250 1204 256 1308 1400"

    def events(self, pid=42):
        prefix = "Microsoft-Windows-Direct3D11/ID3D11VideoContext_GetDecoderBuffer/win:"
        rows = []
        for i in range(2):
            common = f", {2*i+1}, probe ({pid}), 7, 0, 0, 0, 0, 0, "
            rows.extend([prefix + "Start" + common + "Type : 0, pDecoder : 0x1250",
                         prefix + "Stop" + common + "m_Ret : 0, pBufferSize : 256, ppBuffer : 0x1400"])
        return "\n".join(rows)

    def test_returned_value_is_distinct_from_caller_storage(self):
        result = compare(self.observed, self.events())
        self.assertEqual(len(result), 2)
        for row in result:
            self.assertTrue(row["ppBuffer_matches_returned_value"])
            self.assertFalse(row["ppBuffer_matches_output_slot"])
            self.assertTrue(row["pBufferSize_matches_returned_value"])
            self.assertFalse(row["pBufferSize_matches_output_slot"])

    def test_wrong_process_and_duplicate_pairs_are_rejected(self):
        for events in [self.events(41), self.events() + "\n" + self.events()]:
            with self.assertRaises(ValueError):
                compare(self.observed, events)
