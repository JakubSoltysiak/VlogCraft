import os,subprocess,sys,tempfile,time,unittest
from pathlib import Path
from unittest import mock
import psutil
from benchmarks.owned_process import ProcessScope,standard_environment

@unittest.skipUnless(os.name=='nt','Windows job and console qualification')
class OwnedProcessTests(unittest.TestCase):
    def test_missing_known_folder_environment_is_restored_without_replacing_supplied_values(self):
        with mock.patch.dict(os.environ,{'APPDATA':'existing-value'},clear=True):
            env,restored=standard_environment()
        self.assertEqual(env['APPDATA'],'existing-value');self.assertNotIn('APPDATA',restored)
        self.assertTrue(Path(env['LOCALAPPDATA']).is_absolute());self.assertTrue(Path(env['USERPROFILE']).is_absolute())

    def test_diagnostic_failure_cannot_skip_job_cleanup(self):
        owner=ProcessScope();p=owner.launch([sys.executable,'-c','import time;time.sleep(60)'])
        with mock.patch.object(owner,'members',side_effect=RuntimeError('diagnostic failure')):
            with self.assertRaisesRegex(RuntimeError,'diagnostic failure'):owner.close()
        self.assertIsNone(owner.job);self.assertIsNotNone(p.poll())
        self.assertEqual(owner.report['diagnostic_failure_type'],'RuntimeError')

    def test_guard_hides_plain_grandchild_and_composes_with_offline_guard(self):
        env=dict(os.environ,VLOGCRAFT_QA_HIDDEN_CHILDREN='1',VLOGCRAFT_OFFLINE_TEST='1',PYTHONPATH=str(Path('tests/qa_guard').resolve()))
        code='import subprocess,sys,socket;assert getattr(subprocess.Popen,"_qa_hidden",False);assert socket.getaddrinfo.__name__=="local_resolve";p=subprocess.run([sys.executable,"-c","import ctypes;print(ctypes.windll.kernel32.GetConsoleWindow())"],capture_output=True,text=True,check=True);print(p.stdout.strip())'
        with ProcessScope() as owner:
            p=owner.launch([sys.executable,'-c',code],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            output,errors=p.communicate(timeout=10)
            self.assertEqual(p.returncode,0,errors);self.assertEqual(output.strip(),'0')

    def test_logs_exit_status_and_no_console(self):
        with ProcessScope() as owner:
            p=owner.launch([sys.executable,'-c','import ctypes;print(ctypes.windll.kernel32.GetConsoleWindow(),flush=True)'],stdout=subprocess.PIPE,text=True)
            output,_=p.communicate(timeout=10)
            self.assertEqual(p.returncode,0);self.assertEqual(output.strip(),'0')
        self.assertEqual(owner.report['remaining_owned_processes'],0)

    def test_exception_kills_descendants_but_preserves_unrelated_process(self):
        sentinel=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            owner=ProcessScope()
            with self.assertRaisesRegex(RuntimeError,'injected'):
                with owner:
                    code='import subprocess,sys,time;p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(60)"],creationflags=0x08000000);print(p.pid,flush=True);time.sleep(60)'
                    p=owner.launch([sys.executable,'-c',code],stdout=subprocess.PIPE,text=True)
                    child=psutil.Process(int(p.stdout.readline()));created=child.create_time()
                    self.assertIn(child.pid,owner.members());raise RuntimeError('injected')
            self.assertIsNotNone(p.poll());self.assertEqual(owner.report['remaining_owned_processes'],0)
            self.assertIsNone(sentinel.poll())
            self.assertFalse(child.is_running() and child.create_time()==created)
        finally: sentinel.terminate();sentinel.wait()

    def test_timeout_releases_job_and_preserves_log(self):
        with tempfile.TemporaryDirectory() as folder:
            log=Path(folder)/'test.log';owner=ProcessScope()
            with self.assertRaises(subprocess.TimeoutExpired):
                with log.open('w') as out,owner:
                    p=owner.launch([sys.executable,'-c','import time;print("preserved",flush=True);time.sleep(60)'],stdout=out)
                    p.wait(timeout=1)
            self.assertEqual(log.read_text().strip(),'preserved');self.assertIsNotNone(p.poll())

    def test_abrupt_supervisor_exit_closes_job(self):
        code='from benchmarks.owned_process import ProcessScope;import os,sys,time;s=ProcessScope();p=s.launch([sys.executable,"-c","import time;time.sleep(60)"]);print(p.pid,flush=True);os._exit(0)'
        p=subprocess.Popen([sys.executable,'-c',code],stdout=subprocess.PIPE,text=True,creationflags=subprocess.CREATE_NO_WINDOW)
        pid=int(p.stdout.readline());p.stdout.close();p.wait(timeout=10)
        deadline=time.monotonic()+5
        while psutil.pid_exists(pid) and time.monotonic()<deadline:time.sleep(.05)
        self.assertFalse(psutil.pid_exists(pid))

    def test_observer_disconnect_does_not_end_owned_work(self):
        with tempfile.TemporaryDirectory() as folder,ProcessScope() as owner:
            flag=Path(folder)/'finished'
            code='import pathlib,sys,time;print("ready",flush=True);sys.stdout.close();time.sleep(.3);pathlib.Path(sys.argv[1]).write_text("done")'
            p=owner.launch([sys.executable,'-c',code,str(flag)],stdout=subprocess.PIPE,text=True)
            self.assertEqual(p.stdout.readline().strip(),'ready');p.stdout.close()
            p.wait(timeout=10);self.assertEqual(p.returncode,0);self.assertEqual(flag.read_text(),'done')
