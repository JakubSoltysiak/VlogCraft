"""Deterministic compiler barrier: no timing benchmark or real encoder needed."""
import io,tempfile,threading,unittest
from pathlib import Path
from unittest import mock
import native_playback

class PCMPreparationLockTests(unittest.TestCase):
    def run_case(self,stop=False,seek=False):
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
                elif seek:c.seek(1,1)
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
                        if stop or seek:
                            try:list(chunks)
                            except ValueError:pass
                        else:self.assertEqual(len(b''.join(chunks)),samples*4)
                    c.close()
                self.assertFalse(worker.is_alive());self.assertFalse(command.is_alive())
                if stop or seek:
                    self.assertEqual(launch.call_count,0,'Obsolete preparation spawned an encoder after Stop')
                    self.assertEqual(len(errors),1);self.assertIsInstance(errors[0],ValueError)
                else:self.assertFalse(errors);self.assertEqual(c.clock_position,123456)
    def test_clock_delivery_is_independent_of_slow_pcm_graph_preparation(self):self.run_case()
    def test_stop_fences_inflight_preparation_before_encoder_launch(self):self.run_case(stop=True)
    def test_seek_fences_preparation_while_the_snapshot_identity_is_unchanged(self):self.run_case(seek=True)
    def test_seek_dispatches_picture_target_before_reaping_pcm(self):
        with tempfile.TemporaryDirectory() as folder:
            controller=native_playback.Controller(None,Path(folder),Path(folder))
            controller.generation=1
            controller.snapshot={'output':{'fps':60}}
            child=mock.Mock()
            controller.audio_processes.add(child)

            def reap(process):
                self.assertIs(process,child)
                self.assertEqual(controller.clock_position,500000)
                self.assertEqual(controller.generation,2)

            with mock.patch.object(controller,'_terminate',side_effect=reap) as terminate:
                self.assertEqual(controller.seek(30,1),{'generation':2})
                terminate.assert_called_once_with(child)
            controller.audio_processes.clear()
            controller.close()

    def test_concurrent_graphs_cannot_overadmit_the_two_process_budget(self):
        with tempfile.TemporaryDirectory() as folder:
            c=native_playback.Controller(None,Path(folder),Path(folder));c.generation=1
            c.snapshot={'output':{'fps':60},'tracks':[{'type':'video','clips':[{'assetId':'fixture','start':0,'end':16,'position':0}]}]}
            barrier=threading.Barrier(3);streams=[];errors=[]
            def compile(*args):barrier.wait(3);return ['encoder','output.wav']
            def launch(*args,**kwargs):
                p=mock.Mock();p.poll.return_value=None;p.wait.return_value=0;p.stdout=io.BytesIO(b'\0'*(384000*4));return p
            def prepare():
                try:streams.append(c.audio(1,0))
                except Exception as error:errors.append(error)
            with mock.patch('native_playback.render_engine.segment_command',side_effect=compile),mock.patch('native_playback.subprocess.Popen',side_effect=launch) as spawn:
                workers=[threading.Thread(target=prepare) for _ in range(3)]
                for worker in workers:worker.start()
                for worker in workers:worker.join(5)
                try:
                    self.assertFalse(any(w.is_alive() for w in workers));self.assertEqual(spawn.call_count,2)
                    self.assertEqual(len(c.audio_processes),2);self.assertEqual(len(errors),1);self.assertIsInstance(errors[0],ValueError)
                    for samples,end,chunks in streams:self.assertEqual(len(b''.join(chunks)),samples*4)
                finally:c.close()
