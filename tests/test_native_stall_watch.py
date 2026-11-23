"""Exercise the production watchdog with the Windows lab Zig compiler.

Run directly after installing the Zig lab component, or set
VLOGCRAFT_WATCH_TEST_COMPILER to an existing zig.exe.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def compiler_path():
    configured = os.environ.get("VLOGCRAFT_WATCH_TEST_COMPILER")
    if configured:
        return Path(configured).resolve()
    installed = ROOT / "build/tools/architecture/zig"
    return next(installed.glob("*/zig.exe"), None) or shutil.which("zig")


@unittest.skipUnless(sys.platform == "win32", "the watchdog samples Windows thread state")
class NativeStallWatch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = compiler_path()
        if not compiler:
            raise unittest.SkipTest("the Windows Zig lab compiler is unavailable")
        work = Path(cls.enterClassContext(tempfile.TemporaryDirectory()))
        cls.executable = work / "stall-watch-test.exe"
        cls.work = work
        subprocess.run(
            [
                str(compiler), "c++", "-std=c++17", "-target", "x86_64-windows-gnu",
                "-municode", str(ROOT / "tests/native_stall_watch.cpp"),
                "-o", str(cls.executable),
            ],
            cwd=work,
            check=True,
            timeout=120,
        )

    def run_fixture(self, mode):
        path = self.work / f"{mode}.json"
        subprocess.run([str(self.executable), mode, str(path)], check=True, timeout=20)
        live = path.with_suffix(".json.live")
        return json.loads(path.read_text(encoding="utf-8")), live

    def test_decoder_stall_captures_native_heartbeats_and_recovery_without_gui(self):
        report, live_path = self.run_fixture("blocked")
        live_report = json.loads(live_path.read_text(encoding="utf-8"))
        self.assertEqual(live_report["trigger_count"], 1)
        [live] = live_report["incidents"]
        self.assertEqual(live["last_frame"], 12)
        self.assertEqual(live["generation"], 7)
        self.assertGreaterEqual(live["observed_age_us"], 500000)
        self.assertFalse(live["recovered"])
        self.assertLessEqual(len(live["samples"]), 768)

        coherent = [row for row in live["samples"] if not row[1]]
        self.assertTrue(any(0 <= row[5][0] < 12 for row in coherent))
        blocked = [
            row for row in coherent
            if row[5][0] == 12 and row[9][0] == "receive_picture" and row[9][7][:2] == [1, 0]
        ]
        self.assertGreater(len(blocked), 2)
        self.assertGreater(blocked[-1][4][4] - blocked[0][4][4], 100000)
        for row in blocked:
            self.assertEqual(row[6], [7, 7, 12, 7])
            self.assertEqual(row[7], 7)
            producer = row[9]
            self.assertEqual(producer[3], [3, 12, 1, 90000])
            self.assertEqual(producer[4][3:8], [0, 2, 0, 3, 0])
            self.assertEqual(producer[6], [18000, 15000, 1])
            self.assertGreater(producer[2][8], 0)  # Windows producer thread ID

        self.assertEqual(report["trigger_count"], 1)
        [recovered] = report["incidents"]
        self.assertTrue(recovered["recovered"])
        self.assertFalse(recovered["transition"])
        self.assertFalse(recovered["truncated"])
        self.assertLessEqual(len(recovered["samples"]), 832)
        after = [row for row in recovered["samples"] if not row[1] and row[5][0] == 120]
        self.assertGreater(len(after), 2)
        self.assertGreater(after[-1][0] - after[0][0], 120000)
        self.assertEqual(after[-1][6], [8, 8, 120, 7])
        self.assertEqual(after[-1][7], 8)

    def test_pause_and_pending_seek_exclude_old_native_progress(self):
        for mode in ("pause", "seek"):
            with self.subTest(mode=mode):
                report, live_path = self.run_fixture(mode)
                self.assertGreater(report["polls"], 5)
                self.assertEqual(report["trigger_count"], 0)
                self.assertEqual(report["incidents"], [])
                self.assertFalse(live_path.exists())

    def test_only_three_longest_incidents_are_retained(self):
        report, _ = self.run_fixture("retention")
        self.assertEqual(
            sorted(incident["observed_age_us"] for incident in report["incidents"]),
            [250000, 400000, 900000],
        )


if __name__ == "__main__":
    if sys.platform == "win32" and not compiler_path():
        raise SystemExit("Install the Windows Zig lab compiler or set VLOGCRAFT_WATCH_TEST_COMPILER.")
    unittest.main(verbosity=2)
