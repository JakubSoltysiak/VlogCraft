import struct
import tempfile
import unittest
from pathlib import Path

from benchmarks.render_phase2 import Scenario, clips_for, write_plan


class ResidentVideoPlanTests(unittest.TestCase):
    def test_temporal_slots_dissolve_and_frame_geometry(self):
        scenario = Scenario('test', 128, 72, layers=3, motion=True, dissolve=True)
        count = 8
        with tempfile.TemporaryDirectory() as folder:
            plan = Path(folder) / 'plan.bin'
            write_plan(plan, scenario, clips_for(scenario, count), count, precise_edges=True,
                       source_slots=((0, 1, 2), (3, 4, 5), (6,)), dissolve_window=(2, 4))
            data = plan.read_bytes()

        self.assertEqual(struct.unpack_from('<4I', data), (128, 72, 0x80000007, count))
        self.assertEqual(len(data), 16 + 160 * count + 120 * count)
        frames = []
        for index in range(count):
            start = 16 + 160 * index
            width, height, layers, dissolve = struct.unpack_from('<3If', data, start)
            self.assertEqual((width, height, layers), (128, 72, 3))
            slots = [struct.unpack_from('<I', data, start + 16 + 48 * n + 32)[0]
                     for n in range(layers)]
            self.assertEqual(slots, [index % 3, 3 + index % 3, 6])
            frames.append(dissolve)
        self.assertEqual(frames, [0, 0, 0, .5, 1, 1, 1, 1])


if __name__ == '__main__':
    unittest.main()
