"""Supervised QA entry point. No shell, console windows, discarded logs or global kills."""
import argparse,json,os,subprocess,time
from pathlib import Path
if __package__:
    from .owned_process import ProcessScope,standard_environment
    from .qa_progress import Tracker,DEFAULT,Activity,duration
else:
    from owned_process import ProcessScope,standard_environment
    from qa_progress import Tracker,DEFAULT,Activity,duration

def main(a):
    if a.command and a.command[0]=='--':a.command=a.command[1:]
    if not a.command:raise ValueError('A QA command is required')
    root=Path(__file__).resolve().parents[1];a.results.mkdir(parents=True,exist_ok=True)
    if (a.results/'supervisor.json').exists():raise FileExistsError('Preserve previous QA results; use a new results directory for a retry')
    env,restored=standard_environment();env['VLOGCRAFT_QA_HIDDEN_CHILDREN']='1'
    env['PYTHONPATH']=str(root/'tests/qa_guard')+os.pathsep+env.get('PYTHONPATH','')
    run_id=a.run_id or env.get('VLOGCRAFT_QA_RUN_ID')
    tracker=Tracker(a.status or env.get('VLOGCRAFT_QA_STATUS',DEFAULT),run_id,a.name or a.results.name)
    container=any(str(x).replace('\\','/').endswith('benchmarks/performance_suite.py') for x in a.command)
    key=a.case_id or a.name or a.results.name;token=None
    if not container:
        if not run_id:tracker.plan([key],complete=True)
        token=tracker.start(key,a.name or key,a.phase,duration(a.command),os.getpid())
    env.update(VLOGCRAFT_QA_RUN_ID=tracker.run_id,VLOGCRAFT_QA_STATUS=str(tracker.path.resolve()))
    began=time.monotonic();reason=None;code=1;owner=ProcessScope();progress_error=None
    try:
        with (a.results/'supervisor.log').open('ab') as log,owner:
            proc=owner.launch(a.command,cwd=root,env=env,stdout=log,stderr=log)
            activity=Activity(proc.pid)
            try:
                while True:
                    remaining=a.timeout-(time.monotonic()-began)
                    if remaining<=0:raise subprocess.TimeoutExpired(a.command,a.timeout)
                    try:code=proc.wait(timeout=min(2,remaining));break
                    except subprocess.TimeoutExpired:
                        if token:
                            try:tracker.heartbeat(key,token,time.monotonic()-began,activity.sample())
                            except Exception as error:progress_error=type(error).__name__
            except subprocess.TimeoutExpired:reason='timeout';code=124
            except KeyboardInterrupt:reason='explicit_interrupt';code=130
            if code in (124,130):owner.close()
            else:
                deadline=time.monotonic()+3
                while owner.members() and time.monotonic()<deadline:time.sleep(.05)
    finally:
        release=owner.close()
        if release['job_members_at_cleanup'] and code==0:reason='unreleased_descendants';code=1
        if token:
            try:tracker.finish(key,token,'cancelled' if code==130 else 'passed' if code==0 else 'failed',code,reason)
            except Exception as error:progress_error=type(error).__name__
        result={'exit_code':code,'reason':reason,'seconds':time.monotonic()-began,'restored_standard_environment_keys':restored,'process_ownership':release,'progress_error':progress_error}
        (a.results/'supervisor.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
        print(json.dumps(result),flush=True)
    return code

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--results',type=Path,required=True);p.add_argument('--timeout',type=float,default=7200)
    p.add_argument('--status',type=Path);p.add_argument('--run-id');p.add_argument('--case-id');p.add_argument('--name');p.add_argument('--phase',default='verification')
    p.add_argument('command',nargs=argparse.REMAINDER);raise SystemExit(main(p.parse_args()))
