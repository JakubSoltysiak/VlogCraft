"""Bounded experimental export using a native compositor and the existing HDR10+ author."""
import argparse
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

from render_phase2 import (BASELINE, ROOT, SCENARIOS, call, clips_for, compare_pictures,
                           native_trial, power, reference_trial, technical_conditions,
                           write_plan, write_sources)


def encode(source, packed, audio, target, scenario, frames, contract):
    from color_management import x265_metadata
    from hdr_render import final_clock

    video=target.with_suffix('.video.mov')
    command=['ffmpeg','-v','error','-nostdin','-f','rawvideo','-pixel_format','gbrpf32le',
             '-video_size',f'{scenario.width}x{scenario.height}','-framerate',str(scenario.fps),
             '-i','pipe:0' if packed else str(source)]
    command+=['-map','0:v:0','-an','-frames:v',str(frames),
              '-vf','setsar=1,zscale=threads=1:agamma=0:pin=2020:tin=linear:min=gbr:rin=full:'
                    'p=2020:t=smpte2084:m=2020_ncl:r=limited:npl=100:dither=error_diffusion,'
                    'format=yuv420p10le',
              '-filter_threads','1','-c:v','libx265','-preset','ultrafast','-crf','15',
              '-profile:v','main10','-x265-params',x265_metadata(contract),
              '-color_primaries','bt2020','-color_trc','smpte2084','-colorspace','bt2020nc',
              '-color_range','tv','-tag:v','hvc1','-threads','4',
              '-video_track_timescale','120000','-movie_timescale','120000','-movflags','+faststart',str(video)]
    if not packed:
        call(command,240)
    else:
        pictures=np.memmap(source,dtype='<f4',mode='r',shape=(frames,scenario.height,scenario.width,4))
        with tempfile.TemporaryFile() as log, subprocess.Popen(command,stdin=subprocess.PIPE,stderr=log,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)) as process:
            try:
                with process.stdin:
                    for frame in pictures:
                        for channel in (1,2,0):
                            process.stdin.write(np.ascontiguousarray(frame[...,channel]).data.cast('B'))
                if process.wait(timeout=240):
                    log.seek(0)
                    raise RuntimeError(log.read().decode(errors='replace')[-1200:])
            except BaseException:
                if process.poll() is None:
                    process.kill()
                raise
    playlist=target.with_suffix('.txt')
    playlist.write_text(f"file '{video.name}'\n",encoding='utf8')
    clocks=final_clock(playlist,scenario.fps,frames,lambda:False)
    call(['ffmpeg','-v','error','-nostdin','-f','concat','-safe','0','-i',playlist,'-i',audio,
          '-map','0:v:0','-map','1:a:0','-c:v','copy',*clocks,'-c:a','aac','-b:a','192k',
          '-video_track_timescale','120000','-movie_timescale','120000','-movflags','+faststart',target],120)


def streams(path):
    return json.loads(call(['ffprobe','-v','error','-show_streams','-of','json',path]).stdout)['streams']


def decoded(path, stream, muxer):
    command=['ffmpeg','-v','error','-threads','2','-i',path,'-map',stream]
    if stream=='0:v:0':
        command+=['-c:v','rawvideo','-threads:v','1','-fps_mode','passthrough']
    return call([*command,'-f',muxer,'-'],180).stdout


