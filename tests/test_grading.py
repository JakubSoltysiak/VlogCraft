from pathlib import Path
import json
import tempfile
import unittest

import numpy as np
from PIL import Image

import grading
import render_engine
import server
import timing


class GradeTests(unittest.TestCase):
    def setUp(self):
        rows = [f'{b} {g} {r}' for b in (0, 1) for g in (0, 1) for r in (0, 1)]
        self.cube = 'LUT_3D_SIZE 2\n' + '\n'.join(rows)

    def test_grids_curves_and_wheels(self):
        ident, entry = grading.import_cube(self.cube, 'swap.cube')
        lib = {ident: entry}
        transform = grading.table({'master': [0, .1, .8, .9, 1]}, ident, lib)
        self.assertEqual(len(transform), 33)
        np.testing.assert_allclose(transform[0, 0, 16], [0, 0, .8], atol=.001)
        balanced = grading.table({'midtones': [1, 0]}, None, {})
        self.assertGreater(balanced[16, 16, 16, 0], balanced[16, 16, 16, 1] + .2)
        for invalid in (self.cube[:-4], self.cube.replace('0 0 0','nan 0 0'), 'DOMAIN_MIN -1 -1 -1\n' + self.cube):
            with self.assertRaises(ValueError):
                grading.import_cube(invalid, 'invalid.cube')

    def test_embedded_lut_project_reopen_and_ffmpeg_reference(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'red.png'
            Image.new('RGB', (96, 64), (180, 40, 15)).save(source)
            a = dict(id='a'*32, kind='image', name=source.name, path=str(source), size=source.stat().st_size, **server.probe(source))
            s = server.default_state()
            s['output'].update(width=96, height=64, fps=24)
            s['assets'] = [a]
            ident, entry = grading.import_cube(self.cube, 'swap.cube')
            s['luts'] = {ident: entry}
            clip = server.default_clip(a)
            clip.update(lutId=ident, end=.25)
            s['tracks'][1]['clips'] = [clip]
            stored = json.loads(json.dumps(timing.encode(s)))
            server.validate_document(stored)
            reopened = timing.decode(stored)
            frame = root / 'reference.png'
            render_engine._run(render_engine.segment_command(reopened, 0, 1/24, frame, root, 'frame'), str(root))
            pixel = np.array(Image.open(frame).convert('RGB'))[32, 48].astype(int)
            np.testing.assert_allclose(pixel, [15, 40, 180], atol=8)
