"""Exact compression-quality arithmetic and independent Main10 decode."""
from fractions import Fraction
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest

import numpy as np

from benchmarks import phase3a_mixed_reference as quality
from native_project_render import PQ_TAGS


class MixedReferenceQualityTests(unittest.TestCase):
    def test_yuv_error_uses_all_samples_and_pins_the_source_bytes(self):
        source = bytes(12)
        decoded = np.arange(1,7,dtype="<u2").tobytes()
        digest = sha256(source).hexdigest()
        errors, hashes = quality.main10_errors(BytesIO(source),BytesIO(decoded),2,2,1,digest)
        self.assertEqual(errors,[91])
        self.assertEqual(hashes,[sha256(decoded).digest()])
        with self.assertRaisesRegex(ValueError,"input changed"):
            quality.main10_errors(BytesIO(source),BytesIO(decoded),2,2,1,"unexpected")
        with self.assertRaisesRegex(ValueError,"extra bytes"):
            quality.main10_errors(BytesIO(source),BytesIO(decoded+b"x"),2,2,1,digest)
        with self.assertRaisesRegex(ValueError,"complete picture 0"):
            quality.main10_errors(BytesIO(source),BytesIO(decoded[:-1]),2,2,1,digest)

    def test_floor_and_overall_score_use_unrounded_error(self):
        peak_sum = 32*32*3//2*1023**2
        passing = peak_sum//100_000
        errors = [0,passing,passing+1]
        audit = quality.quality_report(errors,32,32,[(0,2),(2,3)])
        self.assertEqual(audit["frames_below_floor"],[2])
        self.assertEqual(audit["pictures_below_floor"],1)
        self.assertEqual(audit["exact_raw_pictures"],1)
        self.assertEqual(audit["per_frame_psnr_db"][0],"inf")
        self.assertGreater(audit["per_frame_psnr_db"][1],50)
        self.assertLess(audit["minimum_psnr_db"],50)
        self.assertGreater(audit["overall_psnr_db"],51)
        self.assertFalse(audit["passed"])
        self.assertEqual(audit["seams"][0]["boundary_frame"],2)
        self.assertEqual(audit["seams"][0]["first_psnr_db"],audit["minimum_psnr_db"])

    def test_independent_decodes_report_compression_and_equality_separately(self):
        with TemporaryDirectory() as temp:
            work = Path(temp)
            width = height = 64
            area = width*height
            original = np.concatenate((np.full(area,400,dtype="<u2"),np.full(area//2,512,dtype="<u2")))
            altered = original.copy()
            altered[:area] += 42
            raw = work/"canonical.yuv"
            raw.write_bytes(original.tobytes()*3)
            digest = sha256(raw.read_bytes()).hexdigest()

            def encode(path, data):
                command = ["ffmpeg","-v","error","-nostdin","-xerror","-f","rawvideo","-pixel_format",
                           "yuv420p10le","-video_size",f"{width}x{height}","-framerate","60","-i","pipe:0",
                           "-vf","setsar=1,"+PQ_TAGS,"-c:v","libx265","-preset","ultrafast","-pix_fmt","yuv420p10le",
                           "-x265-params","lossless=1:pools=1:frame-threads=1","-tag:v","hvc1",
                           "-video_track_timescale","120000",str(path)]
                subprocess.run(command,input=data,capture_output=True,check=True)

            exact = work/"exact.mp4"
            different = work/"different.mp4"
            encode(exact,original.tobytes()*3)
            encode(different,original.tobytes()*2+altered.tobytes())
            receipt = {}
            self.assertFalse(quality.audit_masters(
                raw,exact,[different,exact],{"width":width,"height":height},Fraction(60),3,
                [(0,2),(2,3)],digest,receipt))
            own, first, second = receipt["raw_audits"]
            self.assertEqual(own["compression"]["overall_psnr_db"],"inf")
            self.assertEqual(first["compression"]["frames_below_floor"],[2])
            self.assertEqual(first["decoded_equality_to_uninterrupted"],
                             {"matching_pictures":2,"different_frames":[2]})
            self.assertEqual(second["decoded_equality_to_uninterrupted"],
                             {"matching_pictures":3,"different_frames":[]})
