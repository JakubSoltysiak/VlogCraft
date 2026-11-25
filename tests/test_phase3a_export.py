"""Boundary tests for repair and first-export admission."""
from copy import deepcopy
from fractions import Fraction
from hashlib import sha256
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import native_project_plan as plan
import native_project_render as renderer
import native_project_verification as verification
import server
from benchmarks.phase3a_camera_range import camera_range, retained_reference, verify_original_requests
from test_hdr_color import CONTRACT


class ExportPolicyTests(unittest.TestCase):
    def setUp(self):
        asset={"id":"v","kind":"video","duration":1,"name":"Example"}
        self.clip=server.default_clip(asset)
        self.clip["end"]=.2
        self.state={"tracks":[{"id":"V1","type":"video","clips":[self.clip]}],
                    "output":{"color":deepcopy(CONTRACT),"preset":"ultrafast","crf":15}}
        source=plan.Source(Path("example.mp4"),(3840,2160),"",(3840,2160),"video",asset,
                           ("bt709","bt709","bt709","limited","rec709"),{0:Fraction(0)})
        self.program=plan.Program(3840,2160,Fraction(60),1,[(0,12)],[source],[(-1,[None])]*12)

    def test_first_export_matrix_accepts_only_qualified_profile_and_edits(self):
        self.assertEqual(verification.eligible(self.state,self.program)[1],CONTRACT)
        for change in ({"opacity":.8},{"rotation":90},{"fadeIn":.1},{"keys":{"x":[{}]}},
                       {"transitionIn":{"kind":"dissolve"}},{"inputColor":{"profile":"rec709"}}):
            with self.subTest(change=change):
                state=deepcopy(self.state)
                state["tracks"][0]["clips"][0].update(change)
                with self.assertRaises(plan.Ineligible):
                    verification.eligible(state,self.program)
        self.state["output"]["crf"]=17
        with self.assertRaisesRegex(plan.Ineligible,"Ultrafast CRF 15"):
            verification.eligible(self.state,self.program)

    def test_every_source_selection_uses_the_independent_original_clock(self):
        ticks=list(range(0,24,2))
        clock={0:(Fraction(1,120),Fraction(0),ticks,list(range(12)))}
        with patch.object(verification,"source_ids",return_value=ticks):
            self.assertEqual(verification.verify_source_clocks(self.program,clock,lambda:False),12)
        with patch.object(verification,"source_ids",return_value=[*ticks[:-1],23]):
            with self.assertRaisesRegex(plan.Ineligible,"different presentation timestamp"):
                verification.verify_source_clocks(self.program,clock,lambda:False)

    def test_camera_profile_requires_explicit_opt_in_and_preserves_the_saved_settings(self):
        self.state["output"].update(preset="slow",crf=20,bitrate=60)
        self.assertEqual(verification.eligible(self.state,self.program,camera_range=True)[1],CONTRACT)
        with self.assertRaisesRegex(plan.Ineligible,"Ultrafast CRF 15"):
            verification.eligible(self.state,self.program)
        self.state["output"]["crf"]=19
        with self.assertRaisesRegex(plan.Ineligible,"Slow CRF 20"):
            verification.eligible(self.state,self.program,camera_range=True)

    def test_hevc_sdr_camera_requires_the_probed_main_profile_and_source_geometry(self):
        src=self.program.sources[0]
        src.requests.update({1:Fraction(1,60),2:Fraction(1,30)})
        stream=dict(width=3840,height=2160,codec_name="hevc",profile="Main",pix_fmt="yuv420p",time_base="1/90000",
                    color_primaries="bt709",color_transfer="bt709",color_space="bt709",color_range="tv",
                    field_order="progressive")
        probe={"streams":[stream],"frames":[{"best_effort_timestamp":p} for p in (0,1499,3033,4501)]}
        with tempfile.TemporaryFile() as output,patch.object(plan,"run_capture") as capture:
            capture.return_value=(json.dumps(probe).encode(),b"")
            with self.assertRaises(plan.Ineligible):
                plan.append_video(output,0,src,3,lambda:False,first_time=True)
            plan.append_video(output,0,src,3,lambda:False,first_time=True,camera_range=True)
            output.seek(-12,2)
            self.assertEqual(struct.unpack("<3i",output.read()),(0,1,1))
            for extra in ({"profile":"Main 10"},{"side_data_list":[{"rotation":-90}]},{"color_range":"pc"}):
                with self.subTest(extra=extra):
                    modified={**probe,"streams":[{**stream,**extra}]}
                    capture.return_value=(json.dumps(modified).encode(),b"")
                    with self.assertRaises(plan.Ineligible):
                        plan.append_video(output,0,src,3,lambda:False,first_time=True,camera_range=True)

    def test_camera_excerpt_keeps_source_ticks_and_the_original_document(self):
        asset=self.program.sources[0].asset
        asset["timeBase"]="1/90000"
        self.state["assets"]=[asset]
        self.state["output"]["fps"]=60
        self.clip.update(position=10,start=1,end=3)
        original=deepcopy(self.state)
        result=camera_range(self.state,600,640)
        clip=result["tracks"][0]["clips"][0]
        self.assertEqual(clip["position"],0)
        self.assertEqual(clip["start"],1)
        self.assertEqual(clip["end"],float(Fraction(5,3)))
        self.assertEqual(result["output"],self.state["output"])
        self.assertEqual(self.state,original)
        self.program.spans=[(0,40)]
        requests=self.program.sources[0].requests
        requests.update({frame:1+Fraction(frame,60) for frame in range(40)})
        self.assertEqual(verify_original_requests(self.state,self.program,600,640),40)
        requests[17]+=Fraction(1,90000)
        with self.assertRaisesRegex(ValueError,"Picture 617 changed"):
            verify_original_requests(self.state,self.program,600,640)
        with self.assertRaisesRegex(ValueError,"original render-span boundary"):
            camera_range(self.state,660,700)
        self.clip["fadeIn"]=.1
        with self.assertRaisesRegex(ValueError,"trim behavior"):
            camera_range(self.state,600,640)

    def test_camera_mp4_packet_clock_sorts_reordered_pictures_and_rejects_ambiguity(self):
        src=self.program.sources[0]
        src.asset["codec"]="hevc"
        src.requests={0:Fraction(1,60),1:Fraction(1,30),2:Fraction(1,20)}
        stream=dict(width=3840,height=2160,codec_name="hevc",profile="Main",pix_fmt="yuv420p",time_base="1/90000",
                    color_primaries="bt709",color_transfer="bt709",color_space="bt709",color_range="tv",
                    field_order="progressive")
        probe={"streams":[stream],"format":{"start_time":"0","format_name":"mov,mp4,m4a,3gp,3g2,mj2"},
               "packets":[{"pts":p,"flags":"___"} for p in (0,3033,1499,6000,4511)]}
        with tempfile.TemporaryFile() as output,patch.object(plan,"run_capture") as capture:
            capture.return_value=(json.dumps(probe).encode(),b"")
            clock=plan.append_video(output,0,src,3,lambda:False,first_time=True,camera_range=True)
            self.assertEqual(clock[2:],([0,1499,3033],[1,1,2]))
            self.assertTrue(any("packet=pts,flags" in arg for arg in capture.call_args.args[0]))
            for modify in ({"flags":"__D"},{"pts":None},{"pts":1499},{"pts":-1}):
                with self.subTest(modify=modify):
                    changed={**probe,"packets":[{**probe["packets"][0],**modify},*probe["packets"][1:]]}
                    capture.return_value=(json.dumps(changed).encode(),b"")
                    with self.assertRaises(plan.Ineligible):
                        plan.append_video(output,0,src,3,lambda:False,first_time=True,camera_range=True)
            changed={**probe,"format":{**probe["format"],"start_time":"-.02"}}
            capture.return_value=(json.dumps(changed).encode(),b"")
            with self.assertRaisesRegex(plan.Ineligible,"nonnegative"):
                plan.append_video(output,0,src,3,lambda:False,first_time=True,camera_range=True)

    def test_wider_encoder_pool_preserves_the_saved_quality_and_frame_settings(self):
        original=["-preset","slow","-crf","20","-x265-params",
                  "hdr10=1:repeat-headers=1:pools=2:frame-threads=2:max-cll=1000,200"]
        widened=renderer.parallel_camera_x265(original)
        self.assertEqual(widened[:-1],original[:-1])
        self.assertEqual(widened[-1].replace("pools=8","pools=2"),original[-1])
        self.assertIn("pools=8",widened[-1].split(":"))
        with self.assertRaises(plan.Ineligible):
            renderer.parallel_camera_x265([*original[:-1],original[-1].replace("frame-threads=2","frame-threads=4")])

    def test_retained_reference_requires_the_matching_project_media_and_master(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            original=root/"camera.mp4"
            identity=(1,2,3,4,5)
            prior={"source_project_sha256":"fixture","range":[2,12],"frames":10,"output":{"fps":60},
                   "original_files_match":True,"first_export":{"delivered_backend":"reference"},
                   "fallback":{"seconds":3}}
            current=root/"current.vlogcraft"
            project=root/"range.vlogcraft"
            master=root/"first-export.mp4"
            pin=root/"source-pin.json"
            (root/"qualification.json").write_text(json.dumps(prior),encoding="utf8")
            pin.write_text(json.dumps({"source_signatures":{str(original):list(identity)}}),encoding="utf8")
            current.write_bytes(b"same saved project")
            project.write_bytes(current.read_bytes())
            master.write_bytes(b"verified managed master")
            digest=sha256(master.read_bytes()).hexdigest()
            self.assertEqual(retained_reference(root,current,prior,{original:identity},pin,digest),
                             (master,prior["fallback"]))
            with self.assertRaisesRegex(ValueError,"pinned sources"):
                retained_reference(root,current,prior,{original:(1,2,3,4,6)},pin,digest)
            master.write_bytes(b"different master")
            with self.assertRaisesRegex(ValueError,"recorded master hash"):
                retained_reference(root,current,prior,{original:identity},pin,digest)

            prior.update(passed=True, first_export={"delivered_backend":"d3d11"},
                         independent_comparison={"passed":True}, reference={"seconds":5})
            (root/"qualification.json").write_text(json.dumps(prior),encoding="utf8")
            baseline=root/"reference.mp4"
            baseline.write_bytes(b"verified managed master")
            self.assertEqual(retained_reference(root,current,prior,{original:identity},pin,digest),
                             (baseline,prior["reference"]))

    def test_direct_worker_pipe_delivers_exact_bytes_and_detects_trailing_output(self):
        payload=bytes(range(48))
        self.program.width,self.program.height=2,2
        self.program.spans=[(0,4)]
        self.program.frames=self.program.frames[:4]
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            target=root/"received"
            video_command=["ffmpeg","-/filter_complex",str(root/"hdr_graph_clip.txt"),"-map","[finished]",
                           "-an","-frames:v","4","-c:v","libx265",str(target)]
            spawn=subprocess.Popen
            reader=("import os,sys; data=b''\n"
                    "if os.name=='nt':\n"
                    " import msvcrt; msvcrt.setmode(0,os.O_BINARY)\n"
                    "while len(data)<48:\n"
                    " part=os.read(0,48-len(data))\n"
                    " if not part: sys.exit(2)\n"
                    " data+=part\n"
                    "open(sys.argv[1],'wb').write(data)")

            def subprocess_for_test(command,**kwargs):
                if command[0]=="ffmpeg":
                    self.assertIn("-xerror",command)
                    command=[sys.executable,"-c",reader,str(target)]
                return spawn(command,**kwargs)

            for trailing in (b"",b"x"):
                with self.subTest(trailing=trailing),patch.object(renderer.subprocess,"Popen",side_effect=subprocess_for_test):
                    receipt={"wall_ms":1,"samples":[{}]*4}
                    child=(f"import sys; sys.stdout.buffer.write({payload+trailing!r}); "
                           f"sys.stderr.write({json.dumps(receipt)!r})")
                    with renderer.ProjectVideo(self.program,root,Path(__file__),None,10,lambda:False,
                                               "gpu32-first-export",None,direct_pipe=True) as video:
                        video.command=[sys.executable,"-c",child]
                        video(video_command,root)
                        self.assertEqual(target.read_bytes(),payload)
                        if trailing:
                            with self.assertRaisesRegex(renderer.NativeFailure,"end-of-stream"):
                                video.receipt()
                        else:
                            self.assertEqual(video.receipt()["frames"],4)
                    self.assertIsNotNone(video.producer.poll())

    def test_only_one_bounded_quality_rejection_can_enter_repair(self):
        self.program.spans=[(0,4),(4,6),(6,12)]
        correct={"passed":False,"per_frame_psnr_db":["55"]*12,"decoded_pq_psnr_db":"54",
                 "exact_video_pts":True,"static_hdr_matches":True,"video_declaration_matches":True,
                 "exact_decoded_pcm":True,"hdr10plus_picture_associations":12}
        correct["per_frame_psnr_db"][5]="49.48"
        self.assertEqual(renderer.failed_gop(self.program,correct),1)
        self.assertIsNone(renderer.failed_gop(self.program,{**correct,"exact_decoded_pcm":False}))
        self.assertIsNone(renderer.failed_gop(self.program,{**correct,"decoded_pq_psnr_db":"49.98"}))
        correct["per_frame_psnr_db"][6]="49.7"
        self.assertIsNone(renderer.failed_gop(self.program,correct))

    def test_first_export_requires_explicit_policy_and_never_publishes_rejected_delivery(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            dest=root/"result.mp4"
            with self.assertRaisesRegex(ValueError,"verification"):
                renderer.export_native(self.state,dest,None,root/"worker",None)
            with (patch.object(renderer,"compile_project",return_value=self.program),
                  patch.object(renderer.hdr10plus_master,"preflight",return_value=12),
                  patch.object(renderer.hdr10plus_master,"author",return_value=12),
                  patch.object(renderer.render_engine,"render"),
                  patch.object(renderer,"write_plan"),
                  patch.object(renderer,"write_sources",return_value={}),
                  patch.object(verification,"source_snapshot",return_value={}),
                  patch.object(verification,"verify_delivery",return_value={"passed":False}),
                  patch.object(renderer,"ProjectVideo") as worker):
                worker.return_value.__enter__.return_value.receipt.return_value={}
                def fallback():
                    self.assertFalse(dest.exists())
                    dest.write_bytes(b"managed output")
                evidence=renderer.export_native(self.state,dest,None,root/"worker",None,
                                                first_time=True,fallback=fallback)
                self.assertEqual(evidence["delivered_backend"],"reference")
                self.assertEqual(dest.read_bytes(),b"managed output")
