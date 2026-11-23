import json,os,subprocess,sys,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
import server,render_engine
from benchmarks.owned_process import ProcessScope

class ConsoleLaunchTests(unittest.TestCase):
 def test_metadata_probe_retains_command_output_and_timeout_without_console(self):
  result=SimpleNamespace(returncode=0,stdout=json.dumps({'format':{'duration':'1'},'streams':[{'codec_type':'video','width':64,'height':36,'r_frame_rate':'24/1','codec_name':'h264'}]}))
  with mock.patch('server.subprocess.run',return_value=result) as run:
   data=server.probe(Path('generated.mp4'))
  self.assertEqual((data['width'],data['height'],data['fps']),(64,36,24))
  self.assertEqual(run.call_args.kwargs['creationflags'],getattr(subprocess,'CREATE_NO_WINDOW',0))
  self.assertEqual(run.call_args.kwargs['timeout'],75)

 def test_thumbnail_and_default_renderer_keep_logging_and_hide_console(self):
  with tempfile.TemporaryDirectory() as folder,mock.patch.object(server,'THUMBS',Path(folder)),mock.patch('subprocess.run',return_value=SimpleNamespace(returncode=0,stderr='')) as run:
   server.create_thumbnail({'id':'generated','kind':'video','duration':1,'path':'generated.mp4'})
   self.assertEqual(run.call_args.kwargs['creationflags'],getattr(subprocess,'CREATE_NO_WINDOW',0))
   render_engine._run(['ffmpeg','-version'],folder)
   self.assertEqual(run.call_args.kwargs['creationflags'],getattr(subprocess,'CREATE_NO_WINDOW',0))
   self.assertTrue(run.call_args.kwargs['capture_output'])
   self.assertEqual(run.call_args.kwargs['timeout'],7200)

 def test_proxy_uses_background_priority_and_publishes_completed_output(self):
  options=getattr(subprocess,'CREATE_NO_WINDOW',0)|getattr(subprocess,'BELOW_NORMAL_PRIORITY_CLASS',0)
  with tempfile.TemporaryDirectory() as folder:
   proxy=Path(folder)/'proxy.mp4'
   asset={'id':'generated','path':'generated.mp4','name':'generated','duration':2}
   process=mock.MagicMock()
   process.stdout=[b'out_time_us=2000000']
   process.wait.return_value=0
   process.__enter__.return_value=process
   def launch(cmd,**kwargs):
    self.assertEqual(kwargs['creationflags'],options)
    Path(cmd[-1]).write_bytes(b'completed proxy')
    return process
   with mock.patch.object(server,'PROXIES',Path(folder)), \
        mock.patch.object(server,'proxy_path',return_value=proxy), \
        mock.patch.object(server,'CURRENT_PROCESS',{}), \
        mock.patch.object(server,'CANCEL',{'proxy':threading.Event()}), \
        mock.patch.object(server,'job_status') as status, \
        mock.patch.object(server,'start_next_proxy'), \
        mock.patch('server.subprocess.Popen',side_effect=launch):
    server.run_proxy(asset)
    self.assertEqual(proxy.read_bytes(),b'completed proxy')
    self.assertEqual(server.CURRENT_PROCESS,{'proxy':None})
    self.assertEqual(status.call_args.kwargs['status'],'done')
    self.assertFalse(proxy.with_suffix('.partial.mp4').exists())

 @unittest.skipUnless(os.name=='nt','GUI-parent console allocation is Windows-specific')
 def test_real_gui_parent_metadata_probes_leave_no_console_hosts(self):
  with tempfile.TemporaryDirectory() as folder:
   source=Path(folder)/'generated.mp4'
   subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=s=64x36:r=24:d=0.25','-c:v','libx264',str(source)],check=True,capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
   env=dict(os.environ,VLOGCRAFT_QA_HIDDEN_CHILDREN='0')
   # Disable the QA hiding shim in this GUI parent: exercise production flags.
   env['PYTHONPATH']=str(Path('tests/offline_guard').resolve())
   gui=Path(sys.executable).with_name('pythonw.exe');self.assertTrue(gui.is_file())
   script='import json,sys;from pathlib import Path;import server;a=[server.probe(Path(sys.argv[1])) for _ in range(3)];print(json.dumps([x["width"] for x in a]),flush=True)'
   owner=ProcessScope()
   with owner:
    p=owner.launch([str(gui),'-c',script,str(source)],cwd=Path(__file__).resolve().parents[1],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    output,errors=p.communicate(timeout=30)
    self.assertEqual(p.returncode,0,errors);self.assertEqual(json.loads(output),[64]*3)
   self.assertEqual(owner.report['job_members_at_cleanup'],0,owner.report)
   self.assertEqual(owner.report['remaining_owned_processes'],0)
