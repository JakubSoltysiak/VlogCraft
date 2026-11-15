"""Deterministic compiler barrier: no timing benchmark or real encoder needed."""
import io,tempfile,threading,unittest
from pathlib import Path
from unittest import mock
import native_playback

class PCMPreparationLockTests(unittest.TestCase):
    def run_case(self,stop=False):
        with tempfile.TemporaryDirectory() as folder:
            c=native_playback.Controller(None,Path(folder),Path(folder));c.generation=1
            c.snapshot={'output':{'fps':60},'tracks':[{'type':'video','clips':[{'assetId':'fixture','start':0,'end':16,'position':0}]}]}
            entered=threading.Event();release=threading.Event();done=threading.Event();streams=[];errors=[]
            def compile(*args):entered.set();self.assertTrue(release.wait(5));return ['encoder','output.wav']
            def prepare():
                try:streams.append(c.audio(1,0))
                except Exception as error:errors.append(error)
            def control():
                if stop:c.stop()
                else:c.clock(123456,True,1)
                done.set()
            p=mock.Mock();p.poll.return_value=None;p.wait.return_value=0;p.stdout=io.BytesIO(b'\0'*(384000*4))
            with mock.patch('native_playback.render_engine.segment_command',side_effect=compile),mock.patch('native_playback.subprocess.Popen',return_value=p) as launch:
                worker=threading.Thread(target=prepare);worker.start();self.assertTrue(entered.wait(2),repr(errors))
                command=threading.Thread(target=control);command.start()
                try:self.assertTrue(done.wait(.3),'Clock/Stop blocked behind graph compilation')
                finally:
                    release.set();worker.join(5);command.join(5)
                    for samples,end,chunks in streams:
                        if stop:
                            try:list(chunks)
                            except ValueError:pass
                        else:self.assertEqual(len(b''.join(chunks)),samples*4)
                    c.close()
                self.assertFalse(worker.is_alive());self.assertFalse(command.is_alive())
                if stop:
                    self.assertEqual(launch.call_count,0,'Obsolete preparation spawned an encoder after Stop')
                    self.assertEqual(len(errors),1);self.assertIsInstance(errors[0],ValueError)
                else:self.assertFalse(errors);self.assertEqual(c.clock_position,123456)
    def test_clock_delivery_is_independent_of_slow_pcm_graph_preparation(self):self.run_case()
    def test_stop_fences_inflight_preparation_before_encoder_launch(self):self.run_case(stop=True)