def delivery(stage, static, master, fps, count, seconds):
    from hdr10plus_export import media, static_metadata
    from hdr10plus_index import SIDE_DATA
    from hdr10plus_master import author
    from profile_hdr_render import metadata_by_picture
    from render_engine import _run

    work=stage/(master.stem+'-authoring')
    work.mkdir()
    started=time.perf_counter()
    authored=author(static,master,work,fps,count,_run,lambda *_:None,lambda:False)
    author_seconds=time.perf_counter()-started
    video,audio=media(master)
    if video['time_base']!='1/120000' or int(video['duration_ts'])*fps!=count*120000:
        raise AssertionError('Unexpected edited video clock')
    if audio['time_base']!='1/48000' or int(audio['duration_ts'])*fps!=count*48000:
        raise AssertionError('Unexpected edited audio clock')
    blocks=metadata_by_picture(lambda *args:call(args,120).stdout,master,SIDE_DATA)
    if len(blocks)!=count or authored!=count or any(int(pts)*fps!=i*120000 or not data
                                                  for i,(pts,data) in enumerate(blocks)):
        raise AssertionError('Incorrect dynamic metadata association')
    pictures=decoded(master,'0:v:0','framemd5')
    pcm=decoded(master,'0:a:0','s16le')
    if pictures!=decoded(static,'0:v:0','framemd5') or pcm!=decoded(static,'0:a:0','s16le'):
        raise AssertionError('Authored file changed decoded video or audio')
    frame_data=json.loads(call(['ffprobe','-v','error','-select_streams','v:0','-show_frames','-of','json',master]).stdout)
    declared={json.dumps(value,sort_keys=True) for frame in frame_data['frames'] for value in static_metadata(frame)}
    static_fields=[json.loads(value) for value in sorted(declared)]
    static_types=sorted({value['side_data_type'] for value in static_fields})
    if static_types!=['Content light level metadata','Mastering display metadata']:
        raise AssertionError('Static mastering and content-light metadata are required')
    return dict(seconds=seconds+author_seconds,author_seconds=author_seconds,frames=count,
                hdr10plus_blocks=len(blocks),audio_samples=int(audio['duration_ts']),
                same_static_and_authored_decode=True,static_metadata=static_fields,
                audio_pcm_sha256=hashlib.sha256(pcm).hexdigest())


def compare_encoded(reference, candidate):
    result=call(['ffmpeg','-v','info','-threads','2','-i',reference,'-threads','2','-i',candidate,
                 '-lavfi','psnr','-an','-f','null','-'],120)
    field=re.search(rb'PSNR y:([\d.]+|inf) u:([\d.]+|inf) v:([\d.]+|inf) average:([\d.]+|inf)',result.stderr)
    if not field:
        raise AssertionError('Independent decoded PQ comparison did not produce a score')
    measured=dict(zip(('y','u','v','average'),(part.decode() for part in field.groups())))
    measured['passed']=float(measured['average'])>=50
    return measured


