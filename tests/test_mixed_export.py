"""Check original HDR picture dispatch without a workstation GPU."""
from fractions import Fraction
from hashlib import sha256
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PIL import Image

import hdr10plus_master
import hdr_render
import mixed_continuous
import mixed_export
import native_project_plan
from native_project_render import camera_raster_input, export_native
from native_project_verification import verify_audio, verify_source_clocks
import render_engine
import server
from test_hdr_color import project


class MixedExportTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)

    def asset(self, kind, filename, **properties):
        return {"id":filename, "kind":kind, "path":str(self.root/filename),
                "name":filename, "duration":1, **properties}

    def state(self, width, height):
        camera = self.asset("video", "camera.mp4", width=width, height=height, codec="h264",
                            colorPrimaries="bt709", colorTransfer="bt709", colorSpace="bt709",
                            colorRange="tv", pixelFormat="yuv420p", sampleAspectRatio="unknown")
        photo = self.asset("image", "photo.jpg")
        pixels = Image.new("RGB", (24,40), "#345678")
        pixels.paste("white", (8,4,14,22))
        exif = pixels.getexif()
        exif[274] = 6
        pixels.save(photo["path"], exif=exif)
        audio = self.asset("audio", "tone.wav")
        state = project([], width=width, height=height)
        state["output"].update(fps=60, preset="slow", crf=20, bitrate=60)
        state["assets"] = [camera, photo, audio]
        first = server.default_clip(camera)
        first.update(end=4/60, inputColor={"profile":"source", "range":"auto", "pixelAspect":"square"})
        still = server.default_clip(photo,4/60)
        still.update(end=5/60, opacity=.6, scale=1.2, x=.1)
        last = server.default_clip(camera,9/60)
        last.update(start=.1, end=.1+4/60, inputColor=first["inputColor"])
        sound = server.default_clip(audio,2/60)
        sound.update(end=9/60, volume=.33)
        state["tracks"] = [
            {"id":"video", "type":"video", "clips":[first,still,last]},
            {"id":"audio", "type":"audio", "clips":[sound]},
        ]
        return state

    def test_sources_and_ranges_compact_only_native_camera_instructions(self):
        state = self.state(3840,2160)
        Path(state["assets"][0]["path"]).touch()
        plan = mixed_export.compile_mixed(state,self.root)
        self.assertEqual(plan.spans, ((0,2),(2,4),(4,9),(9,11),(11,13)))
        self.assertEqual(plan.routes, ("camera","camera","managed","camera","camera"))
        self.assertEqual(plan.camera.spans, [(0,2),(2,4),(4,6),(6,8)])
        self.assertEqual(set(plan.camera.sources[0].requests), {0,1,2,3})
        self.assertEqual(plan.camera.sources[0].requests[2], Fraction(16667,500000))
        self.assertEqual(plan.camera.sources[1].requests[6], Fraction(66667,500000))
        first = state["tracks"][0]["clips"][0]
        first["opacity"] = .9
        self.assertEqual(mixed_export.compile_mixed(state,self.root).routes,
                         ("managed","managed","managed","camera","camera"))

    def test_wrong_renderer_range_cannot_advance_either_provider(self):
        state = self.state(3840,2160)
        Path(state["assets"][0]["path"]).touch()
        plan = mixed_export.compile_mixed(state,self.root)
        native = Mock()
        dispatch = mixed_export.MixedVideo(state,plan,native)
        with self.assertRaisesRegex(native_project_plan.Ineligible,"changed an original mixed span"):
            dispatch([],str(self.root),1,3)
        native.assert_not_called()
        native.run.assert_not_called()
        with self.assertRaisesRegex(native_project_plan.Ineligible,"complete every"):
            dispatch.receipt()

    def test_source_alias_is_refused_before_fallback(self):
        state = self.state(3840,2160)
        original = Path(state["assets"][0]["path"])
        original.write_bytes(b"original")
        alias = self.root/"alias.mp4"
        os.link(original,alias)
        fallback = Mock()
        with self.assertRaisesRegex(ValueError,"different from source media"):
            export_native(state,alias,None,self.root/"worker",None,first_time=True,camera_range=True,
                          qualification=True,camera_raster=True,mixed=True,diagnostics=self.root/"logs",
                          fallback=fallback,publish=os.replace)
        fallback.assert_not_called()
        self.assertEqual(original.read_bytes(),b"original")

    def recorded_fixture(self):
        state = self.state(128,72)
        camera, _, audio = state["assets"]
        camera_tags = ["-color_primaries","bt709","-color_trc","bt709","-colorspace","bt709","-color_range","tv"]
        subprocess.run(["ffmpeg","-v","error","-f","lavfi","-i","color=teal:s=128x72:r=60:d=1",
                        "-f","lavfi","-i","sine=frequency=240:sample_rate=48000:duration=1",
                        "-c:v","libx264","-x264-params","colorprim=bt709:transfer=bt709:colormatrix=bt709:fullrange=off",
                        "-pix_fmt","yuv420p","-chroma_sample_location","left",
                        *camera_tags,"-c:a","aac",camera["path"]], check=True)
        camera["hasAudio"] = True
        subprocess.run(["ffmpeg","-v","error","-f","lavfi","-i",
                        "sine=frequency=600:sample_rate=48000:duration=1",audio["path"]], check=True)
        spans = tuple(render_engine.frame_spans(state,Fraction(60)))
        routes = ("camera","camera","managed","camera","camera")
        indexed = native_project_plan.compile_project(
            state,self.root,camera_raster=True,camera_spans=[span for span,route in zip(spans,routes) if route=="camera"])
        plan = mixed_export.MixedPlan(128,72,Fraction(60),spans,routes,indexed)
        raw = subprocess.run(["ffmpeg","-v","error","-i",camera["path"],"-frames:v","1","-pix_fmt","nv12",
                              "-f","rawvideo","-"], check=True, capture_output=True).stdout
        return state,plan,raw

    def test_shared_encoder_boundaries_preserve_camera_still_and_audio(self):
        state,plan,raw = self.recorded_fixture()
        indexed = plan.camera
        camera_spans = iter(indexed.spans)

        class CameraPipe:
            @staticmethod
            def cancelled():
                return False

            def check(self):
                pass

            def run(self, command, cwd):
                render_engine._run(command,cwd)

            def __call__(self, command, cwd):
                first,last = next(camera_spans)
                raster, frame_bytes = camera_raster_input(indexed,first,last)
                self_test.assertEqual(len(raw),frame_bytes)
                raster += command[command.index("-an",command.index("-/filter_complex")):]
                subprocess.run(raster,cwd=cwd,input=raw*(last-first),check=True,capture_output=True)

        self_test = self
        provider = CameraPipe()
        dispatch = mixed_export.MixedVideo(state,plan,provider)
        candidate, reference = self.root/"candidate.mp4", self.root/"reference.mp4"
        render_engine.render(state,candidate,self.root/"mixed",popen=provider.run,picture_runner=dispatch)
        render_engine.render(state,reference,self.root/"managed")
        self.assertEqual((dispatch.receipt()["camera_pictures"],dispatch.receipt()["managed_pictures"]), (8,5))

        def decoded(path):
            return subprocess.run(["ffmpeg","-v","error","-i",str(path),"-map","0:v:0","-map","0:a:0",
                                   "-f","framemd5","-"], check=True,capture_output=True).stdout

        self.assertEqual(decoded(candidate),decoded(reference))
        self.assertTrue(verify_audio(state,candidate,plan,self.root,provider.run,provider.cancelled))
        clocks = native_project_plan.write_sources(self.root/"fixture-sources.bin",indexed,
                                                  camera_range=True,first_time=True,
                                                  keyframe_seek=True,camera_raster=True)
        self.assertEqual(verify_source_clocks(indexed,clocks,provider.cancelled,camera_raster=True),8)
        samples = mixed_export.compare_mixed_samples(state,candidate,plan,self.root,provider.cancelled,clocks)
        self.assertEqual([score["frame"] for score in samples], [0,1,2,3,4,6,8,9,10,11,12])

    def test_continuous_export_matches_a_separately_rendered_full_encoder_context(self):
        state,plan,raw = self.recorded_fixture()
        reference_work = self.root/"continuous-reference"
        reference_work.mkdir()
        reference = reference_work/"reference.mp4"
        source_planes = self.root/"decoder-fixture.bin"
        source_planes.write_bytes(raw*len(plan.camera.frames))
        oracle = bytearray()
        for first,last in plan.spans:
            managed = hdr_render.command(state,float(first/plan.fps),float(last/plan.fps),
                                         reference_work/f"source-{first}.mov",reference_work)
            command = managed[:managed.index("-c:v")]+["-c:v","rawvideo","-threads:v","1","-f","rawvideo","-"]
            oracle.extend(subprocess.run(command,check=True,capture_output=True).stdout)
        reference_video = reference_work/"continuous.mov"
        encoder = mixed_continuous.encoder_command(managed,plan,reference_video,2)
        subprocess.run(encoder,input=oracle,check=True,capture_output=True)
        static = reference_work/"static.mp4"
        mixed_continuous.mux_audio(state,plan,reference_video,static,reference_work,render_engine._run)
        hdr10plus_master.author(static,reference,reference_work,plan.fps,len(plan.frames),
                               render_engine._run,lambda *_:None,lambda:False)

        worker = SimpleNamespace(environment=dict(os.environ),command=[
            sys.executable,"-c",
            "import shutil, sys; shutil.copyfileobj(open(sys.argv[1], 'rb'), sys.stdout.buffer)",
            str(source_planes),
        ])
        output = self.root/"mixed-continuous.mp4"
        with (patch.object(mixed_continuous,"compile_mixed",return_value=plan),
              patch.object(mixed_continuous,"ProjectVideo",return_value=worker),
              patch.object(mixed_continuous,"collect",return_value={"frames":len(plan.camera.frames)})):
            receipt = mixed_continuous.export_continuous(
                state,output,self.root/"candidate-work",None,None,reference=reference,
                reference_sha256=sha256(reference.read_bytes()).hexdigest(),
                prepared_main10_sha256=sha256(oracle).hexdigest())
        self.assertTrue(output.is_file())
        self.assertTrue(receipt["passed"])
        self.assertTrue(receipt["spans"][2]["held"])
        self.assertEqual(receipt["equal_coded_pictures"],len(plan.frames))
        self.assertEqual(receipt["independent"]["exact_decoded_pictures"],len(plan.frames))
        self.assertTrue(receipt["independent"]["exact_decoded_pcm"])
        self.assertEqual(receipt["independent"]["hdr10plus_records_matching_reference"],len(plan.frames))
