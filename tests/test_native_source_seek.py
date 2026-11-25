"""Check the packet index without requiring a hardware decoder."""
from fractions import Fraction
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

import native_project_plan as plan
import native_source_seek as seek


class SourceSeekTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "camera.mp4"
        self.manifest = Path(folder.name) / "sources.bin"

    def samples(self, rows, *, hevc=True):
        config = bytearray(23 if hevc else 7)
        config[0] = 1
        config[21 if hevc else 4] = 3
        self.video = dict(width=128, height=72, codec_name="hevc" if hevc else "h264",
                          codec_tag_string="hvc1" if hevc else "avc1",
                          extradata="00000000: " + config.hex(), profile="Main", pix_fmt="yuv420p",
                          time_base="1/1000", color_primaries="bt709", color_transfer="bt709",
                          color_space="bt709", color_range="tv", field_order="progressive")
        data = bytearray()
        packets = []
        for pts, dts, flags, kind in rows:
            nal = bytes([kind << 1, 1, 0]) if hevc else bytes([kind, 0])
            sample = struct.pack(">I", len(nal)) + nal
            packets.append(dict(pts=pts, dts=dts, flags=flags, pos=str(len(data)), size=str(len(sample))))
            data.extend(sample)
        self.path.write_bytes(data)
        self.packets = {"packets": packets}
        self.stream = {"streams": [self.video], "format": {"format_name": "mov,mp4", "start_time": ".012"}}

    def capture(self, command, **_):
        answer = self.stream if "-show_data" in command else self.packets
        return json.dumps(answer).encode("ascii"), b""

    def test_cra_index_keeps_vfr_pts_and_identifies_only_decodable_leading(self):
        self.samples([
            (12, -8, "K__", 20), (41, 5, "___", 1), (29, 20, "___", 0),
            (103, 34, "K__", 21), (70, 48, "___", 8), (83, 60, "___", 7),
            (121, 74, "___", 1), (156, 88, "K__", 19), (171, 104, "___", 1),
        ])
        src = plan.Source(self.path, (128, 72), "", (128, 72), "video", None,
                          ("bt709", "bt709", "bt709", "limited", "rec709"),
                          {0: Fraction(71, 1000), 1: Fraction(91, 1000), 2: Fraction(109, 1000)})
        program = plan.Program(128, 72, Fraction(60), 1, [(0, 3)], [src], [None] * 3)
        with patch.object(plan, "run_capture", side_effect=self.capture):
            clocks = plan.write_sources(self.manifest, program, camera_range=True, keyframe_seek=True)
        # A request for the leading picture itself must still start at the
        # earlier IDR, since its PTS precedes the CRA.
        self.assertEqual(clocks[0], (Fraction(1, 1000), Fraction(12, 1000),
                                     [12, 29, 41, 70, 83, 103, 121], [4, 5, 6]))
        manifest = self.manifest.read_bytes()
        self.assertEqual(manifest[:4], b"VSD3")
        self.assertEqual(struct.unpack("<IqqIIIq", manifest[-40:]), (1, 34, 21, 5, 21, 1, 83))

    def test_h264_requires_an_idr_even_if_the_container_marks_other_pictures_key(self):
        self.samples([
            (12, -8, "K__", 5), (41, 5, "___", 1), (29, 20, "___", 1),
            (70, 34, "K__", 1), (83, 60, "___", 1), (103, 74, "K__", 5),
            (121, 88, "___", 1),
        ], hevc=False)
        _, stamps, points = seek.probe(self.path, 2, "stream=codec_name", self.capture, lambda: False)
        self.assertEqual(stamps, [12, 29, 41, 70, 83, 103, 121])
        self.assertEqual([(point.picture, point.dts, point.kind) for point in points], [(0, -8, 5), (5, 74, 5)])

    def test_corrupt_or_ambiguous_packet_index_uses_the_decoded_clock(self):
        self.samples([(12, -8, "K__", 20), (41, 5, "___", 1), (29, 20, "___", 0)])
        src = plan.Source(self.path, (128, 72), "", (128, 72), "video", None,
                          ("bt709", "bt709", "bt709", "limited", "rec709"), {0: Fraction(17, 1000)})
        decoded = {**self.stream, "frames": [{"best_effort_timestamp": pts} for pts in (12, 29, 41)]}
        for change in ({"pts": 12}, {"dts": -8}, {"flags": "_D_"}, {"pos": "N/A"}):
            with self.subTest(change=change):
                packets = self.packets["packets"].copy()
                packets[1] = {**packets[1], **change}
                probes = [(json.dumps(row).encode("ascii"), b"")
                          for row in (self.stream, {"packets": packets}, decoded)]
                with patch.object(plan, "run_capture", side_effect=probes) as run, self.manifest.open("wb") as output:
                    clock = plan.append_video(output, 0, src, 1, lambda: False, keyframe_seek=True)
                self.assertEqual(clock[2:], ([12, 29], [1]))
                self.assertIn("frame=best_effort_timestamp", " ".join(map(str, run.call_args.args[0])))
                self.assertEqual(self.manifest.read_bytes()[-4:], bytes(4))

    def test_cra_rejects_a_reordered_nonleading_nal(self):
        self.samples([
            (12, -8, "K__", 20), (41, 5, "___", 1),
            (103, 34, "K__", 21), (83, 60, "___", 1), (121, 74, "___", 1),
        ])
        _, _, points = seek.probe(self.path, 2, "stream=codec_name", self.capture, lambda: False)
        self.assertEqual([point.kind for point in points], [20])
