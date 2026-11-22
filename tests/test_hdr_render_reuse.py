from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

import hdr_layers
import render_engine
from test_hdr_color import project, source
from test_hdr_editing import asset
from test_hdr10plus_export import command


class HoldStillTests(unittest.TestCase):
    def test_prepared_transparent_still_matches_processing_every_frame(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            photograph = root/'alpha.png'
            rows, columns = np.indices((51, 72))
            pixels = np.stack((3*columns, 5*rows, columns+rows, 3*columns), axis=-1)
            Image.fromarray(pixels.astype(np.uint8)).save(photograph)
            state = project([asset(photograph), source(root, 'pq', 800)])
            still = state['tracks'][0]['clips'][0]
            still.update(position=.125, end=.25, scale=.91, rotation=19, x=.17, opacity=.74,
                         mask='ellipse', maskRadius=.37, feather=.19, contrast=1.25, saturation=.8)

            def decoded(path):
                return command('ffmpeg','-v','error','-i',str(path),'-map','0:v','-map','0:a',
                               '-c:v','rawvideo','-threads:v','1','-f','framemd5','-')

            for fade in (0, .17):
                with self.subTest(fade=fade):
                    still['fadeIn']=fade
                    if fade:
                        still['keys']={'opacity':[{'time':0,'value':1,'mode':'linear'},
                                                  {'time':.25,'value':.7,'mode':'linear'}]}
                    reused = root/f'reused-{fade}.mp4'
                    every_frame = root/f'every-frame-{fade}.mp4'
                    with patch('hdr_render.os.cpu_count', return_value=4):
                        render_engine.render(state, reused, root/reused.stem)
                    with (patch.object(hdr_layers, 'still_needs_frame_clock', return_value=True),
                          patch('hdr_render.os.cpu_count', return_value=1)):
                        render_engine.render(state, every_frame, root/every_frame.stem)
                    self.assertEqual(decoded(reused), decoded(every_frame))
