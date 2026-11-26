"""Verify the exact opaque raster with nonuniform 8/10-bit camera planes."""
from pathlib import Path
import subprocess
import tempfile
import unittest

import numpy as np

import hdr_render
import native_project_plan as plan
from native_project_render import camera_raster_input
from test_hdr_color import project


class CameraRasterTests(unittest.TestCase):
    def test_selected_camera_planes_match_reference_geometry_and_dither(self):
        rng=np.random.default_rng(1168)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for pq in (False,True):
                with self.subTest(pq=pq):
                    # The clockwise contain fit is 45 pixels wide. Its two
                    # black margins are unequal, as in the actual UHD edit.
                    w,h=128,76
                    fmt="yuv420p10le" if pq else "yuv420p"
                    dtype="<u2" if pq else "u1"
                    scale=4 if pq else 1
                    y,u,v=[rng.integers(16*scale,235*scale,size=n).astype(dtype)
                           for n in (w*h,w*h//4,w*h//4)]
                    plane=root/"source.bin"
                    plane.write_bytes(y.tobytes()+u.tobytes()+v.tobytes())
                    coded=np.concatenate([y,np.column_stack([u,v]).ravel()])
                    if pq:
                        coded<<=6
                    props=("bt2020","smpte2084","bt2020nc") if pq else ("bt709","bt709","bt709")
                    asset=dict(id="cam",kind="video",name="camera",path=str(plane),duration=.5,width=w,height=h,
                               sampleAspectRatio="1:1",pixelFormat=fmt,rotation=-90 if pq else 0,
                               colorPrimaries=props[0],colorTransfer=props[1],colorSpace=props[2],colorRange="tv")
                    state=project([asset],width=w,height=h)
                    state["tracks"][0]["clips"][0]["end"]=1/24
                    state["tracks"][0]["clips"][0]["inputColor"]={"profile":"pq2020" if pq else "rec709"}
                    program=plan.compile_project(state,root)
                    reference=hdr_render.command(state,0,1/24,root/"reference.mov",root)
                    start=reference.index("-noautorotate")
                    stop=reference.index("-i",start)+2
                    reference[start:stop]=["-f","rawvideo","-pixel_format",fmt,"-video_size",f"{w}x{h}",
                                           "-framerate","24","-chroma_sample_location","left","-i",str(plane)]
                    reference=reference[:reference.index("-c:v")]
                    cmd,frame_bytes=camera_raster_input(program,0,1)
                    self.assertEqual(len(coded.tobytes()),frame_bytes)
                    tail=["-an","-frames:v","1","-c:v","rawvideo","-threads:v","1","-f","rawvideo","-"]
                    expected=subprocess.run(reference+tail,capture_output=True,check=True).stdout
                    actual=subprocess.run(cmd+tail,input=coded.tobytes(),capture_output=True,check=True).stdout
                    self.assertEqual(len(expected),w*h*3)
                    np.testing.assert_array_equal(np.frombuffer(actual,"<u2"),np.frombuffer(expected,"<u2"))
                    fast, _ = camera_raster_input(program, 0, 1, fast=True)
                    result = subprocess.run(fast+tail, input=coded.tobytes(), capture_output=True, check=True)
                    self.assertEqual(result.stdout, expected)
