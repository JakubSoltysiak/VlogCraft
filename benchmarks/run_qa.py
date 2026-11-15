"""Supervised QA entry point. No shell, console windows, discarded logs or global kills."""
import argparse,json,os,subprocess,time
from pathlib import Path
from owned_process import ProcessScope,standard_environment

def main(a):
    if a.command and a.command[0]=='--':a.command=a.command[1:]
    if not a.command:raise ValueError('A QA command is required')
    root=Path(__file__).resolve().parents[1];a.results.mkdir(parents=True,exist_ok=True)
    env,restored=standard_environment();env['VLOGCRAFT_QA_HIDDEN_CHILDREN']='1'
    env['PYTHONPATH']=str(root/'tests/qa_guard')+os.pathsep+env.get('PYTHONPATH','')
    began=time.monotonic();reason=None;code=1;owner=ProcessScope()
    try:
        with (a.results/'supervisor.log').open('ab') as log,owner:
            proc=owner.launch(a.command,cwd=root,env=env,stdout=log,stderr=log)
            try:code=proc.wait(timeout=a.timeout)
            except subprocess.TimeoutExpired:reason='timeout';code=124
            except KeyboardInterrupt:reason='explicit_interrupt';code=130
            if code in (124,130):owner.close()
            else:
                deadline=time.monotonic()+3
                while owner.members() and time.monotonic()<deadline:time.sleep(.05)
    finally:
        release=owner.close()
        if release['job_members_at_cleanup'] and code==0:reason='unreleased_descendants';code=1
        result={'exit_code':code,'reason':reason,'seconds':time.monotonic()-began,'restored_standard_environment_keys':restored,'process_ownership':release}
        (a.results/'supervisor.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
        print(json.dumps(result),flush=True)
    return code

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--results',type=Path,required=True);p.add_argument('--timeout',type=float,default=7200)
    p.add_argument('command',nargs=argparse.REMAINDER);raise SystemExit(main(p.parse_args()))
