"""Repeated original-media transport trials; retain every result and poor run."""
import argparse,hashlib,json,os,statistics,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def percentile(values,q):
    if not values:return None
    ordered=sorted(values);at=(len(ordered)-1)*q;lo=int(at);hi=min(lo+1,len(ordered)-1)
    return ordered[lo]+(ordered[hi]-ordered[lo])*(at-lo)

def summary(rows):
    good=[r for r in rows if r.get('exit_code')==0]
    fps=[r['fps'] for r in good];skips=[r['skips'] for r in good]
    return {'completed':len(rows),'valid':len(good),'fps_all':fps,'skips_all':skips,
        'fps_best':max(fps) if fps else None,'fps_median':statistics.median(fps) if fps else None,
        'fps_worst':min(fps) if fps else None,'fps_p05_across_trials':percentile(fps,.05),'fps_population_stdev':statistics.pstdev(fps) if fps else None,
        'at_least_59_5':sum(v>=59.5 for v in fps),'under_30_skips':sum(v<30 for v in skips),
        'zero_underruns':bool(good) and all(r.get('underruns')==0 for r in good),'failed_trials':len(rows)-len(good)}
def main(a):
    a.results.mkdir(parents=True,exist_ok=True);report=a.results/'consistency.json'
    assert not report.exists(),'Preserve existing trial results; use a new results directory'
    dll=a.executable.resolve().parent/'_internal/engine/native'
    if not dll.is_dir():dll=ROOT/'build/tools/architecture/ffmpeg-shared/ffmpeg-9.0.2-full_build-shared/bin'
    env=dict(os.environ,PYTHONUTF8='1',VLOGCRAFT_NATIVE_BINARY=str(a.native.resolve()),PATH=str(dll)+os.pathsep+os.environ['PATH'])
    native_sha=hashlib.sha256(a.native.read_bytes()).hexdigest();rows=[]
    for n in range(1,a.repeat+1):
        folder=a.results/f'trial-{n:02d}';folder.mkdir()
        env['VLOGCRAFT_NATIVE_TRACE_FILE']=str((folder/'missed-frames.json').resolve())
        probe=ROOT/'build/tools/architecture/VlogCraftProbe.exe'
        inventory=json.loads(subprocess.check_output([str(probe)],env=env))
        (folder/'workstation.json').write_text(json.dumps(inventory,indent=2),encoding='utf8')
        cmd=[sys.executable,'benchmarks/native_playback.py',str(a.executable.resolve()),str(a.media.resolve()),str(folder),'--seconds',str(a.seconds),'--width',str(a.width),'--trace']
        began=time.monotonic()
        with (folder/'trial.log').open('wb') as log:result=subprocess.run(cmd,cwd=ROOT,env=env,stdout=log,stderr=log)
        row={'trial':n,'exit_code':result.returncode,'wall_seconds':round(time.monotonic()-began,3)}
        path=folder/'native-playback.json'
        if path.is_file():
            d=json.loads(path.read_text('utf8'));d.setdefault('last',{});d.setdefault('resources',{});row.update(fps=d.get('distinct_sequence_fps',d.get('present_calls_per_second')),
                skips=d['last'].get('skipped_sequence_frames'),samples=d.get('samples'),expected_samples=d.get('expected_samples'),
                underruns=d.get('underruns'),first_ready_seconds=d.get('first_ready_seconds'),startup_seconds=d.get('application_ready_seconds'),
                peak_working_set_MiB=d['resources'].get('peak_summed_working_set_MiB'),CPU_percent=d['resources'].get('average_cpu_machine_percent'),
                present_intervals=d['last'].get('timings',{}).get('playback_present_interval',d['last'].get('timings',{}).get('present_call_interval')),throughput_windows=d.get('throughput_windows'),
                source_skips=d['last'].get('skipped_after_source_wait'),gpu_skips=d['last'].get('skipped_after_gpu_wait'),
                other_skips=d['last'].get('skipped_without_queue_wait'),mixed_power=d.get('conditions',{}).get('mixed_power',True),
                all_on_AC=all(r['ac_power'] is True for r in d.get('conditions',{}).get('samples',[])))
        rows.append(row)
        record={'native_binary_sha256':native_sha,'seconds':a.seconds,'width':a.width,'layers':3,'audio_tracks':3,
            'cache_policy':'Fresh application each trial; repeated original-source offsets; OS filesystem caches unmanaged',
            'proxy':False,'rows':rows,'summary':summary(rows)}
        report.write_text(json.dumps(record,indent=2),encoding='utf8');print(json.dumps(row),flush=True)
        if result.returncode:raise SystemExit(result.returncode)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('executable',type=Path);p.add_argument('media',type=Path);p.add_argument('native',type=Path);p.add_argument('results',type=Path)
    p.add_argument('--repeat',type=int,default=10);p.add_argument('--seconds',type=float,default=125);p.add_argument('--width',type=int,default=960);main(p.parse_args())
