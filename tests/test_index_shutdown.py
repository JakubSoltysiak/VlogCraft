import os
from pathlib import Path
import subprocess,sys,tempfile,threading,unittest
from unittest import mock
from source_frames import FrameIndex

class IndexShutdownTests(unittest.TestCase):
    def test_close_between_registration_and_launch_does_not_spawn(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);index=FrameIndex(root/'pts')
            original=tempfile.NamedTemporaryFile
            def close_before_launch(*args,**kwargs):
                file=original(*args,**kwargs);index.close();return file
            with mock.patch('source_frames.tempfile.NamedTemporaryFile',side_effect=close_before_launch),mock.patch('source_frames.subprocess.Popen') as spawn:
                with self.assertRaisesRegex(ValueError,'cancelled'):
                    index.build({'id':'asset','path':str(root/'unused.mp4')},root/'pts'/'new.pts')
                spawn.assert_not_called()
            self.assertFalse(index.running)

    def test_close_cancels_and_reaps_running_worker_before_return(self):
        with tempfile.TemporaryDirectory() as folder:
            index=FrameIndex(Path(folder))
            process=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],
                                     creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            cancelled=threading.Event()
            index.running['asset']={'process':process,'cancel':cancelled,'count':0}
            try:
                index.close()
                self.assertTrue(cancelled.is_set());self.assertIsNotNone(process.poll())
                with self.assertRaisesRegex(ValueError,'closed'):
                    index.build({'id':'another'},Path(folder)/'new.pts')
            finally:
                if process.poll() is None:process.kill();process.wait()
