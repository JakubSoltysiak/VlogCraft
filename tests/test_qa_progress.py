import json,os,subprocess,sys,tempfile,threading,time,unittest
from pathlib import Path
from unittest import mock
from benchmarks.qa_progress import Tracker,snapshot,atomic,duration,Activity,read_document

class ProgressTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.path=Path(self.folder.name)/'status.json';self.tracker=Tracker(self.path,'fixture','Fixture QA')

    def test_unknown_total_stays_unknown_and_dynamic_cases_are_counted(self):
        a=self.tracker.start('a');self.tracker.finish('a',a,'passed')
        b=self.tracker.start('b');d=snapshot(self.path)
        self.assertIsNone(d['total']);self.assertIsNone(d['completion_percent'])
        self.assertEqual((d['completed'],d['discovered'],d['counts']['running']),(1,2,1))

    def test_retry_preserves_failure_and_does_not_inflate_total(self):
        self.tracker.plan(['a','b'],complete=True)
        a=self.tracker.start('a');self.tracker.finish('a',a,'failed',1)
        retry=self.tracker.start('a');self.tracker.finish('a',retry,'passed',0)
        b=self.tracker.start('b');self.tracker.finish('b',b,'skipped')
        d=snapshot(self.path)
        self.assertEqual((d['total'],d['completed'],d['counts']['passed'],d['counts']['skipped']),(2,2,1,1))
        self.assertEqual((d['attempts'],d['historical_failed_attempts'],d['completion_percent']),(3,1,100))

    def test_obsolete_attempt_and_completed_result_cannot_be_overwritten(self):
        first=self.tracker.start('a');self.tracker.finish('a',first,'failed')
        latest=self.tracker.start('a')
        with self.assertRaises(ValueError):self.tracker.finish('a',first,'passed')
        self.tracker.finish('a',latest,'cancelled',130)
        with self.assertRaises(ValueError):self.tracker.finish('a',latest,'passed')
        self.assertEqual(snapshot(self.path)['counts']['cancelled'],1)

    def test_heartbeat_activity_and_stall_are_distinct(self):
        token=self.tracker.start('a',expected_seconds=600,pid=os.getpid())
        self.tracker.heartbeat('a',token,462,activity=False)
        d=snapshot(self.path,now=time.time()+35)['running'][0]
        self.assertTrue(d['controller_alive']);self.assertEqual(d['elapsed_seconds'],462)
        self.assertEqual(d['observation_status'],'heartbeat stale')
        self.tracker.heartbeat('a',token,463,activity=True)
        self.assertIn('activity observed',snapshot(self.path)['running'][0]['observation_status'])

    def test_controller_death_is_not_fabricated_completion(self):
        self.tracker.start('a',pid=os.getpid())
        with mock.patch('benchmarks.qa_progress.psutil.Process',side_effect=__import__('psutil').NoSuchProcess(1)):
            d=snapshot(self.path)
        self.assertEqual(d['completed'],0);self.assertFalse(d['running'][0]['controller_alive'])
        self.assertIn('without a result',d['running'][0]['observation_status'])

    def test_atomic_write_failure_preserves_previous_document(self):
        self.tracker.plan(['a'],complete=True);before=self.path.read_bytes()
        with mock.patch('benchmarks.qa_progress.os.replace',side_effect=OSError('injected')):
            with self.assertRaises(OSError):self.tracker.plan(['b'])
        self.assertEqual(self.path.read_bytes(),before)
        self.assertFalse(list(self.path.parent.glob('.qa-status-*.tmp')))

    def test_concurrent_writers_and_readers_never_lose_results(self):
        self.tracker.plan([],complete=False);errors=[];stop=threading.Event()
        def reader():
            while not stop.wait(.001):
                try:read_document(self.path)
                except Exception as error:errors.append(error)
        observer=threading.Thread(target=reader);observer.start()
        def work(n):
            try:
                t=Tracker(self.path,'fixture');token=t.start(str(n));t.finish(str(n),token,'passed')
            except Exception as error:errors.append(error)
        writers=[threading.Thread(target=work,args=(n,)) for n in range(12)]
        for w in writers:w.start()
        for w in writers:w.join()
        stop.set();observer.join()
        self.assertEqual(errors,[]);self.assertEqual(snapshot(self.path)['completed'],12)

    def test_legacy_import_is_append_only_and_groups_exact_retry_ids(self):
        self.tracker.import_legacy([{'name':'a','exit_code':1},{'name':'a','exit_code':0},{'name':'b','exit_code':1}])
        d=snapshot(self.path);self.assertEqual((d['total'],d['attempts'],d['historical_failed_attempts']),(2,3,2))
        with self.assertRaises(ValueError):self.tracker.import_legacy([])

    def test_corrupt_status_is_preserved_instead_of_reset(self):
        self.path.write_text('interrupted invalid bytes')
        with self.assertRaises(ValueError):self.tracker.plan(['a'])
        self.assertEqual(self.path.read_text(),'interrupted invalid bytes')

    def test_windows_sharing_denial_is_retried_without_resetting_data(self):
        with mock.patch.object(Path,'read_text',side_effect=[PermissionError('sharing'),'{"preserved":true}']):
            self.assertEqual(read_document(self.path),{'preserved':True})

    def test_declared_duration_never_claims_measured_frame_progress(self):
        self.assertEqual(duration(['script','--seconds','125','--repeat','10']),1250)
        self.assertEqual(duration(['script','--seconds','600','--measure-seconds','90']),90)
        self.assertIsNone(duration(['script']))

    def test_process_activity_sampling_detects_work_without_gpu_polling(self):
        sample=Activity(os.getpid());self.assertFalse(sample.sample())
        with (Path(self.folder.name)/'activity').open('wb') as out:
            out.write(b'x'*1048576);out.flush();os.fsync(out.fileno())
        self.assertTrue(sample.sample())

    def test_independent_supervisor_records_result_without_observer(self):
        results=Path(self.folder.name)/'run';log=Path(self.folder.name)/'launch.log'
        with log.open('w') as out:
            p=subprocess.Popen([sys.executable,'benchmarks/run_qa.py','--results',str(results),'--status',str(self.path),
                '--run-id','fixture','--case-id','background','--',sys.executable,'-c','import time;time.sleep(2.2);print("done")'],
                stdout=out,stderr=out,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            p.wait(timeout=20)
        self.assertEqual(p.returncode,0,log.read_text());d=snapshot(self.path)
        self.assertEqual(d['counts']['passed'],1);self.assertTrue((results/'supervisor.log').is_file())
        before=(results/'supervisor.json').read_bytes()
        retry=subprocess.run([sys.executable,'benchmarks/run_qa.py','--results',str(results),'--',sys.executable,'-c','raise SystemExit(99)'],
            capture_output=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.assertNotEqual(retry.returncode,0);self.assertEqual((results/'supervisor.json').read_bytes(),before)

    def test_text_viewer_works_with_a_legacy_windows_console_encoding(self):
        result=subprocess.run([sys.executable,'tools/qa_status.py','--status',str(self.path),'--run-id','fixture','--plan','a','b'],
            env=dict(os.environ,PYTHONUTF8='0',PYTHONIOENCODING='cp1250'),capture_output=True,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.assertEqual(result.returncode,0,result.stderr.decode('utf8',errors='replace'))
        self.assertIn('Completed: 0 / 2',result.stdout.decode('utf8'))

    def test_profile_records_leaf_steps_without_an_extra_parent_case(self):
        import argparse
        from benchmarks import performance_suite
        results=Path(self.folder.name)/'profile'
        steps=[(name,[sys.executable,'-c','print("complete")']) for name in ('first','second')]
        args=argparse.Namespace(results=results,level='QUICK',executable=Path(sys.executable),media=Path('.'))
        with mock.patch.object(performance_suite,'commands',return_value=steps),mock.patch.dict(os.environ,{'VLOGCRAFT_QA_STATUS':str(self.path),'VLOGCRAFT_QA_RUN_ID':'fixture'}):
            performance_suite.main(args)
        d=snapshot(self.path);self.assertEqual((d['total'],d['completed'],d['counts']['passed']),(2,2,2))
