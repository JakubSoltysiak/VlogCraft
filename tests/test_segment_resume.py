from fractions import Fraction
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from threading import Event
import unittest
from unittest.mock import patch

from PIL import Image

from benchmarks.phase2b_project_export import export_project
from benchmarks.phase3a_segment_resume import Span, process_spans, qualify
from test_hdr10plus_export import command
from test_hdr_color import project, source
import project_store
import server
import timing


class SegmentResumeTests(unittest.TestCase):
    def test_span_binds_absolute_and_relative_audio_sample_ranges(self):
        span = Span(3, 7, 2, Fraction(60000, 1001))
        self.assertEqual(span.binding, {"frame_range": [3, 7], "reference_frame_range": [1, 5],
                                       "audio_sample_range": [2402, 5606],
                                       "delivery_sample_range": [800, 4004]})

    def test_two_worker_admission_preserves_order_and_propagates_failure(self):
        workers = Event()
        finished = Event()
        stop = Event()
        calls = []

        def process(piece, index):
            calls.append(index)
            if index == 0:
                self.assertTrue(workers.wait(5))
                self.assertTrue(finished.wait(5))
                raise ValueError("injected segment verification failure")
            if index == 1:
                workers.set()
                finished.set()
            return index, piece, False

        with self.assertRaisesRegex(ValueError, "injected segment verification failure"):
            process_spans([0, 1, 2], 2, process, None, stop.is_set, stop)
        self.assertTrue(stop.is_set())
        self.assertEqual(set(calls[:2]), {0, 1})

    def test_media_checkpoints_are_private_until_resume_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            camera = source(root, "pq", nits=800, ramp=True)
            png = root / "photo.png"
            Image.new("RGBA", (48, 56), (24, 70, 214, 164)).save(png)
            photo = dict(id="photo", kind="image", path=str(png), name=png.name, **server.probe(png))
            wav = root / "tone.wav"
            command("ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=f=521:r=48000:d=0.5", str(wav))
            audio = dict(id="audio", kind="audio", path=str(wav), name=wav.name, **server.probe(wav))
            state = project([camera, photo])
            state["output"].update(preset="slow", crf=20, fps="24000/1001")
            state["tracks"][0]["clips"][0].update(end=float(Fraction(6*1001, 24000)), opacity=1)
            state["tracks"][1]["clips"][0].update(position=float(Fraction(6*1001, 24000)),
                                                 end=float(Fraction(6*1001, 24000)))
            state["assets"].append(audio)
            sound = server.default_clip(audio)
            sound["end"] = float(Fraction(12*1001, 24000))
            state["tracks"].append(dict(id="sound", type="audio", name="Sound", volume=1, clips=[sound]))
            saved = root / "project.vlogcraft.json"
            project_store.save(saved, timing.encode(state), server.validate_document)
            archived = root / "reference.mp4"
            restored, _ = project_store.load(saved, server.validate_document)
            export_project(restored, archived, progress=lambda _: None)
            pins = {path: sha256(path.read_bytes()).hexdigest() for path in
                    (saved, Path(camera["path"]), wav, png, archived)}
            work = root / "trial"
            lane = work / "serial"
            result = qualify(saved, work, 0, 12, archived, pins[archived], stop_after=1, progress=lambda _: None)
            self.assertEqual(result["state"], "stopped")
            self.assertFalse((lane / "verified.mp4").exists())
            self.assertFalse((lane / "video-001.json").exists())
            self.assertEqual(json.loads((lane / "video-000.json").read_bytes())["verification"]["state"], "passed")

            # Terminate a separate owner after moving media and before committing its receipt.
            interrupted_run = """
import os
from pathlib import Path
import sys
from benchmarks import phase3a_segment_resume as trial
commit = trial.write_record
def interrupted(path, value):
    if path.name == "video-001.json":
        os._exit(47)
    commit(path, value)
trial.write_record = interrupted
project, work, reference = map(Path, sys.argv[1:4])
trial.qualify(project, work, 0, 12, reference, sys.argv[4], progress=lambda _: None)
"""
            child = subprocess.run([sys.executable, "-c", interrupted_run, str(saved), str(work),
                                    str(archived), pins[archived]], capture_output=True, timeout=60,
                                   cwd=Path(__file__).resolve().parents[1])
            self.assertEqual(child.returncode, 47, child.stderr.decode())
            self.assertTrue((lane / "video-001.mp4").is_file())
            self.assertFalse((lane / "video-001.json").exists())
            cancel = Event()
            with self.assertRaisesRegex(RuntimeError, "cancelled"):
                qualify(saved, work, 0, 12, archived, pins[archived], cancelled=cancel.is_set,
                        progress=lambda _: cancel.set())
            self.assertFalse((lane / "verified.mp4").exists())
            self.assertEqual(json.loads((lane / "run.json").read_bytes())["state"], "cancelled")

            # Refuse the final publication once without accepting it on restart.
            with patch("benchmarks.phase3a_segment_resume.os.link", side_effect=OSError("publication injected")):
                with self.assertRaisesRegex(OSError, "publication injected"):
                    qualify(saved, work, 0, 12, archived, pins[archived], progress=lambda _: None)
            self.assertFalse((lane / "verified.mp4").exists())
            failed = json.loads((lane / "run.json").read_bytes())
            self.assertEqual(failed["state"], "rejected")
            self.assertEqual([item["reused"] for item in failed["segments"]], [True, False])

            result = qualify(saved, work, 0, 12, archived, pins[archived], progress=lambda _: None)
            self.assertEqual(result["state"], "passed")
            self.assertTrue(all(segment["reused"] for segment in result["segments"]))
            self.assertEqual(result["isolated_and_joined_decode_match"], 12)
            self.assertEqual(result["authored_span_comparison"]["exact_decoded_pictures"], 12)
            self.assertEqual(result["audio_endpoint_samples"], 24024)
            self.assertEqual({path: sha256(path.read_bytes()).hexdigest() for path in pins}, pins)
            self.assertTrue((lane / "verified.mp4").is_file())

            # A renamed file with a known digest cannot stand in for a continuous encoder receipt.
            pending_control = root / "unverified-control.mp4"
            pending_control.write_bytes(b"unverified control")
            with self.assertRaisesRegex(ValueError, "uninterrupted encoder receipt"):
                qualify(saved, root / "unqualified-two", 0, 12, archived, pins[archived],
                        continuous_reference=pending_control,
                        continuous_sha256=sha256(pending_control.read_bytes()).hexdigest(),
                        workers=2, progress=lambda _: None)
            self.assertFalse((root / "unqualified-two" / "two-workers").exists())

            # A real receipt from the same project cannot certify a substituted movie.
            (root / "control.json").write_text(json.dumps({
                "passed": True, "continuous": True, "pool": 2, "frames": 12,
                "project_hash": pins[saved], "master_sha256": pins[archived],
                "prepared_main10_sha256": "0"*64,
                "encoder_contexts": [{"-frames:v": "12", "-preset": "slow", "-crf": "20"}],
            }))
            with self.assertRaisesRegex(ValueError, "uninterrupted encoder receipt"):
                qualify(saved, root / "substituted-control", 0, 12, archived, pins[archived],
                        continuous_reference=pending_control,
                        continuous_sha256=sha256(pending_control.read_bytes()).hexdigest(),
                        progress=lambda _: None)

            # A modified linked source invalidates the whole checkpoint specification.
            sound_stamp = wav.stat()
            sound_bytes = bytearray(wav.read_bytes())
            sound_bytes[-1] ^= 1
            wav.write_bytes(sound_bytes)
            os.utime(wav, ns=(sound_stamp.st_atime_ns, sound_stamp.st_mtime_ns))
            with self.assertRaisesRegex(ValueError, "pinned identities or configuration changed"):
                qualify(saved, work, 0, 12, archived, pins[archived], progress=lambda _: None)
