"""Regression tests for the saved-project renderer and its publication boundary."""
import copy
from fractions import Fraction
import json
import os
from pathlib import Path
import struct
import tempfile
from threading import Event
import unittest
from unittest.mock import patch

from PIL import Image

import native_project_plan as plan
import native_project_render as native
import render_engine
import server
from hdr10plus_master import author
from test_hdr_color import project
from test_timeline_transitions import settings


class ProjectRenderTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.rate = Fraction(30000,1001)
        self.state = project([])
        self.state["output"]["fps"] = str(self.rate)
        self.duration = float(8/self.rate)
        for index,shade in enumerate((90,160)):
            file = self.folder/f"still-{index}.png"
            Image.new("RGBA",(128,72),(shade,shade,shade,255)).save(file)
            asset = {"id":f"asset-{index}","kind":"image","path":str(file),"name":file.name,"duration":4}
            self.state["assets"].append(asset)
        first,second = [server.default_clip(asset,i*self.duration) for i,asset in enumerate(self.state["assets"])]
        first.update(end=self.duration)
        second.update(end=self.duration,transitionIn=settings(first,4,"dip-white"))
        self.state["tracks"] = [{"id":"bottom","type":"video","clips":[first,second]}]

    def test_fractional_transition_and_layer_order(self):
        title = server.default_title(self.duration)
        title.update(end=self.duration,fadeIn=self.duration,fadeOut=0)
        self.state["tracks"].insert(0,{"id":"top","type":"video","clips":[title]})
        program = plan.compile_project(self.state,self.folder)
        self.assertEqual((program.fps,len(program.frames)),(self.rate,16))
        self.assertEqual(program.spans,[(0,6),(6,8),(8,10),(10,16)])
        self.assertEqual([program.frames[index][0] for index in range(6,10)],[0,1/3,2/3,1])
        self.assertEqual([row[0][10] for row in program.frames[8][1]],[1,4,0])
        self.assertEqual(program.frames[12][1][-1][0][5],.5)
        target = self.folder/"instructions"
        plan.write_plan(target,program)
        data = target.read_bytes()
        self.assertEqual(struct.unpack_from("<4I",data),(128,72,0xc0000003,16))
        self.assertEqual(len(data),16+16*(416+8*40))

    def test_fractional_source_selection_with_vfr_and_origin(self):
        src = plan.Source(self.folder/"video.mp4",(128,72),"",(128,72),"video",None,
                          ("bt709","bt709","bt709","limited","rec709"),
                          {0:Fraction(0),1:Fraction(1,30),2:Fraction(1,15),4:Fraction(1,10)})
        stream = {"width":128,"height":72,"codec_name":"h264","pix_fmt":"yuv420p","time_base":"1/1000",
                  "color_primaries":"bt709","color_transfer":"bt709","color_space":"bt709",
                  "color_range":"tv","field_order":"progressive"}
        fixture = {"streams":[stream],"frames":[{"best_effort_timestamp":tick} for tick in (12,34,89,112,150)],
                   "format":{"start_time":".012"}}
        manifest = self.folder/"manifest"
        with patch.object(plan,"run_capture",return_value=(json.dumps(fixture).encode(),b"")):
            with manifest.open("wb") as output:
                plan.append_video(output,0,src,5,lambda:False)
        self.assertEqual(struct.unpack("<5i",manifest.read_bytes()[-20:]),(0,1,1,-1,3))
        fixture["frames"][2]["best_effort_timestamp"]=34
        with patch.object(plan,"run_capture",return_value=(json.dumps(fixture).encode(),b"")):
            with manifest.open("wb") as output,self.assertRaises(plan.Ineligible):
                plan.append_video(output,0,src,5,lambda:False)
        stream["codec_name"]="vp9"
        with patch.object(plan,"run_capture",return_value=(json.dumps(fixture).encode(),b"")):
            with manifest.open("wb") as output,self.assertRaisesRegex(plan.Ineligible,"codec"):
                plan.append_video(output,0,src,5,lambda:False)
        fixture["frames"][2]={}
        with patch.object(plan,"run_capture",return_value=(json.dumps(fixture).encode(),b"")):
            with manifest.open("wb") as output,self.assertRaises(plan.Ineligible):
                plan.append_video(output,0,src,5,lambda:False)

    def test_jpeg_orientation_precedes_fit(self):
        path = self.folder/"portrait.jpg"
        pixels = Image.new("RGB",(128,72),"gray")
        exif = pixels.getexif()
        exif[274] = 6
        pixels.save(path,exif=exif)
        self.state["assets"][0]["path"] = str(path)
        source = plan.compile_project(self.state,self.folder).sources[0]
        self.assertEqual((source.size,source.fitted,source.orientation),((72,128),(40,72),"transpose=clock"))

    def test_animated_half_pixel_translation_and_mask_instruction(self):
        first=self.state["tracks"][0]["clips"][0]
        first.update(mask="ellipse",maskRadius=.42,feather=.17,opacity=.7)
        first["keys"]={"x":[{"time":0,"mode":"linear","value":0},
                            {"time":float(4/self.rate),"mode":"hold","value":.5/128}]}
        program=plan.compile_project(self.state,self.folder)
        self.assertEqual(program.frames[0][1][0][1][-2],0)
        self.assertAlmostEqual(program.frames[4][1][0][1][-2]*128,.5)
        self.assertEqual(program.frames[5][1][0][0][8:10],(0,1))
        self.assertEqual(program.frames[5][1][0][0][5:8],(.7,.42,.17))

    def test_unsupported_operation_calls_complete_reference_without_worker(self):
        rejected = copy.deepcopy(self.state)
        rejected["tracks"][0]["clips"][0]["contrast"] = 1.1
        reference = self.folder/"reference.mp4"
        reference.touch()
        destination = self.folder/"delivery.mp4"
        def fallback():
            self.assertFalse(destination.exists())
            destination.write_bytes(b"reference")
        with patch.object(native,"ProjectVideo") as worker:
            record = native.export_native(rejected,destination,reference,self.folder/"worker",None,fallback=fallback)
        worker.assert_not_called()
        self.assertEqual(record["delivered_backend"],"reference")
        self.assertEqual(destination.read_bytes(),b"reference")

    def test_early_cancel_and_reference_alias_preserve_files(self):
        reference = self.folder/"reference.mp4"
        reference.write_bytes(b"reference")
        event = Event()
        event.set()
        with self.assertRaisesRegex(RuntimeError,"cancelled"):
            native.export_native(self.state,self.folder/"delivery.mp4",reference,self.folder/"worker",None,
                                 cancelled=event.is_set)
        with self.assertRaisesRegex(ValueError,"comparison master"):
            native.export_native(self.state,reference,reference,self.folder/"worker",None,publish=os.replace)
        existing=self.folder/"existing.mp4"
        existing.write_bytes(b"previous delivery")
        with self.assertRaises(FileExistsError):
            native.export_native(self.state,existing,reference,self.folder/"worker",None)
        self.assertEqual(existing.read_bytes(),b"previous delivery")
        self.assertEqual(reference.read_bytes(),b"reference")
        self.assertFalse((self.folder/"delivery.mp4").exists())

    def test_missing_media_and_worker_failure_cannot_publish(self):
        reference = self.folder/"reference.mp4"
        reference.touch()
        destination = self.folder/"delivery.mp4"
        absent = self.folder/"absent-worker.exe"
        with self.assertRaises(FileNotFoundError):
            native.export_native(self.state,destination,reference,absent,None)
        with patch.object(plan,"run_capture") as capture:
            Path(self.state["assets"][0]["path"]).unlink()
            with self.assertRaises(FileNotFoundError):
                native.export_native(self.state,destination,reference,absent,None)
            capture.assert_not_called()
        self.assertFalse(destination.exists())

    def test_allocation_encoder_and_author_failures_fall_back_before_publication(self):
        reference = self.folder/"reference.mp4"
        reference.touch()
        destination = self.folder/"delivery.mp4"
        for phase in ("allocation","decoder","gpu","encoder","author"):
            with self.subTest(phase=phase),patch.object(native,"ProjectVideo") as video, \
                 patch.object(native.render_engine,"render") as render, \
                 patch.object(native.hdr10plus_master,"author") as authoring, \
                 patch.object(native,"write_sources") as prepare:
                prepare.side_effect=MemoryError if phase=="allocation" else None
                if phase=="decoder":
                    prepare.side_effect=native.subprocess.CalledProcessError(1,["ffprobe"])
                video.side_effect=OSError if phase=="gpu" else None
                render.side_effect=RuntimeError if phase=="encoder" else None
                authoring.side_effect=ValueError if phase=="author" else None
                video.return_value.__enter__.return_value.receipt.return_value={}
                def fallback():
                    self.assertFalse(destination.exists())
                    self.assertFalse(list(self.folder.glob("native-project-*")))
                result=native.export_native(self.state,destination,reference,self.folder/"worker",None,
                                            fallback=fallback)
                self.assertEqual(result["delivered_backend"],"reference")
                self.assertIn("native_failure",result)

    @unittest.skipUnless(os.environ.get("VLOGCRAFT_PROJECT_TEST_WORKER"),"Requires locally compiled D3D11 worker")
    def test_warp_fractional_export_and_injected_removal(self):
        runtime = Path(os.environ["VLOGCRAFT_PROJECT_TEST_RUNTIME"])
        worker = Path(os.environ["VLOGCRAFT_PROJECT_TEST_WORKER"])
        static,reference = self.folder/"static.mp4",self.folder/"reference.mp4"
        render_engine.render(self.state,static,self.folder/"reference-render")
        author(static,reference,self.folder,self.rate,16,render_engine._run,lambda *_:None,lambda:False)
        result = native.export_native(self.state,self.folder/"native.mp4",reference,worker,runtime,mode="warp32")
        self.assertTrue(result["comparison"]["exact_video_pts"])
        self.assertTrue(result["comparison"]["exact_decoded_pcm"])
        self.assertEqual(result["comparison"]["hdr10plus_picture_associations"],16)
        with patch.object(native,"compare_project",return_value={"passed":True}), \
             patch.object(native.render_engine,"render"),patch.object(native.hdr10plus_master,"author",return_value=16), \
             patch.object(native,"ProjectVideo") as pipe:
            pipe.return_value.__enter__.return_value.receipt.return_value={}
            with patch.object(native.os,"link",side_effect=FileExistsError) as fallback:
                with self.assertRaises(FileExistsError):
                    native.export_native(self.state,self.folder/"collision.mp4",reference,worker,runtime,
                                         mode="warp32",fallback=fallback,publish=fallback)
                fallback.assert_called_once()
        destination = self.folder/"failure.mp4"
        evidence = {}
        def fallback():
            self.assertFalse(destination.exists())
            work = self.folder/"managed-retry"
            work.mkdir()
            static = work/"static.mp4"
            render_engine.render(self.state,static,work/"render")
            author(static,destination,work,self.rate,16,render_engine._run,lambda *_:None,lambda:False)
        result = native.export_native(self.state,destination,reference,worker,runtime,mode="warp32",
                                      fault=2,fallback=fallback,record=evidence)
        self.assertEqual(result["delivered_backend"],"reference")
        program = plan.compile_project(self.state,self.folder)
        self.assertTrue(native.compare_project(reference,destination,program,self.folder)["passed"])
        self.assertFalse(list(self.folder.glob("native-project-*")),evidence)
        changed=copy.deepcopy(self.state)
        changed["tracks"][0]["clips"][0]["hdrExposure"]=1.
        rejected=self.folder/"mismatched.mp4"
        evidence={}
        with self.assertRaisesRegex(native.NativeFailure,"reference acceptance contract"):
            native.export_native(changed,rejected,reference,worker,runtime,mode="warp32",record=evidence)
        self.assertFalse(rejected.exists())
        self.assertFalse(evidence["comparison"]["passed"])
        self.assertTrue(evidence["comparison"]["exact_video_pts"])
        self.assertTrue(evidence["comparison"]["exact_decoded_pcm"])
