"""Exercise deadline expiry on a software producer with a real FFmpeg decoder."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from test_native_stall_watch import ROOT, compiler_path


@unittest.skipUnless(sys.platform == "win32", "the native producer uses Windows APIs")
class NativeRefillLiveness(unittest.TestCase):
    def test_producer_refills_while_renderer_cannot_release_hold(self):
        compiler = compiler_path()
        lab = ROOT / "build/tools/architecture/ffmpeg-shared"
        sdk = next(lab.glob("ffmpeg-*-full_build-shared"), None)
        ffmpeg = shutil.which("ffmpeg")
        if not (compiler and sdk and ffmpeg):
            self.skipTest("native lab Zig, shared FFmpeg SDK and FFmpeg are required")
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            media = work / "refill.mp4"
            worker = work / "refill.exe"
            subprocess.run(
                [ffmpeg, "-v", "error", "-nostdin", "-f", "lavfi", "-i", "testsrc2=size=64x64:rate=10:duration=2",
                 "-an", "-c:v", "libx264", "-threads", "1", "-video_track_timescale", "60000", str(media)],
                check=True, timeout=30,
            )
            subprocess.run(
                [str(compiler), "c++", "-std=c++17", "-O2", "-target", "x86_64-windows-gnu",
                 ROOT / "tests/native_refill_liveness.cpp", "-I" + str(sdk / "include"), "-L" + str(sdk / "lib"),
                 "-lavformat", "-lavcodec", "-lavutil", "-lswscale", "-ld3d11", "-ldxgi", "-o", worker],
                check=True, timeout=120,
            )
            env = {**os.environ, "PATH": str(sdk / "bin") + os.pathsep + os.environ.get("PATH", "")}
            subprocess.run([worker, media], env=env, check=True, timeout=15)


if __name__ == "__main__":
    unittest.main(verbosity=2)
