from pathlib import Path
import subprocess
import tempfile
import unittest

import numpy as np
from PIL import Image

from export_raster_options import prepare_still_command
import hdr_render
from test_hdr_color import project
from test_hdr_editing import asset


class FinalStillRasterTests(unittest.TestCase):
    def test_constant_alpha_and_geometry_hold_exact_quantized_picture(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root/"photo.png"
            y, x = np.indices((37, 51))
            Image.fromarray(np.stack((2*x, 5*y, x+y, (x*y)%255), axis=-1).astype("uint8")).save(path)
            state = project([asset(path)])
            still = state["tracks"][0]["clips"][0]
            still.update(end=.25, opacity=.73, scale=.91, mask="ellipse", rotation=18)
            def raw(command):
                tail = ["-c:v","rawvideo","-threads:v","1","-f","rawvideo","-"]
                return subprocess.run(command[:command.index("-c:v")]+tail, check=True, capture_output=True).stdout
            command = hdr_render.command(state, 0, .25, root/"test.mov", root)
            fast = prepare_still_command(command, state, 0, .25, root)
            self.assertNotEqual(command, fast)
            self.assertEqual(raw(command), raw(fast))
            for change in ({"fadeOut":.125}, {"fadeOut":0,"keys":{"opacity":[{"time":0,"value":.4}]}}):
                still.update(change)
                self.assertIs(prepare_still_command(command, state, 0, .25, root), command)
