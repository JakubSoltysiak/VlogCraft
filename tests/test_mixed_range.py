"""Frame-exact v4 excerpt gates without requiring private media."""
from copy import deepcopy
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from benchmarks import phase3a_mixed_range as excerpts
import render_engine
import server
from test_hdr_color import project
import timing


class MixedRangeTests(unittest.TestCase):
    def saved_project(self, folder):
        def asset(name,kind,base):
            return dict(id=name.split(".")[0],name=name,path=str(folder/name),kind=kind,duration=2,
                        timeBase=base,hasAudio=kind!="image")

        camera = asset("camera.mp4","video","1/90000")
        still = asset("still.jpg","image","1/25")
        audio = asset("sound.wav","audio","1/44100")
        state = project([])
        state["assets"] = [camera,still,audio]
        state["output"]["fps"] = 60
        left = server.default_clip(camera)
        left.update(end=.2)
        photo = server.default_clip(still,.2)
        photo.update(end=.2)
        right = server.default_clip(camera,.4)
        right.update(start=.3,end=.5)
        sound = server.default_clip(audio,.2)
        sound.update(start=.5,end=.5+11/60)
        state["tracks"] = [
            {"id":"video","type":"video","clips":[left,photo,right]},
            {"id":"audio","type":"audio","clips":[sound]},
        ]
        return timing.encode(state)

    def test_v4_copy_preserves_still_hold_and_one_frame_silent_boundary(self):
        with TemporaryDirectory() as temp:
            original = self.saved_project(Path(temp))
            snapshot = deepcopy(original)
            excerpt = excerpts.clip_range(original,6,30)
            self.assertEqual(excerpt["assets"],original["assets"])
            self.assertEqual(excerpt["output"],original["output"])
            self.assertEqual(original,snapshot)
            clips = excerpt["tracks"][0]["clips"]
            self.assertEqual([(c["timing"]["positionFrame"],c["timing"]["inTick"],c["timing"]["outTick"])
                              for c in clips],[(0,9000,18000),(6,0,5),(18,27000,36000)])
            state = server.validate_document(excerpt)
            self.assertEqual(render_engine.frame_spans(state,Fraction(60)),
                             [(0,6),(6,17),(17,18),(18,24)])

    def test_fade_and_fractional_source_ticks_are_refused(self):
        with TemporaryDirectory() as temp:
            original = self.saved_project(Path(temp))
            with self.assertRaisesRegex(ValueError,"source tick grid"):
                excerpts.clip_range(original,6,22)
            original["tracks"][0]["clips"][0]["fadeOut"] = .1
            with self.assertRaisesRegex(ValueError,"time-dependent"):
                excerpts.clip_range(original,6,30)

    def test_cut_into_a_static_still_shortens_the_hold_without_seeking_the_image(self):
        with TemporaryDirectory() as temp:
            original = self.saved_project(Path(temp))
            _,photo,right = original["tracks"][0]["clips"]
            photo.update(end=.4)
            photo["timing"]["outTick"] = 10
            right.update(position=.6)
            right["timing"]["positionFrame"] = 36
            snapshot = deepcopy(original)
            for first,last in ((24,42),(13,25)):
                with self.subTest(first=first,last=last):
                    excerpt = excerpts.clip_range(original,first,last)
                    hold = excerpt["tracks"][0]["clips"][0]
                    self.assertEqual(hold["assetId"],photo["assetId"])
                    self.assertEqual(hold["timing"],dict(photo["timing"],positionFrame=0,inTick=0,outTick=5))
                    self.assertEqual((hold["start"],hold["end"]),(0,.2))
                    self.assertEqual(excerpts.validate_v4(excerpt)["tracks"][0]["clips"][0]["end"],.2)
            self.assertEqual(original,snapshot)
            with self.assertRaisesRegex(ValueError,"source tick grid"):
                excerpts.clip_range(original,25,42)

    def test_camera_floor_rejects_a_rebase_that_changes_the_source_picture(self):
        clock = {"streams":[{"time_base":"1/1000"}],"format":{"start_time":"0"}}
        index = clock,[0,16,20,50],[]
        with (patch.object(excerpts.native_source_seek,"probe",return_value=index),
              patch.object(excerpts,"source_ids") as decode):
            with self.assertRaisesRegex(ValueError,"camera packet floor"):
                excerpts.camera_floors(Path("input.mp4"),[Fraction(159,10000)],[Fraction(16,1000)],
                                       Fraction(60),lambda:False)
            decode.assert_not_called()

    def test_audio_offsets_reject_resampling_phase_change(self):
        clock = 44100,Fraction(0),2645265
        result = excerpts.audio_offset(clock,Fraction(45),Fraction(45),Fraction(1,60))
        self.assertEqual(result["source_sample_first"],1984500)
        self.assertEqual(result["source_sample_last"],1985235)
        with self.assertRaisesRegex(ValueError,"resampling phase"):
            excerpts.audio_offset(clock,Fraction(45),Fraction(4500001,100000),
                                  Fraction(1,60))
