"""Boundary tests for repair and first-export admission."""
from copy import deepcopy
from fractions import Fraction
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import native_project_plan as plan
import native_project_render as renderer
import native_project_verification as verification
import server
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
