from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import export_scratch


class ExportScratchTests(unittest.TestCase):
    def test_export_cleanup_excludes_active_job_and_foreign_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            destination=root/'final.mp4'
            with export_scratch.create(root,destination) as scratch:
                (scratch/'segment_00000.mov').write_bytes(b'media')
                self.assertGreater(export_scratch.usage(root),0)
                self.assertEqual(export_scratch.clear(root,[]),0)
            self.assertFalse(scratch.exists())
            self.assertEqual(export_scratch.usage(root),0)
            with export_scratch.create(root,destination) as scratch:
                (scratch/'user-image.png').write_bytes(b'source')
            self.assertEqual(export_scratch.clear(root,[]),0)
            self.assertEqual((scratch/'user-image.png').read_bytes(),b'source')

    def test_abrupt_owner_exit_is_reclaimable_only_when_unused(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            script=("import export_scratch,os,sys; context=export_scratch.create(sys.argv[1],sys.argv[2]);"
                    "work=context.__enter__(); (work/'segment_00000.mov').write_bytes(b'render');"
                    "print(work,flush=True); os._exit(0)")
            child=subprocess.run([sys.executable,'-c',script,str(root),str(root/'film.mp4')],
                                 capture_output=True,text=True,check=True,timeout=12)
            scratch=Path(child.stdout.strip())
            kept=scratch/'segment_00000.mov'
            self.assertEqual(export_scratch.clear(root,[kept]),0)
            with patch('export_scratch.media_worker_uses',return_value=True):
                self.assertEqual(export_scratch.clear(root,[]),0)
            self.assertEqual(kept.read_bytes(),b'render')
            self.assertEqual(export_scratch.clear(root,[]),1)
            self.assertFalse(scratch.exists())

    def test_cancelled_and_failed_jobs_clean_known_scratch(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            with self.assertRaisesRegex(RuntimeError,'cancelled'):
                with export_scratch.create(root,root/'film.mp4') as scratch:
                    (scratch/'delivery.partial.mp4').write_bytes(b'partial')
                    raise RuntimeError('cancelled')
            self.assertFalse(scratch.exists())
