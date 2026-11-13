"""Repeatable local QUICK/STANDARD/FULL profiles. Generated workloads; no uploads."""
import argparse,json,subprocess,sys,time,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def commands(level,executable,media,results):
 py=sys.executable
 steps=[('python',[py,'-m','unittest','discover','-s','tests','-p','test_*.py','-v']),
        ('javascript',['node','--test','tests/timeline_commands.test.js','tests/native_audio_worklet.test.js','tests/native_clock.test.js']),
        ('native-precision',[py,'benchmarks/native_precision.py',str(results/'precision')])]
 if level!='QUICK':
  steps += [('transport',[py,'tests/native_windows.py',str(executable),str(media),str(results/'transport')]),
   ('seeking',[py,'benchmarks/native_seek.py',str(executable),str(media),str(results/'seeking')]),
   ('playback',[py,'benchmarks/native_playback.py',str(executable),str(media),str(results/'playback'),'--seconds','30']),
   ('export',[py,'benchmarks/engine_profile.py',str(results/'export'),str(media/'h264-4k60-0.mp4'),'--width','3840','--seconds','3','--repeat','3','--gpu'])]
 if level=='FULL':
  for width in (960,1280,1920,2560,3840):
   steps.append((f'quality-{width}',[py,'benchmarks/native_playback.py',str(executable),str(media),str(results/f'quality-{width}'),'--seconds','30','--width',str(width)]))
  steps.append(('endurance',[py,'benchmarks/native_playback.py',str(executable),str(media),str(results/'endurance'),'--seconds','600']))
 return steps
def main(a):
 a.results.mkdir(parents=True,exist_ok=True);report={'level':a.level,'steps':[]}
 for name,cmd in commands(a.level,a.executable.resolve(),a.media.resolve(),a.results.resolve()):
  began=time.perf_counter()
  with (a.results/(name+'.log')).open('wb') as log:r=subprocess.run(cmd,cwd=ROOT,stdout=log,stderr=log)
  report['steps'].append({'name':name,'exit_code':r.returncode,'seconds':time.perf_counter()-began})
  (a.results/'suite.json').write_text(json.dumps(report,indent=2),encoding='utf8')
  print(json.dumps(report['steps'][-1]),flush=True)
  if r.returncode:raise SystemExit(r.returncode)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--level',choices=('QUICK','STANDARD','FULL'),default='QUICK')
 p.add_argument('--executable',type=Path,default=Path(sys.executable));p.add_argument('--media',type=Path,default=ROOT/'build/qa/architecture/media')
 p.add_argument('--results',type=Path,required=True);main(p.parse_args())
