"""Repeatable local QUICK/STANDARD/FULL profiles. Generated workloads; no uploads."""
import argparse,json,subprocess,sys,time,os
from pathlib import Path
if __package__:
 from .owned_process import ProcessScope
 from .qa_progress import Tracker,DEFAULT,Activity,duration
else:
 from owned_process import ProcessScope
 from qa_progress import Tracker,DEFAULT,Activity,duration
ROOT=Path(__file__).resolve().parents[1]
def commands(level,executable,media,results):
 py=sys.executable
 steps=[('python',[py,'-m','unittest','discover','-s','tests','-p','test_*.py','-v']),
        ('javascript',['node','--test','tests/timeline_commands.test.js','tests/native_audio_worklet.test.js','tests/native_clock.test.js','tests/meter.test.js','tests/recovery.test.js']),
        ('native-precision',[py,'benchmarks/native_precision.py',str(results/'precision')])]
 if level!='QUICK':
  steps += [('transport',[py,'tests/native_windows.py',str(executable),str(media),str(results/'transport')]),
   ('physical-preview-geometry',[py,'tests/native_geometry.py',str(executable),str(media),str(results/'physical-preview-geometry')]),
   ('view-recovery',[py,'tests/windows_recovery.py',str(executable),str(media),str(results/'view-recovery')]),
   ('audio-ownership',[py,'benchmarks/audio_ownership.py',str(executable),str(media),str(results/'audio-ownership'),'--expect-disposed']),
   ('seeking',[py,'benchmarks/native_seek.py',str(executable),str(media),str(results/'seeking')]),
   ('playback',[py,'benchmarks/native_playback.py',str(executable),str(media),str(results/'playback'),'--seconds','30']),
   ('export',[py,'benchmarks/engine_profile.py',str(results/'export'),str(media/'h264-4k60-0.mp4'),'--width','3840','--seconds','3','--repeat','3','--gpu'])]
 if level=='FULL':
  steps.append(('large-history-recovery',[py,'tests/recovery_large_history.py',str(executable),str(media),str(results/'large-history-recovery')]))
  for mode in ('editor-covered','editor-covered-unfocused'):
   steps.append((mode,[py,'benchmarks/native_playback.py',str(executable),str(media),str(results/mode),'--seconds','125','--window-mode',mode]))
  native=executable.parent/'_internal/engine/native/VlogCraftNative.exe'
  if not native.is_file():native=ROOT/'build/tools/architecture/VlogCraftNative.exe'
  steps.append(('consistency',[py,'benchmarks/consistency.py',str(executable),str(media),str(native),str(results/'consistency'),'--repeat','10','--seconds','125']))
  for width in (960,1280,1920,2560,3840):
   steps.append((f'quality-{width}',[py,'benchmarks/native_playback.py',str(executable),str(media),str(results/f'quality-{width}'),'--seconds','30','--width',str(width)]))
  steps.append(('endurance',[py,'benchmarks/native_playback.py',str(executable),str(media),str(results/'endurance'),'--seconds','600']))
  for name,script in (('project-lifecycle','tests/project_lifecycle.py'),('pressure-cancel','tests/pressure_cancel.py'),('background-recovery','tests/recovery_background.py')):
   steps.append((name,[py,script,str(executable),str(media),str(results/name)]))
  steps.append(('startup-close',[py,'tests/windows_startup_close.py',str(executable),str(results/'startup-close')]))
  for name,seconds,mode in (('memory600',600,'continuous'),('editing1800',1800,'editing')):
   steps.append((name,[py,'benchmarks/session_memory.py',str(executable),str(media),str(results/name),'--seconds',str(seconds),'--mode',mode]))
   steps.append((name+'-analysis',[py,'benchmarks/memory_metrics.py',str(results/name/'memory.json'),str(results/(name+'-analysis.json'))]))
  steps.append(('editing-detached1800',[py,'benchmarks/detached_editing.py',str(executable),str(media),str(results/'editing-detached1800'),'--seconds','1800']))
 return steps
def main(a):
 a.results.mkdir(parents=True,exist_ok=True);report={'level':a.level,'steps':[]}
 if (a.results/'suite.json').exists():raise FileExistsError('Preserve previous suite results; use a new results directory')
 steps=commands(a.level,a.executable.resolve(),a.media.resolve(),a.results.resolve())
 tracker=Tracker(os.environ.get('VLOGCRAFT_QA_STATUS',DEFAULT),os.environ.get('VLOGCRAFT_QA_RUN_ID'),a.level+' QA profile')
 tracker.plan([name for name,cmd in steps],complete=True)
 for name,cmd in steps:
  began=time.perf_counter()
  token=tracker.start(name,phase=a.level,expected_seconds=duration(cmd),pid=os.getpid())
  progress_error=None
  env=dict(os.environ,VLOGCRAFT_QA_HIDDEN_CHILDREN='1');env['PYTHONPATH']=str(ROOT/'tests/qa_guard')+os.pathsep+env.get('PYTHONPATH','')
  with (a.results/(name+'.log')).open('wb') as log,ProcessScope() as owner:
   r=owner.launch(cmd,cwd=ROOT,env=env,stdout=log,stderr=log);activity=Activity(r.pid)
   try:
    while True:
     try:code=r.wait(timeout=2);break
     except subprocess.TimeoutExpired:
      try:tracker.heartbeat(name,token,time.perf_counter()-began,activity.sample())
      except Exception as error:progress_error=type(error).__name__
   except BaseException as error:
    try:tracker.finish(name,token,'cancelled' if isinstance(error,KeyboardInterrupt) else 'failed',reason=type(error).__name__)
    except Exception:pass  # Preserve the original exception and owned-process cleanup.
    raise
   deadline=time.monotonic()+3
   while owner.members() and time.monotonic()<deadline:time.sleep(.05)
  if owner.report['job_members_at_cleanup'] and code==0:code=1
  try:tracker.finish(name,token,'passed' if code==0 else 'failed',code)
  except Exception as error:progress_error=type(error).__name__
  report['steps'].append({'name':name,'exit_code':code,'seconds':time.perf_counter()-began,'process_ownership':owner.report,'progress_error':progress_error})
  (a.results/'suite.json').write_text(json.dumps(report,indent=2),encoding='utf8')
  print(json.dumps(report['steps'][-1]),flush=True)
  if code:raise SystemExit(code)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--level',choices=('QUICK','STANDARD','FULL'),default='QUICK')
 p.add_argument('--executable',type=Path,default=Path(sys.executable));p.add_argument('--media',type=Path,default=ROOT/'build/qa/architecture/media')
 p.add_argument('--results',type=Path,required=True);main(p.parse_args())