def experiment(results, reference, executable, frames, *, quick=False, force_fallback=False, precise_edges=False):
    sys.path[:0]=[str(reference),str(ROOT),str(ROOT/'tests')]
    import hdr_layers
    from test_hdr_color import CONTRACT
    expected=call(['git','show',f'{BASELINE}:hdr_layers.py']).stdout
    if expected.replace(b'\r\n',b'\n')!=Path(hdr_layers.__file__).read_bytes().replace(b'\r\n',b'\n'):
        raise ValueError('The export reference must use the frozen Phase 1 filters')
    from dataclasses import replace
    scenario=next(case for case in SCENARIOS if case.name=='uhd-mixed')
    if quick:
        scenario=replace(scenario,width=320,height=180)
    results.mkdir(parents=True,exist_ok=False)
    conditions=technical_conditions()
    with tempfile.TemporaryDirectory(prefix='compositor-',dir=results) as tmp:
        stage=Path(tmp)
        started=time.perf_counter()
        inputs,planar=write_sources(stage,scenario,None,True)
        clips=clips_for(scenario,frames)
        plan=stage/'frames.bin'
        write_plan(plan,scenario,clips,frames,precise_edges=precise_edges)
        audio=stage/'clock.wav'
        call(['ffmpeg','-v','error','-nostdin','-f','lavfi','-i',
              f'sine=frequency=577:sample_rate=48000:duration={frames/scenario.fps:.12f}',
              '-af','pan=stereo|c0=c0|c1=c0','-c:a','pcm_s16le',audio],60)
        prep_seconds=time.perf_counter()-started
        ffmpeg_output=stage/'reference.gbr'
        started=time.perf_counter()
        reference_trial(stage,scenario,clips,frames,0,planar,hdr_layers,ffmpeg_output)
        reference_composite=time.perf_counter()-started
        static=stage/'reference-static.mp4'
        reference_master=stage/'reference-hdr10plus.mp4'
        encode(ffmpeg_output,False,audio,static,scenario,frames,CONTRACT)
        control=delivery(stage,static,reference_master,scenario.fps,frames,time.perf_counter()-started)
        control['float_composite_seconds']=reference_composite

        selected='d3d11-fp32'
        failure=None
        compared=None
        pq=None
        candidate=None
        try:
            started=time.perf_counter()
            packed_output=stage/'native.rgba'
            render=native_trial(executable if not force_fallback else stage/'unavailable.exe','gpu32',
                                plan,inputs,0,8,packed_output)
            candidate_composite=time.perf_counter()-started
            comparison_start=time.perf_counter()
            compared=compare_pictures(ffmpeg_output,packed_output,scenario,frames,reference=True)
            comparison_seconds=time.perf_counter()-comparison_start
            if not compared['passed']:
                raise ValueError('The scene-linear tolerance was exceeded')
            static=stage/'native-static.mp4'
            master=stage/'native-hdr10plus.mp4'
            encode(packed_output,True,audio,static,scenario,frames,CONTRACT)
            candidate=delivery(stage,static,master,scenario.fps,frames,
                               time.perf_counter()-started-comparison_seconds)
            candidate.update(float_composite_seconds=candidate_composite,native=render,
                             independent_linear_comparison_seconds=comparison_seconds)
            if candidate['audio_pcm_sha256']!=control['audio_pcm_sha256']:
                raise AssertionError('The experimental export changed decoded PCM')
            if candidate['static_metadata']!=control['static_metadata']:
                raise AssertionError('The experimental export changed static HDR declarations')
            pq=compare_encoded(reference_master,master)
            if not pq['passed']:
                raise ValueError('The decoded PQ tolerance was exceeded')
        except (OSError,subprocess.SubprocessError,RuntimeError,ValueError,AssertionError) as error:
            selected='ffmpeg'
            failure=type(error).__name__
            (results/'fallback.log').write_text(str(error),encoding='utf-8')

        report=dict(reference=BASELINE,dimensions=[scenario.width,scenario.height],fps=scenario.fps,frames=frames,
                    conditions=conditions,ac_after=power(),source_preparation_seconds=prep_seconds,
                    checkout=call(['git','rev-parse','HEAD']).stdout.decode().strip(),
                    native_sha256=hashlib.sha256(executable.read_bytes()).hexdigest(),
                    ffmpeg=control,d3d11=candidate,scene_linear=compared,decoded_pq=pq,selected=selected,
                    precise_edges=precise_edges,forced_fallback=force_fallback,fallback_reason=failure)
        os.replace(reference_master if selected=='ffmpeg' else master,results/'verified-hdr10plus.mp4')
    (results/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report),flush=True)
    if (selected=='ffmpeg')!=force_fallback:
        raise SystemExit('The export did not select the expected backend')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('results',type=Path)
    parser.add_argument('--reference',required=True,type=Path)
    parser.add_argument('--executable',required=True,type=Path)
    parser.add_argument('--frames',type=int,default=8)
    parser.add_argument('--quick',action='store_true')
    parser.add_argument('--force-fallback',action='store_true')
    parser.add_argument('--precise-edges',action='store_true')
    args=parser.parse_args()
    if not 2<=args.frames<=12:
        parser.error('The experimental export fixture must contain 2–12 frames')
    experiment(args.results.resolve(),args.reference.resolve(),args.executable.resolve(),
               args.frames,quick=args.quick,force_fallback=args.force_fallback,precise_edges=args.precise_edges)


if __name__=='__main__':
    main()
