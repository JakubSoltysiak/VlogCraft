from contextlib import ExitStack
from pathlib import Path
import tempfile
from threading import Event
import unittest
from unittest.mock import Mock, patch

import hdr10plus_master
import mixed_project_delivery as mixed
from native_project_render import NativeFailure
import server


class MixedExportEndpointTests(unittest.TestCase):
    def test_only_explicit_mixed_request_selects_the_new_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = root/"reference.mp4"
            reference.write_bytes(b"comparison")
            known = {"path": str(root/"destination.mp4"), "delivery": "hdr10plus-master"}
            cases = [
                ({}, None, False, False),
                ({"comparisonMaster": str(reference)}, reference, False, False),
                ({"experimentalFirstExport": True}, None, True, False),
                ({"comparisonMaster": str(reference), "experimentalMixedExport": True}, reference, False, True),
            ]
            for changes, comparison, first, mixed_mode in cases:
                with self.subTest(request=changes):
                    response, thread, options = self.submit(root, {**known, **changes})
                    self.assertTrue(response.call_args.args[0]["started"])
                    arguments = thread.call_args.kwargs
                    self.assertEqual(arguments["kwargs"], {"mixed": True} if mixed_mode else {})
                    if comparison or first:
                        self.assertEqual(arguments["args"][-2:], (comparison, first))
                    self.assertEqual(options.get("experimental_mixed_export", False), mixed_mode)

    def test_mixed_option_requires_runtime_an_existing_master_and_separate_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = root/"reference.mp4"
            reference.write_bytes(b"comparison")
            base = {"path": str(root/"destination.mp4"), "delivery": "hdr10plus-master",
                    "experimentalMixedExport": True}
            with_reference = {**base, "comparisonMaster": str(reference)}
            cases = [(base, True), (with_reference, False), ({**with_reference, "delivery": "render"}, True),
                     ({**with_reference, "experimentalFirstExport": True}, True),
                     ({**with_reference, "experimentalMixedExport": "true"}, True),
                     ({**with_reference, "comparisonMaster": str(root/"missing.mp4")}, True)]
            for request, available in cases:
                with self.subTest(request=request, available=available):
                    response, thread, options = self.submit(root, request, available=available)
                    self.assertEqual(response.call_args.args[-1], 400)
                    thread.assert_not_called()
                    self.assertIsNone(options)

    def submit(self, root, request, *, available=True):
        state = server.default_state()
        state["tracks"][0]["clips"].append(server.default_title(0))
        handler = server.Handler.__new__(server.Handler)
        handler.path = "/api/export"
        handler.check_origin = lambda: True
        handler.read_json = lambda: request
        handler.json_response = Mock()
        with (patch.object(server, "STATE", state), patch.dict(server.JOBS, export={"status": "idle"}),
              patch.object(server, "NATIVE_PROJECT_RUNTIME", root if available else None),
              patch.object(server, "NATIVE_EXPORT_THREAD"),
              patch.object(server, "remember_export_folder"),
              patch.object(server.CANCEL["export"], "clear"),
              patch.object(server.threading, "Thread") as thread,
              patch.object(server.export_jobs, "start") as register,
              patch.object(hdr10plus_master, "preflight", return_value=48),
              patch.object(server.encoders, "available", return_value={"libx265": "HEVC"})):
            handler.do_POST()
        return handler.json_response, thread, register.call_args.args[3] if register.called else None


class MixedExportPrivateDeliveryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.reference = self.root/"comparison.mp4"
        self.reference.write_bytes(b"matched master")
        self.destination = self.root/"destination.mp4"
        self.destination.write_bytes(b"original destination")
        self.scratch = self.root/"scratch"
        self.scratch.mkdir()
        self.cancelled = Event()
        self.state = {"output": {"width": 3840, "height": 2160, "fps": 60, "encoder": "libx265",
                                 "preset": "slow", "crf": 20, "bitrate": 60}, "tracks": [], "assets": []}
        self.verification = {"verifiedFrames": 48, "verifiedHdr10PlusFrames": 48, "verifiedAudioSamples": 38400,
                             "x265PoolWorkers": 2}
        video = {"width": 3840, "height": 2160, "time_base": "1/120000", "duration_ts": 96000,
                 "nb_frames": "48", "avg_frame_rate": "60/1"}
        audio = {"time_base": "1/48000", "duration_ts": 38400}
        mocks = ExitStack()
        self.addCleanup(mocks.close)
        mocks.enter_context(patch.object(mixed.hdr10plus_master, "preflight", return_value=48))
        mocks.enter_context(patch.object(mixed.hdr10plus_export, "media", return_value=(video, audio)))
        mocks.enter_context(patch.object(mixed, "author_options", return_value={}))
        self.native = mocks.enter_context(patch.object(mixed, "export_native", side_effect=self.render_candidate))
        self.verify = mocks.enter_context(patch.object(mixed, "verify_master", side_effect=self.verify_candidate))
        self.publish = Mock(side_effect=lambda part, target: part.replace(target))
        self.fallback = Mock()

    def render_candidate(self, state, candidate, reference, executable, runtime, **options):
        self.assertIsNone(reference)
        self.assertTrue(candidate.is_relative_to(self.scratch))
        self.assertEqual(self.destination.read_bytes(), b"original destination")
        candidate.write_bytes(b"verified mixed candidate")
        return {"delivered_backend": "mixed-d3d11-zimg-managed"}

    def verify_candidate(self, reference, candidate, *_args):
        self.assertEqual(reference, self.reference)
        self.assertEqual(candidate.read_bytes(), b"verified mixed candidate")
        self.assertEqual(self.destination.read_bytes(), b"original destination")
        return self.verification

    def run_mixed(self):
        return mixed.export_mixed_editor(self.state, self.destination, self.reference, self.root, self.scratch,
                                         publish=self.publish, fallback=self.fallback, progress=Mock(),
                                         cancelled=self.cancelled.is_set)

    def test_exact_verification_publishes_using_qualified_options(self):
        receipt = self.run_mixed()
        options = self.native.call_args.kwargs
        self.assertTrue(all(options[key] for key in ("first_time", "camera_range", "qualification",
                                                     "camera_raster", "mixed", "fast_raster")))
        self.assertFalse(options["parallel_x265"])
        self.assertEqual(receipt, {"verificationPolicy": "mixed-exact-master",
                                  "deliveredBackend": "mixed-d3d11-zimg-managed", **self.verification})
        self.assertEqual(self.destination.read_bytes(), b"verified mixed candidate")
        self.assertEqual(self.reference.read_bytes(), b"matched master")
        self.assertFalse(list(self.scratch.iterdir()))
        self.fallback.assert_not_called()

    def test_rejected_candidate_or_incompatible_profile_uses_managed_fallback(self):
        self.verify.side_effect = NativeFailure("different decoded picture")
        self.assertEqual(self.run_mixed()["deliveredBackend"], "reference")
        self.state["output"]["preset"] = "medium"
        self.native.reset_mock()
        self.assertEqual(self.run_mixed()["deliveredBackend"], "reference")
        self.native.assert_not_called()
        self.assertEqual(self.fallback.call_count, 2)
        self.assertEqual(self.destination.read_bytes(), b"original destination")
        self.assertFalse(list(self.scratch.iterdir()))
        self.publish.assert_not_called()

    def test_cancellation_or_failed_atomic_publish_does_not_trigger_fallback(self):
        self.verify.side_effect = lambda *_: (self.cancelled.set() or self.verification)
        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            self.run_mixed()
        self.publish.assert_not_called()
        self.cancelled.clear()
        self.verify.side_effect = self.verify_candidate
        self.publish.side_effect = OSError("publication failed")
        with self.assertRaisesRegex(OSError, "publication failed"):
            self.run_mixed()
        self.fallback.assert_not_called()
        self.assertEqual(self.destination.read_bytes(), b"original destination")
        self.assertFalse(list(self.scratch.iterdir()))


class MixedMasterGateTests(unittest.TestCase):
    def test_decoded_frame_equality_does_not_accept_changed_hdr_payloads(self):
        results = {"passed": True, "per_frame_psnr_db": ["inf"]*2, "decoded_pq_psnr_db": "inf",
                   "exact_decoded_pcm": True, "audio_endpoint_samples": 1600}
        with (patch.object(mixed, "compare_project", return_value=results),
              patch.object(mixed.hdr10plus_export, "media", return_value=({}, {})),
              patch.object(mixed, "packet_timeline", side_effect=[{0: ("old",)}, {0: ("new",)}])):
            with self.assertRaisesRegex(NativeFailure, "HDR10\\+ payloads"):
                mixed.verify_master(Path("reference"), Path("candidate"), {"output": {"fps": 60}},
                                    2, Path("."), lambda: False)

    def test_sample_equality_does_not_accept_changed_aac_packet_clock(self):
        results = {"passed": True, "per_frame_psnr_db": ["inf"]*2, "decoded_pq_psnr_db": "inf",
                   "exact_decoded_pcm": True, "audio_endpoint_samples": 1600}
        with (patch.object(mixed, "compare_project", return_value=results),
              patch.object(mixed.hdr10plus_export, "media", return_value=({}, {})),
              patch.object(mixed, "packet_timeline", return_value={0: ("identical",)}),
              patch.object(mixed, "audio_packet_clock", side_effect=[[(0, 0, 1000)], [(0, 0, 999)]])):
            with self.assertRaisesRegex(NativeFailure, "AAC packet clock"):
                mixed.verify_master(Path("reference"), Path("candidate"), {"output": {"fps": 60}},
                                    2, Path("."), lambda: False)
