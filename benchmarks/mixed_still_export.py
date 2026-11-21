"""Compare the frozen and current SDR renderers with the same generated UHD60 sequence."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT),str(ROOT/'tests')]
import render_engine
from test_export_workflow import decode, fixture, ffmpeg


def main(results, revision):
    results = results.resolve()
    results.mkdir(parents=True,exist_ok=True)
    module = results/'baseline_renderer.py'
    module.write_bytes(subprocess.check_output(['git','show',revision+':render_engine.py'],cwd=ROOT))
    spec = importlib.util.spec_from_file_location('baseline_renderer',module)
    baseline = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(baseline)
    state,paths = fixture(results,3840,2160,5)
    hashes = [hashlib.sha256(path.read_bytes()).digest() for path in paths]
    rows = []
    report = {'baseline':revision,'output':'3840x2160/60','encoder':'libx264',
              'scope':'One pair on generated mixed PNG, JPEG and video with audio. Wall time includes segment drains and final mux.', 'runs':rows}
    for name,engine in [('baseline',baseline),('candidate',render_engine)]:
        target = results/(name+'.mp4')
        start = time.perf_counter()
        row = {'arm':name}
        try:
            engine.render(state,target,results/(name+'-scratch'),popen=lambda cmd,cwd: subprocess.run(
                cmd,cwd=cwd,check=True,capture_output=True,timeout=90))
            row['seconds'] = time.perf_counter()-start
            video,audio = decode(target)
            assert int(video['nb_read_frames'])==324
            assert (video['width'],video['height'],video['avg_frame_rate'])==(3840,2160,'60/1')
            assert abs(float(audio['duration'])-5.4)<.002
            row.update(status='passed',frames=324,frames_per_second=324/row['seconds'],
                       audio_duration=float(audio['duration']),video_duration=float(video['duration']))
        except (subprocess.CalledProcessError,subprocess.TimeoutExpired,AssertionError) as error:
            row.update(status='failed',reason=type(error).__name__,seconds=time.perf_counter()-start)
            if isinstance(error,subprocess.CalledProcessError):
                (results/(name+'-error.log')).write_bytes(error.stderr or b'')
        rows.append(row)
        (results/'comparison.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    if all(row['status']=='passed' for row in rows):
        samples = lambda arm: ffmpeg('-i',results/(arm+'.mp4'),'-vf','scale=96:54','-pix_fmt','rgb24','-f','rawvideo','pipe:1')
        a,b = samples('baseline'),samples('candidate')
        assert len(a)==len(b)==324*96*54*3
        report['mean_absolute_RGB_error_8bit'] = sum(abs(x-y) for x,y in zip(a,b))/len(a)
        assert report['mean_absolute_RGB_error_8bit']<2
    report['original_hashes_match'] = [hashlib.sha256(path.read_bytes()).digest() for path in paths]==hashes
    (results/'comparison.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps(report))
    assert all(row['status']=='passed' for row in rows) and report['original_hashes_match']


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('results',type=Path)
    parser.add_argument('--baseline',default='7d1b2b4a38f51bd5aae383512971e8fbfa1c6492')
    args=parser.parse_args()
    main(args.results,args.baseline)
