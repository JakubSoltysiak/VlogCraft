"""Experimental FP32 video pipe using the qualified CPU HDR10+ delivery stages."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from dataclasses import replace
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

import numpy as np

from conditions import Conditions
from render_phase2 import (BASELINE, ROOT, SCENARIOS, call, clips_for, distribution,
                           native_trial, power, source_picture, technical_conditions, write_plan,
                           write_sources)
from phase2b_conversion import packed_encoder, relay
from phase2b_live import LiveInputs, generated_sources, mixed_audio
from render_phase2_export import compare_encoded, decoded, delivery, encode, mux, streams, video_command


def normalized_loops(folder, scenario):
    """Load two three-frame HEVC controls through explicit SDR/PQ conversions."""
    width,height=scenario.width,scenario.height
    size=f'{width}x{height}'
    sdr='setparams=range=limited:color_primaries=bt709:color_trc=bt709:colorspace=bt709'
    pq='zscale=threads=1:p=2020:t=smpte2084:m=2020_ncl:r=limited:npl=100,format=yuv420p10le'
    linear='zscale=threads=1:agamma=0:p=2020:t=linear:m=gbr:r=full:npl=100,format=gbrpf32le'
    path=folder/'resident.rgba'
    identities=[]
    with path.open('wb') as output:
        for index in range(2):
            video=folder/f'control-{index}.mp4'
            source=f'testsrc2=s={size}:r=60'
            filters=sdr if index==0 else sdr+','+pq
            if index:
                filters+=',hflip'
            tags=('bt2020','smpte2084','bt2020nc') if index else ('bt709','bt709','bt709')
            call(['ffmpeg','-v','error','-nostdin','-f','lavfi','-i',source,'-frames:v','3',
                  '-vf',filters,'-c:v','libx265','-preset','ultrafast','-pix_fmt','yuv420p10le',
                  '-color_primaries',tags[0],'-color_trc',tags[1],'-colorspace',tags[2],'-color_range','tv',
                  '-x265-params','pools=2:frame-threads=1',video],90)
            source_shape=json.loads(call(['ffprobe','-v','error','-select_streams','v:0','-show_streams',
                                          '-of','json',video]).stdout)['streams'][0]
            expected=(*tags,'tv','yuv420p10le')
            if tuple(source_shape[key] for key in ('color_primaries','color_transfer','color_space',
                                                   'color_range','pix_fmt'))!=expected:
                raise ValueError('The encoded SDR/PQ loop lost its declared interpretation')
            raw=folder/'decoded-loop.gbr'
            call(['ffmpeg','-v','error','-nostdin','-threads','2','-i',video,'-vf',linear,
                  '-frames:v','3','-c:v','rawvideo','-threads:v','1','-f','rawvideo',raw],90)
            if raw.stat().st_size!=3*3*height*width*4:
                raise ValueError('Decoded loop has the wrong frame count or geometry')
            with raw.open('rb') as stream:
                rgba=np.ones((height,width,4),dtype='<f4')
                for _ in range(3):
                    green,blue,red=np.fromfile(stream,dtype='<f4',count=3*height*width).reshape(3,height,width)
                    rgba[...,0],rgba[...,1],rgba[...,2]=red,green,blue
                    rgba.tofile(output)
            raw.unlink()
            with video.open('rb') as stream:
                identities.append(hashlib.file_digest(stream,'sha256').hexdigest())
        source_picture(scenario,2).tofile(output)
    return path,((0,1,2),(3,4,5),(6,)),identities


def collect(path):
    # libav driver diagnostics may precede the worker's final report.
    lines=path.read_text(encoding='utf8',errors='replace').splitlines()
    reports=[line for line in lines if line.startswith('{"wall_ms":')]
    if len(reports)!=1:
        raise ValueError('Expected one complete native picture receipt')
    result=json.loads(reports[0])
    samples=result.pop('samples')
    result['frames']=len(samples)
    for key in ('work_ms','gpu_ms','upload_ms','readback_ms','write_ms','dispatch_ms','color_gpu_ms',
                'source_normalization_ms'):
        if any(key in row for row in samples):
            result[key]=distribution([row[key] for row in samples if row.get(key) is not None])
    return result


def stream_video(executable, plan, sources, stage, target, scenario, frames, contract, backend, timeout,
                 conversion='reference',workers=3,simulate_removal=False,*,hardware_bin=None,libav_bin=None):
    """The operating-system pipe blocks the producer when x265 falls behind."""
    native_log=stage/'native.json'
    encoder_log=stage/'encoder.log'
    reference=video_command('pipe:0',target,scenario,frames,contract)
    command=reference.copy() if conversion=='reference' else packed_encoder(reference)
    command[2]='info'
    command[1:1]=['-benchmark','-nostats']
    flags=getattr(subprocess,'CREATE_NO_WINDOW',0)
    processes=[]
    parallel=None
    live=sources if isinstance(sources,LiveInputs) and not hardware_bin else None
    writer=None
    input_stats=None
    started=time.perf_counter()
    with native_log.open('wb') as hints, encoder_log.open('wb') as errors:
        try:
            if live:
                live.start(stage)
            mode='@pq-stream' if conversion=='gpu' else '@gbr-stream'
            if hardware_bin:
                source='@resident:'+str(sources.manifest(stage/'resident-input.bin'))
            else:
                source='@live-stdin' if live else str(sources)
            runtime=hardware_bin or libav_bin
            if runtime:
                native_environment=dict(os.environ)
                native_environment['PATH']=str(runtime.resolve())+os.pathsep+os.environ.get('PATH','')
            else:
                native_environment=None
            native=[str(executable),backend,str(plan),source,mode,'0','8','0']
            if simulate_removal:
                native.append('2')
            producer=subprocess.Popen(native,
                                      stdin=subprocess.PIPE if live else subprocess.DEVNULL,
                                      stdout=subprocess.PIPE,stderr=hints,creationflags=flags,env=native_environment)
            processes.append(producer)
            with producer.stdout:
                sink=subprocess.PIPE if conversion=='parallel' else producer.stdout
                consumer=subprocess.Popen(command,stdin=sink,stdout=subprocess.DEVNULL,
                                          stderr=errors,creationflags=flags)
                processes.append(consumer)
                if live:
                    writer=ThreadPoolExecutor(max_workers=1)
                    future=writer.submit(live.write,producer.stdin)
                if conversion=='parallel':
                    parallel=relay(producer,consumer,reference,stage,frames,scenario.width,scenario.height,
                                   workers,timeout)
            for process in (consumer,producer):
                remaining=max(.01,timeout-(time.perf_counter()-started))
                if process.wait(timeout=remaining):
                    raise RuntimeError('The native producer or the delivery encoder failed')
            if live:
                input_stats=future.result(timeout=max(.01,timeout-(time.perf_counter()-started)))
        finally:
            for process in reversed(processes):
                if process.poll() is None:
                    process.kill()
            if live:
                live.terminate()
                if writer:
                    writer.shutdown()
                live.close()
            for process in reversed(processes):
                process.wait(timeout=10)
                if process.stdin:
                    with suppress(BrokenPipeError):
                        process.stdin.close()
    elapsed=time.perf_counter()-started
    stats=collect(native_log)
    if stats['frames']!=frames:
        raise AssertionError('The native producer wrote the wrong picture count')
    keys=re.search(rb'utime=([\d.]+)s stime=([\d.]+)s rtime=([\d.]+)s',encoder_log.read_bytes())
    stats['encoder_cpu_seconds']=sum(map(float,keys.groups()[:2])) if keys else None
    stats['parallel_compose_and_encode_seconds']=elapsed
    stats['encoder_pix_fmt']='yuv420p10le'
    stats['renderer_pipe_bytes_per_picture']=scenario.width*scenario.height*(3 if conversion=='gpu' else 12)
    if parallel:
        stats['cpu_conversion_workers']=parallel['workers']
        stats['cpu_conversion_setup_seconds']=parallel['worker_setup_seconds']
        stats['cpu_conversion_round_trip_ms']=distribution([1000*v for v in parallel['frame_seconds']])
    if input_stats:
        stats['live_decoders']=input_stats
        stats['live_input_workers']=2 if live.parallel else 1
    if hardware_bin:
        rows=stats.get('resident_sources')
        if not rows or len(rows)!=len(sources.sources):
            raise RuntimeError('Resident decoder did not return complete frame-clock evidence')
        stats['live_decoders']=[dict(source.stats,**row,update_bytes=0)
                                for source,row in zip(sources.sources,rows,strict=True)]
    return stats


def compare_master(reference, candidate, conversion, expected_static):
    from hdr10plus_export import static_metadata

    reference_streams=streams(reference)
    candidate_streams=streams(candidate)
    keys=('pix_fmt','width','height','time_base','duration_ts','color_space','color_transfer',
          'color_primaries','color_range','chroma_location')
    declaration=all(reference_streams[0].get(key)==candidate_streams[0].get(key) for key in keys)
    first_frames=json.loads(call(['ffprobe','-v','error','-select_streams','v:0','-read_intervals','%+#12',
                                  '-show_frames','-of','json',reference]).stdout)['frames']
    declared={json.dumps(item,sort_keys=True) for frame in first_frames for item in static_metadata(frame)}
    same_static=declared=={json.dumps(item,sort_keys=True) for item in expected_static}
    exact_pcm=decoded(reference,'0:a:0','s16le')==decoded(candidate,'0:a:0','s16le')
    quality=compare_encoded(reference,candidate)
    exact_pictures=(decoded(reference,'0:v:0','framemd5')==decoded(candidate,'0:v:0','framemd5')
                    if conversion!='gpu' else None)
    return dict(decoded_pq=quality,exact_pcm=exact_pcm,exact_pictures=exact_pictures,
                stream_declaration_matches=declaration,static_hdr_matches=same_static,
                passed=declaration and same_static and exact_pcm and quality['passed'] and exact_pictures is not False)


def experiment(args):
    sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
    from performance import Resources
    from test_hdr_color import CONTRACT
    from phase2c_author import author_options

    require_ac=not (args.quick and args.backend=='warp32')
    if require_ac and not power():
        raise RuntimeError('AC power is required before starting this qualification')
    scenario=next(item for item in SCENARIOS if item.name=='uhd-mixed')
    if args.loops or args.live:
        scenario=replace(scenario,dissolve=True)
    if args.quick:
        scenario=replace(scenario,width=320,height=180)
    count=args.frames
    results=args.results.resolve()
    results.mkdir(parents=True,exist_ok=False)
    revision=call(['git','rev-parse','HEAD']).stdout.decode().strip()
    conditions=Conditions()
    initial=technical_conditions()
    report={}
    authoring=author_options(args.author_dll,args.author_workers) if args.fast_author else {}
    try:
        with tempfile.TemporaryDirectory(prefix='bounded-',dir=results) as directory:
            stage=Path(directory)
            began=time.perf_counter()
            identities=[]
            source_preparation={}
            if args.live:
                source_start=time.perf_counter()
                paths=args.source
                if len(paths)<2:
                    generated=generated_sources(stage,scenario,count,only_sdr=bool(paths))
                    paths=generated+paths
                source_preparation['fixture_creation_seconds']=time.perf_counter()-source_start
                offsets=args.in_point or [Fraction(1,12),Fraction(1,20)]
                selection_start=time.perf_counter()
                sources=LiveInputs(paths,offsets,scenario,count,args.parallel_decode)
                source_preparation['source_admission_and_index_seconds']=time.perf_counter()-selection_start
                slots=None
            elif args.loops:
                sources,slots,identities=normalized_loops(stage,scenario)
            else:
                sources,_=write_sources(stage,scenario,None,False)
                slots=None
            plan=stage/'plan.bin'
            clips=clips_for(scenario,count)
            window=(count//3, count//3+max(1,count//6)) if args.loops or args.live else None
            write_plan(plan,scenario,clips,count,precise_edges=True,source_slots=slots,dissolve_window=window)
            audio=stage/'common.wav'
            samples=count*48000//scenario.fps
            duration=count/scenario.fps
            audio_started=time.perf_counter()
            if args.live:
                mixed_audio(paths,offsets,samples,audio)
            else:
                call(['ffmpeg','-v','error','-nostdin','-f','lavfi','-i',f'sine=frequency=577:sample_rate=48000:d={duration:.12f}',
                      '-f','lavfi','-i',f'sine=frequency=863:sample_rate=48000:d={duration:.12f}',
                      '-filter_complex','[0:a][1:a]amerge=inputs=2,'
                           f'atrim=end_sample={samples}','-c:a','pcm_s16le',audio],60)
            source_preparation['audio_preparation_seconds']=time.perf_counter()-audio_started
            prep=time.perf_counter()-began
            monitor=Resources(os.getpid(),gpu=False)
            try:
                started=time.perf_counter()
                video=stage/'pipe.video.mov'
                hardware_fallback=False
                try:
                    try:
                        stats=stream_video(args.executable.resolve(),plan,sources,stage,video,
                                           scenario,count,CONTRACT,args.backend,args.timeout,args.conversion,args.workers,
                                           args.simulate_device_removal,hardware_bin=args.hardware_bin,libav_bin=args.libav_bin)
                    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError):
                        if not args.hardware_bin:
                            raise
                        hardware_fallback=True
                        for name in ('native.json','encoder.log'):
                            log=stage/name
                            if log.exists():
                                (results/('hardware-'+name)).write_bytes(log.read_bytes())
                        video.unlink(missing_ok=True)
                        stats=stream_video(args.executable.resolve(),plan,sources,stage,video,
                                           scenario,count,CONTRACT,args.backend,args.timeout,args.conversion,args.workers,
                                           args.simulate_device_removal,libav_bin=args.hardware_bin)
                except Exception:
                    for log in [stage/'native.json',stage/'encoder.log',
                                *stage.glob('converter-*.log'),*stage.glob('decoder-*.log')]:
                        if log.exists():
                            (results/log.name).write_bytes(log.read_bytes())
                    raise
                static=stage/'pipe-static.mp4'
                master=stage/'pipe-HDR10plus.mp4'
                mux_started=time.perf_counter()
                mux(video,audio,static,scenario,count)
                mux_seconds=time.perf_counter()-mux_started
                verify_start=time.perf_counter()
                rendered=delivery(stage,static,master,scenario.fps,count,verify_start-started,authoring=authoring)
                verification_seconds=time.perf_counter()-verify_start-rendered['author_seconds']
            finally:
                metrics=monitor.finish()
            if args.compare_disk:
                packed=stage/'disk.rgba'
                disk_start=time.perf_counter()
                packed_stats=native_trial(args.executable.resolve(),args.backend,plan,sources,0,8,packed)
                disk_static=stage/'disk-static.mp4'
                encode(packed,True,audio,disk_static,scenario,count,CONTRACT)
                disk_master=stage/'disk-HDR10plus.mp4'
                disk=delivery(stage,disk_static,disk_master,scenario.fps,count,time.perf_counter()-disk_start)
                same=decoded(master,'0:v:0','framemd5')==decoded(disk_master,'0:v:0','framemd5')
                if (not same or rendered['audio_pcm_sha256']!=disk['audio_pcm_sha256'] or
                        rendered['static_metadata']!=disk['static_metadata']):
                    raise AssertionError('The pipe changed decoded pictures, PCM or HDR declarations')
                report['packed_disk_control']=dict(disk,native=packed_stats,
                                                   identical_decoded_picture_and_audio=True,
                                                   raw_intermediate_bytes=packed.stat().st_size)
            if args.compare_master:
                report['independent_master_comparison']=compare_master(
                    args.compare_master.resolve(),master,args.conversion,rendered['static_metadata'])
            accepted=not args.compare_master or report['independent_master_comparison']['passed']
            if accepted:
                os.replace(master,results/'verified-hdr10plus.mp4')
            report.update(source_commit=revision,
                          reference=BASELINE,backend=args.backend,conversion=args.conversion,
                          fast_authoring=bool(authoring),native_authoring=bool(args.author_dll),
                          analysis_workers=args.author_workers if args.author_dll else 0,
                          resident_input_requested=bool(args.hardware_bin),resident_input_fallback=hardware_fallback,
                          dimensions=[scenario.width,scenario.height],
                          frames=count,fps=scenario.fps,loops=args.loops,source_clip_hashes=identities,
                          source_preparation_seconds=prep,independent_verification_seconds=verification_seconds,
                          gpu_or_software=stats,resources=metrics,delivery=rendered,
                          live=args.live,source_preparation=source_preparation,final_clock_and_audio_mux_seconds=mux_seconds,
                          output_fps=count/rendered['seconds'],raw_output_intermediate_bytes=0,
                          worker_sha256=hashlib.sha256(args.executable.read_bytes()).hexdigest(),
                          measured_fixture_only=True,
                          final_shader_input_bytes=(sum(d['update_bytes'] for d in stats['live_decoders'])+
                                                    scenario.width*scenario.height*16 if args.live else sources.stat().st_size),
                          executable_conditions=initial)
    finally:
        observation=conditions.finish()
    report['power_and_memory_observation']=observation
    (results/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(json.dumps({key:report[key] for key in ('frames','output_fps','delivery','resources')}, ensure_ascii=True),flush=True)
    if require_ac and (observation['mixed_power'] or not observation['samples'] or
                       not all(s['ac_power'] for s in observation['samples'])):
        raise SystemExit('Mixed power. The result is retained outside the primary comparison.')
    if not accepted:
        raise SystemExit('The independent reference comparison rejected the candidate')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('results',type=Path)
    parser.add_argument('--executable',required=True,type=Path)
    parser.add_argument('--frames',required=True,type=int)
    parser.add_argument('--timeout',type=int,default=900)
    parser.add_argument('--quick',action='store_true')
    parser.add_argument('--loops',action='store_true',help='Use changing decoded SDR/PQ texture loops and a picture dissolve')
    parser.add_argument('--live',action='store_true',help='Stream actual decoder pictures selected by original PTS')
    parser.add_argument('--source',type=Path,action='append',default=[],help='Supply one PQ source or a matched pair')
    parser.add_argument('--in-point',type=Fraction,action='append',default=[],help='Supply two exact relative in-points')
    parser.add_argument('--parallel-decode',action='store_true',help='Read at most one picture per live decoder concurrently')
    parser.add_argument('--hardware-bin',type=Path,help='Try the resident D3D11 source worker with this libav DLL directory')
    parser.add_argument('--libav-bin',type=Path,help='Supply DLLs for a shared worker while retaining software input')
    parser.add_argument('--compare-disk',action='store_true',help='Verify exact equivalence with the packed disk path')
    parser.add_argument('--compare-master',type=Path,help='Independently compare a frozen master made from identical inputs')
    parser.add_argument('--conversion',choices=('reference','parallel','gpu'),default='reference')
    parser.add_argument('--workers',type=int,choices=range(2,5),default=3)
    parser.add_argument('--fast-author',action='store_true',help='Use a bounded large analysis pipe')
    parser.add_argument('--author-dll',type=Path,help='Use the exact native MaxRGB histogram')
    parser.add_argument('--author-workers',type=int,choices=range(1,5),default=1)
    parser.add_argument('--simulate-device-removal',action='store_true',help='Inject D3D11 device removal during a quick test')
    parser.add_argument('--backend',choices=('gpu32','warp32'),default='gpu32')
    args=parser.parse_args()
    if not 2<=args.frames<=3600 or (args.compare_disk and args.frames>48) or args.timeout<1:
        parser.error('Invalid bounded fixture size or timeout')
    if (args.live and (args.loops or args.compare_disk) or not args.live and (args.source or args.in_point or args.parallel_decode)
            or len(args.source)>2 or len(args.in_point) not in (0,2)):
        parser.error('Invalid live source or fixture combination')
    if args.conversion!='reference' and not args.compare_master:
        parser.error('An independently verified reference master is required for candidate publication')
    if args.author_dll and not args.fast_author:
        parser.error('Native analysis requires the explicit fast-authoring option')
    if args.hardware_bin and (not args.live or not args.compare_master or not args.hardware_bin.is_dir()):
        parser.error('Resident input requires a live comparison master and a valid libav DLL directory')
    if args.simulate_device_removal and (not args.quick or args.frames<3):
        parser.error('Fault injection requires a quick fixture with at least three pictures')
    experiment(args)


if __name__=='__main__':
    main()
