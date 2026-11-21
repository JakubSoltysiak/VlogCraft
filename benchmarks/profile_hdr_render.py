"""Instrument generated HDR workloads without changing the production runner."""
import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from unittest.mock import patch
from xml.etree import ElementTree

import psutil


def telemetry(log, **values):
    with log.open('a', encoding='utf-8') as output:
        output.write(json.dumps(values) + '\n')


def progress_frames(file):
    if not file.exists():
        return None
    with file.open('rb') as stream:
        stream.seek(max(0, file.stat().st_size-4096))
        frames = re.findall(rb'^frame=(\d+)', stream.read(), re.MULTILINE)
    return int(frames[-1]) if frames else None


def process_runner(log, gpu=False):
    def run(command, cwd, label=None):
        output = Path(command[-1])
        stage = label or output.name
        stem = Path(cwd) / (output.stem if label is None else label)
        progress = stem.with_suffix('.progress.txt')
        args = list(command)
        if '-loglevel' in args:
            args[args.index('-loglevel')+1] = 'info'
        else:
            args[args.index('-v')+1] = 'info'
        args[1:1] = ['-benchmark', '-nostats', '-stats_period', '0.25', '-progress', str(progress)]
        started = time.monotonic()
        monitor = None
        if gpu:
            from gpu_metrics import GPU
            monitor = GPU()
        with stem.with_suffix('.ffmpeg.log').open('wb') as stderr:
            child = subprocess.Popen(args, cwd=cwd, stdout=subprocess.DEVNULL, stderr=stderr,
                                     creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            process = psutil.Process(child.pid)
            spawned = time.monotonic()-started
            telemetry(log, stage=stage, event='spawn', seconds=spawned)
            sample, peak, disk = {}, 0, 0
            next_gpu_sample = started
            while child.poll() is None:
                try:
                    rss = process.memory_info().rss
                    peak = max(peak, rss)
                    io = process.io_counters()
                    disk = max(disk, sum(path.stat().st_size for path in Path(cwd).glob('*') if path.is_file()))
                    sample = dict(cpu_seconds=sum(process.cpu_times()[:2]), rss_bytes=rss,
                                  process_read_bytes=io.read_bytes, process_write_bytes=io.write_bytes,
                                  job_directory_sample_peak_bytes=disk)
                    telemetry(log, stage=stage, event='sample', seconds=time.monotonic()-started,
                              frames=progress_frames(progress), **sample)
                    if monitor and time.monotonic() >= next_gpu_sample:
                        monitor.sample({child.pid})
                        next_gpu_sample = time.monotonic()+1
                except (psutil.NoSuchProcess, FileNotFoundError):
                    pass
                try:
                    child.wait(timeout=.4)
                except subprocess.TimeoutExpired:
                    continue
        details = stem.with_suffix('.ffmpeg.log').read_text(encoding='utf-8', errors='replace')
        bench = re.search(r'bench: utime=([0-9.]+)s stime=([0-9.]+)s rtime=([0-9.]+)s', details)
        elapsed = time.monotonic()-started
        telemetry(log, stage=stage, event='complete', seconds=elapsed,
                  status=child.returncode, frames=progress_frames(progress), sampled_peak_rss_bytes=peak,
                  ffmpeg_cpu_seconds=sum(map(float, bench.groups()[:2])) if bench else None,
                  gpu=monitor.finish() if monitor else None, **sample)
        if child.returncode:
            raise RuntimeError(details[-2000:])
    return run


@contextmanager
def profile_graphs(engine, log):
    original = engine.segment_command

    def command(*args, **kwargs):
        started = time.monotonic()
        result = original(*args, **kwargs)
        telemetry(log, stage=Path(result[-1]).name, event='compile_graph',
                  seconds=time.monotonic()-started)
        return result

    with patch.object(engine, 'segment_command', command):
        yield


def metadata_by_picture(ff, path, side_data_name):
    xml = ElementTree.fromstring(ff('ffprobe','-v','error','-select_streams','v:0',
                                    '-show_frames','-of','xml',str(path)))
    return [(frame.get('pts'), [tuple(sorted(field.attrib.items())) for side in
             frame.findall(f"./side_data_list/side_data[@type='{side_data_name}']")
             for field in side]) for frame in xml.findall('./frames/frame')]


def compare_delivery(fixture, baseline, candidate):
    before, after = baseline/'master.mp4', candidate/'master.mp4'
    picture_and_audio = fixture.hashes(before) == fixture.hashes(after)
    left = metadata_by_picture(fixture.ff, before, fixture.SIDE_DATA)
    right = metadata_by_picture(fixture.ff, after, fixture.SIDE_DATA)
    return {'decoded_picture_pcm_and_timestamps_equal': picture_and_audio,
            'dynamic_metadata_equal_at_each_pts': bool(left) and all(row[1] for row in left) and left == right,
            'frames': len(left)}


def verify_encoders(fixture, folder, count):
    results = {}
    for label in ('cpu-encode', 'amf-encode'):
        source, marked = folder/(label+'.mp4'), folder/(label+'-authored.mp4')
        info = json.loads(fixture.ff('ffprobe','-v','error','-show_streams','-of','json',str(source)))
        video = info['streams'][0]
        row = {key: video.get(key) for key in (*fixture.hdr10plus_master.VIDEO_FIELDS,
                                              'nb_frames','time_base','duration_ts','avg_frame_rate')}
        row['static_metadata'] = [v['side_data_type'] for v in fixture.hdr10plus_master.static_metadata(video)]
        row['bytes'] = source.stat().st_size
        results[label] = row
        work = folder/(label+'-master')
        work.mkdir()
        try:
            fixture.hdr10plus_master.author(source,marked,work,60,count,fixture.render_engine._run,
                                            lambda *_:None,lambda:False)
            associations = metadata_by_picture(fixture.ff, marked, fixture.SIDE_DATA)
            def decoded(path):
                return fixture.ff('ffmpeg','-v','error','-threads','4','-i',str(path),'-map','0:v',
                                  '-c:v','rawvideo','-threads:v','1','-fps_mode','passthrough',
                                  '-f','framemd5','-')
            row['authoring_passed'] = len(associations) == count and all(a[1] for a in associations)
            row['decoded_encode_and_remux_equal'] = decoded(source) == decoded(marked)
        except (RuntimeError, ValueError) as error:
            row['authoring_passed'] = False
            row['authoring_error'] = str(error)
    (folder/'encoders.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    print(json.dumps(results), flush=True)


def main(args):
    root = args.source.resolve()
    sys.path[:0] = [str(root/'benchmarks'), str(root), str(root/'tests')]
    import studio357_hdr_sequence as fixture

    result = args.results.resolve()
    if args.compare_to:
        comparison = compare_delivery(fixture, args.compare_to, result)
        print(json.dumps(comparison), flush=True)
        return 0 if all(comparison.values()) else 1
    width, height = map(int, args.size.split('x'))
    if args.verify_encoders:
        count, remainder = divmod((result/'same-input.yuv').stat().st_size,width*height*3)
        if not count or remainder:
            raise ValueError('The raw diagnostic does not contain complete 10-bit 4:2:0 pictures')
        verify_encoders(fixture, result, count)
        return
    log = result.with_suffix('.profile.jsonl')
    if log.exists() or result.exists():
        raise FileExistsError('Keep existing measurement attempts')
    log.parent.mkdir(parents=True, exist_ok=True)
    battery = psutil.sensors_battery()
    telemetry(log, event='conditions', ac_power=battery.power_plugged if battery else None,
              logical_processors=psutil.cpu_count())
    runner = process_runner(log, args.gpu)
    engine = fixture.render_engine
    if args.isolate_scene is None:
        with patch.object(engine, '_run', runner), profile_graphs(engine, log):
            fixture.main(result, args.size, args.source_size, args.frames, not args.opacity_motion)
        return

    result.mkdir()
    probe_began = time.monotonic()
    original_probe = fixture.server.probe

    def probe(*params):
        began = time.monotonic()
        metadata = original_probe(*params)
        telemetry(log, stage='source-probe', event='complete', seconds=time.monotonic()-began)
        return metadata

    with patch.object(fixture.server, 'probe', probe):
        state, sources = fixture.state_for(result, (width, height), args.source_size, args.frames,
                                           not args.opacity_motion)
    telemetry(log, stage='generate-and-probe-inputs', event='complete', seconds=time.monotonic()-probe_began)
    start, end = engine.boundaries(state, fixture.server.timing.rate(60))[args.isolate_scene]
    with profile_graphs(engine, log):
        command = engine.segment_command(state, start, end, result/'scene.mp4', result, 'final', 'video')
    graph_path = Path(command[command.index('-/filter_complex')+1])
    graph = graph_path.read_text(encoding='utf-8')
    encoder = command.index('-c:v')
    null_picture = ['-c:v', 'wrapped_avframe', '-f', 'null', '-']
    raw = result/'same-input.yuv'
    for label in args.variant:
        selected = command[:]
        input_graph = graph
        if label in ('graph-only', 'slice4', 'decode-geometry-off', 'no-matte',
                     'no-pq-tail', 'no-transition-arithmetic'):
            selected = selected[:encoder]+null_picture
        if label == 'slice4':
            selected[selected.index('-filter_complex_threads')+1] = '4'
        if label == 'decode-geometry-off':
            input_graph, removed = re.subn(r",geq=r='st\(0,\(X-.*?:a='[^']+'", '', graph)
            if removed != 1:
                raise ValueError(f'Expected one spatial transform, found {removed}')
        if label == 'no-matte':
            input_graph, removed = re.subn(r",geq=r='[^'\n]+'(?::[gba]='[^'\n]+')+:?[^,;\n]*,trim=", ',trim=', graph)
            if not removed:
                raise ValueError('Expected at least one matte')
        if label == 'no-pq-tail':
            input_graph, removed = re.subn(r',sidedata=mode=delete,zscale=[^;]+\[finished\]',
                                            '[finished]', graph)
            if removed != 1:
                raise ValueError('Expected one final PQ conversion')
        if label == 'no-transition-arithmetic':
            input_graph, removed = re.subn(r"(\[base\d+\]\[base\d+\])blend=all_expr='[^']+'(\[transition\d+\])",
                                            r'\1blend=all_mode=normal\2', graph)
            if removed != 1:
                raise ValueError('Select a scene with one video boundary')
        if label == 'startup':
            selected = ['ffmpeg','-v','error','-nostdin','-f','lavfi','-i','color=s=16x16:r=60',
                        '-frames:v','1',*null_picture]
        if label in ('source-demux', 'source-decode', 'video-to-linear'):
            selected = ['ffmpeg','-v','error','-nostdin','-threads','1','-i',str(sources[0]),
                        '-an','-frames:v',command[command.index('-frames:v')+1]]
            if label == 'video-to-linear':
                from hdr_layers import luma_linear
                selected += ['-vf',luma_linear('2020','smpte2084','2020_ncl','limited')+',format=gbrpf32le']
            selected += ['-c:v','copy','-f','null','-'] if label == 'source-demux' else null_picture
        if label == 'still-decode':
            selected = ['ffmpeg','-v','error','-nostdin','-threads','1','-i',str(sources[2]),
                        '-frames:v','1',*null_picture]
        if label == 'write-pq':
            selected = selected[:encoder]+['-c:v','rawvideo','-threads:v','1','-f','rawvideo',str(raw)]
        if label in ('cpu-encode', 'amf-encode'):
            selected = ['ffmpeg','-v','error','-nostdin','-y','-f','rawvideo','-pixel_format','yuv420p10le',
                        '-video_size',args.size,'-framerate','60','-i',str(raw),'-vf','setsar=1',
                        *command[encoder:-1],str(result/(label+'.mp4'))]
            if label == 'amf-encode':
                quality_options = ['-c:v','hevc_amf','-profile','main10','-bitdepth','10','-pix_fmt','p010le',
                                   '-quality','quality','-rc','cqp','-qp_i','20','-qp_p','20']
                selected = selected[:selected.index('-c:v')]+quality_options+selected[selected.index('-color_primaries'):]
        if '-/filter_complex' in selected:
            path = result / (label+'.graph.txt')
            path.write_text(input_graph, encoding='utf-8')
            selected[selected.index('-/filter_complex')+1] = str(path)
        runner(selected, str(result), label)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('results', type=Path)
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--size', default='1280x720')
    parser.add_argument('--source-size', default='1280x720')
    parser.add_argument('--frames', type=int, default=120)
    parser.add_argument('--opacity-motion', action='store_true')
    parser.add_argument('--compare-to', type=Path, help='Compare two completed mixed export directories')
    parser.add_argument('--verify-encoders', action='store_true')
    parser.add_argument('--isolate-scene', type=int)
    parser.add_argument('--gpu', action='store_true', help='Separately sample Windows GPU engines for this diagnostic')
    parser.add_argument('--variant', action='append', default=[],
                        choices=('full', 'graph-only', 'slice4', 'decode-geometry-off', 'no-matte',
                                 'no-pq-tail', 'no-transition-arithmetic', 'startup', 'source-demux',
                                 'source-decode', 'video-to-linear', 'still-decode', 'write-pq',
                                 'cpu-encode', 'amf-encode'))
    raise SystemExit(main(parser.parse_args()))
