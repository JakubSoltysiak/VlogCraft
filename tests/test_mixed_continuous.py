"""Bounded transport and encoder contract for the mixed continuous laboratory path."""
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import subprocess
import sys
import tempfile
from threading import Event
from types import SimpleNamespace
import unittest

import hdr_render
import mixed_continuous as continuous
from native_project_render import NativeFailure
from test_hdr_color import project


class ContinuousPipeTests(unittest.TestCase):
    def test_relay_preserves_the_following_span_and_reports_truncation(self):
        source, destination = BytesIO(b"firstsecond"), BytesIO()
        digest = sha256()
        buffer = memoryview(bytearray(2))
        continuous.relay_exact(source,destination,5,lambda:None,buffer,digest)
        self.assertEqual(source.read(),b"second")
        self.assertEqual(destination.getvalue(),b"first")
        self.assertEqual(digest.digest(),sha256(b"first").digest())
        with self.assertRaisesRegex(NativeFailure,"ended before"):
            continuous.relay_exact(BytesIO(b"one"),BytesIO(),4,lambda:None,buffer)

    def test_two_camera_spans_feed_one_live_sink_in_order(self):
        with tempfile.TemporaryDirectory() as temp, continuous.Processes(10, lambda:False) as owner:
            work = Path(temp)
            target = work/"encoder-input"
            with target.open("wb") as captured:
                sink = owner.start([sys.executable,"-c","import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"],
                                   stdin=subprocess.PIPE,stdout=captured)
            source = owner.start([sys.executable,"-c","import sys; sys.stdout.buffer.write(b'firstsecond')"],
                                 stdout=subprocess.PIPE)
            raster = [sys.executable,"-c",
                      "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read().upper())"]
            output_hash = sha256()
            buffer = memoryview(bytearray(3))
            for n, size in enumerate((5,6)):
                continuous.drain_raster(owner,raster,work/f"raster-{n}.log",sink,1,size,
                                        buffer,output_hash,producer=source,source_bytes=size)
            with source.stdout:
                self.assertEqual(source.stdout.read(),b"")
            owner.wait(source,"source")
            sink.stdin.close()
            owner.wait(sink,"sink")
            self.assertEqual(target.read_bytes(),b"FIRSTSECOND")
            self.assertEqual(output_hash.hexdigest(),sha256(b"FIRSTSECOND").hexdigest())

    def test_cancellation_retires_both_children_of_a_live_pipe(self):
        cancelled = Event()
        with continuous.Processes(10, cancelled.is_set) as owner:
            sleeper = [sys.executable, "-c", "import time; time.sleep(30)"]
            producer = owner.start(sleeper, stdout=subprocess.PIPE)
            consumer = owner.start(sleeper, stdin=producer.stdout)
            cancelled.set()
            with self.assertRaisesRegex(NativeFailure,"cancelled"):
                owner.wait(producer,"producer")
            with self.assertRaisesRegex(NativeFailure,"cancelled"):
                owner.wait(consumer,"consumer")
            producer.stdout.close()
        self.assertIsNotNone(producer.poll())
        self.assertIsNotNone(consumer.poll())

    def test_persistent_encoder_retains_saved_encoder_settings(self):
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp)
            state = project([])
            state["output"].update(fps=60,preset="slow",crf=20,bitrate=60)
            managed = hdr_render.command(state,0.,2/60,work/"scene.mov",work)
            plan = SimpleNamespace(width=128,height=72,fps=60,frames=range(48))
            result = continuous.encoder_command(managed,plan,work/"continuous.mov",8)
            self.assertEqual(result.count("libx265"),1)
            self.assertEqual(result[result.index("-frames:v")+1],"48")
            self.assertEqual(result[result.index("-preset")+1],"slow")
            self.assertEqual(result[result.index("-crf")+1],"20")
            self.assertIn("pools=8:frame-threads=2", result[result.index("-x265-params")+1])
