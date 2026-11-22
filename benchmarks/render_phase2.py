"""Local rendering lab: immutable Phase 1 FFmpeg filters, native CPU and D3D11."""
import argparse
from dataclasses import dataclass, replace
import hashlib
import json
import math
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile
import time

import numpy as np
import psutil

if __package__:
    from .conditions import Conditions
else:
    from conditions import Conditions


BASELINE = '045da0a6b3d8d956d07c075a6c0e73f6878a2d9f'
ROOT = Path(__file__).resolve().parents[1]
REFERENCE_POLICY = dict(max_rgb=.05, rmse_rgb=.002, max_alpha=.003)
NATIVE_MODES = {'scalar','simd','gpu32','gpu16','warp32'}
ENDURANCE_MODES = {'gpu32','gpu16'}
QUALITY_BLOCK_PIXELS = 1 << 20


@dataclass(frozen=True)
class Scenario:
    name: str
    width: int
    height: int
    fps: int = 60
    layers: int = 1
    motion: bool = False
    opacity: bool = False
    mask: bool = False
    dissolve: bool = False


SCENARIOS = (
    Scenario('1080-transform',1920,1080,motion=True),
    Scenario('uhd-single',3840,2160),
    Scenario('uhd-overlap',3840,2160,layers=3),
    Scenario('uhd-photo',3840,2160,motion=True),
    Scenario('uhd-geometry',3840,2160,motion=True,layers=2),
    Scenario('uhd-opacity',3840,2160,opacity=True,layers=2),
    Scenario('uhd-mask',3840,2160,motion=True,mask=True,layers=2),
    Scenario('uhd-dissolve',3840,2160,dissolve=True,layers=2),
    Scenario('uhd-mixed',3840,2160,motion=True,opacity=True,mask=True,layers=3),
    Scenario('uhd-hdr',3840,2160,motion=True,opacity=True,dissolve=True,layers=3),
    Scenario('uhd-sustained',3840,2160,motion=True,opacity=True,mask=True,layers=3),
    Scenario('uhd120',3840,2160,fps=120,motion=True),
    Scenario('8k60',7680,4320,motion=True),
    Scenario('edge-half',320,180),
)


def call(args, timeout=180):
    return subprocess.run([str(arg) for arg in args], timeout=timeout, capture_output=True,
                          creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0), check=True)


def compile_native(output, compiler):
    output.parent.mkdir(parents=True,exist_ok=True)
    call([compiler,'c++','-std=c++17','-O3','-fno-vectorize','-fno-slp-vectorize',
          '-ffp-contract=off','-target','x86_64-windows-gnu','-municode',
          ROOT/'experiments/render_phase2/main.cpp','-ld3d11','-ld3dcompiler_47','-lpsapi','-o',output],300)


def power():
    battery = psutil.sensors_battery()
    return None if battery is None else battery.power_plugged


def technical_conditions():
    frequency=psutil.cpu_freq()
    return dict(ac_power=power(),logical_processors=psutil.cpu_count(),
                cpu_frequency_mhz=frequency.current if frequency else None,
                cpu_frequency_source='Windows OS-reported value',
                board_temperature_c=None,gpu_frequency_mhz=None)


def source_picture(scenario, index, camera=None):
    """Generate chromatic ramps, HDR highlights, alpha edges and subpixel structure."""
    w,h = scenario.width,scenario.height
    if camera and index==0:
        data=call(['ffmpeg','-v','error','-noautorotate','-threads','1','-i',camera,
                   '-vf','zscale=threads=1:p=2020:t=linear:m=gbr:r=full:npl=100,format=gbrpf32le,'
                         f'zscale=threads=1:w={w}:h={h}:filter=bilinear',
                   '-frames:v','1','-c:v','rawvideo','-threads:v','1','-f','rawvideo','-'],90).stdout
        picture=np.ones((h,w,4),dtype='<f4')
        g,b,r=np.frombuffer(data,dtype='<f4').reshape(3,h,w)
        picture[...,:3]=np.stack([r,g,b],axis=-1)
        return picture
    x=np.arange(w,dtype='float32')[None,:]/w
    y=np.arange(h,dtype='float32')[:,None]/h
    a=np.ones((h,w),dtype='float32') if index==0 else np.clip((x-.08)*(1.23+index*.2)+y*.45,0,1)
    highlight=((x-.63)**2+(y-.38)**2<.021).astype('float32')
    picture=np.empty((h,w,4),dtype='<f4')
    picture[...,0]=(.05+.32*x+.1*y+(9-index)*highlight)*a
    picture[...,1]=(.04+.11*x+(.40-index*.07)*y+2.7*highlight)*a
    picture[...,2]=(.02+(.13+index*.2)*x+.22*y+.8*highlight)*a
    picture[...,3]=a
    return picture


def clips_for(scenario, frames):
    end=max(1,frames-1)/scenario.fps
    clips=[]
    for n in range(scenario.layers):
        clip=dict(start=0,position=0,speed=1,scale=1,rotation=0,x=0,y=0,
                  opacity=1 if n==0 else .76,mask='none',maskRadius=.5,feather=.14,keys={})
        if scenario.motion and (n==0 or n==scenario.layers-1):
            clip.update(scale=1.025,rotation=3.15+n,x=-.027,y=.032)
            for prop,target in dict(scale=1.15,rotation=-7.845,x=.045,y=-.053).items():
                clip['keys'][prop]=[
                    dict(time=0,value=clip[prop],mode='linear'),dict(time=end,value=target,mode='linear')]
        if scenario.opacity and n==scenario.layers-1:
            clip['keys']['opacity']=[dict(time=0,value=.83,mode='linear'),dict(time=end,value=.42,mode='linear')]
        if scenario.mask and n==scenario.layers-1:
            clip.update(mask='ellipse' if n%2 else 'rectangle',maskRadius=.42)
            clip['keys']['maskRadius']=[dict(time=0,value=.42,mode='linear'),dict(time=end,value=.34,mode='linear')]
        if scenario.name=='edge-half':
            edge=(.5+1e-9)/scenario.width
            clip['keys']['x']=[dict(time=0,value=edge,mode='linear'),
                                dict(time=end,value=-edge,mode='linear')]
        clips.append(clip)
    return clips


def value_at(clip, prop, position):
    keys=clip['keys'].get(prop)
    if not keys:
        return clip[prop]
    start,end=keys
    return start['value']+(end['value']-start['value'])*position


def write_plan(path, scenario, clips, frames, indices=None, *, precise_edges=False,
               source_slots=None, dissolve_window=None):
    indices=list(range(frames)) if indices is None else indices
    source_slots=source_slots or [(n,) for n in range(scenario.layers)]
    precise=[]
    with path.open('wb') as file:
        images=(max(max(slots) for slots in source_slots)+1)|(0x80000000 if precise_edges else 0)
        file.write(struct.pack('<4I',scenario.width,scenario.height,images,len(indices)))
        for i in indices:
            fraction=i/max(1,frames-1)
            amount=fraction if scenario.dissolve else -1
            if dissolve_window:
                first,last=dissolve_window
                amount=min(1.,max(0.,(i-first)/max(1,last-first)))
            file.write(struct.pack('<3If',scenario.width,scenario.height,scenario.layers,amount))
            for n,clip in enumerate(clips):
                angle=math.radians(value_at(clip,'rotation',fraction))
                geometry=(value_at(clip,'scale',fraction),math.cos(angle),math.sin(angle),
                          value_at(clip,'x',fraction),value_at(clip,'y',fraction))
                if precise_edges:
                    precise.append(geometry)
                slots=source_slots[n]
                file.write(struct.pack('<8f4I',*geometry,value_at(clip,'opacity',fraction),
                    value_at(clip,'maskRadius',fraction),clip['feather'],slots[i%len(slots)],
                    ('none','ellipse','rectangle').index(clip['mask']),0,0))
            file.write(bytes(48*(3-len(clips))))
            if precise_edges:
                precise.extend([(1.,1.,0.,0.,0.)]*(3-len(clips)))
        for geometry in precise:
            file.write(struct.pack('<5d',*geometry))


def write_sources(directory, scenario, camera, reference):
    packed=directory/'sources.rgba'
    planar=[]
    with packed.open('wb') as output:
        for n in range(scenario.layers):
            picture=source_picture(scenario,n,camera)
            picture.tofile(output)
            if reference:
                path=directory/f'input-{n}.gbrap'
                with path.open('wb') as stream:
                    for channel in (1,2,0,3):
                        np.ascontiguousarray(picture[...,channel]).tofile(stream)
                planar.append(path)
    return packed,planar


def ffmpeg_graph(scenario, clips, frames, layers, warmup=0):
    w,h,r=scenario.width,scenario.height,scenario.fps
    black=layers.luma_linear('709','709','709','limited')
    filters=[f'color=black:s={w}x{h}:r={r},{black},format=gbrpf32le,bench=start[base]']
    back='base'
    for n,clip in enumerate(clips):
        chain=f'[{n}:v]setsar=1,setparams=alpha_mode=premultiplied:colorspace=gbr:range=full'
        if clip['mask']!='none':
            chain+=','+layers.soft_mask(clip,0)
        if layers.uses_geometry(clip):
            chain+=','+layers.transform(clip,0)
        alpha=layers.parameter(clip,'opacity',1,0)
        chain+=',unpremultiply=inplace=1,'+layers.matte_expression(clip,0,alpha,1)
        layers.picture_alpha(filters,chain+f'[raw{n}];[raw{n}]',f'layer{n}',n)
        if scenario.dissolve and n==0:
            filters.append(f'[{back}]split=2[bottom][alternate]')
            back='bottom'
        if scenario.dissolve and n==1:
            back='alternate'
        filters.append(f'[{back}][layer{n}][layer{n}mask]maskedmerge[result{n}]')
        back=f'result{n}'
        if scenario.dissolve and n==1:
            weight=f'clip(T*{r}/{max(1,frames-1)},0,1)'
            filters.append(f"[result0][result1]blend=all_expr='A*(1-({weight}))+B*({weight})'[mixed]")
            back='mixed'
    filters.append(f'[{back}]trim=end_frame={frames+warmup},bench=stop[output]')
    return ';\n'.join(filters)


def distribution(values):
    if not values:
        return None
    return {name:round(float(np.percentile(values,p)),6) for name,p in
            (('median',50),('p95',95),('p99',99),('maximum',100))}


def reference_trial(folder, scenario, clips, frames, warmup, planar, layers, output=None):
    graph=folder/'ffmpeg-graph.txt'
    graph.write_text(ffmpeg_graph(scenario,clips,frames,layers,warmup),encoding='utf-8')
    command=['ffmpeg','-hide_banner','-nostats','-v','info','-benchmark','-filter_complex_threads','4',
             '-noauto_conversion_filters','-nostdin','-progress','pipe:1']
    for path in planar:
        command+=['-stream_loop','-1','-f','rawvideo','-video_size',f'{scenario.width}x{scenario.height}',
                  '-pixel_format','gbrapf32le','-framerate',str(scenario.fps),'-i',path]
    command+=['-/filter_complex',graph,'-map','[output]','-frames:v',str(frames+warmup),'-an']
    command+=['-c:v','rawvideo','-threads:v','1','-f','rawvideo',output] if output else [
        '-c:v','wrapped_avframe','-f','null','-']
    start=time.perf_counter()
    result=call(command,240)
    wall=time.perf_counter()-start
    progress=re.split(rb'\r?\n',result.stdout.strip())
    counts=[line.split(b'=',1)[1].strip() for line in progress if line.startswith(b'frame=')]
    if not counts or counts[-1]!=str(frames+warmup).encode() or progress[-1]!=b'progress=end':
        raise ValueError('FFmpeg did not finish with the requested output picture count')
    values=[1000*float(v) for v in re.findall(rb'\bt:([0-9.]+) avg:',result.stderr)]
    if len(values)!=frames+warmup:
        raise ValueError('FFmpeg did not report one processing sample per picture')
    match=re.search(rb'utime=([\d.]+)s stime=([\d.]+)s rtime=([\d.]+)s',result.stderr)
    memory=re.search(rb'maxrss=(\d+)KiB',result.stderr)
    return dict(wall_ms=1000*wall,frames=frames+warmup,measurement_frames=len(values[warmup:]),
                fps=(frames+warmup)/wall,frame_ms=distribution(values[warmup:]),
                cpu_ms=1000*sum(map(float,match.groups()[:2])) if match else None,
                peak_rss_bytes=int(memory[1])*1024 if memory else None)


def native_trial(executable, mode, plan, source, warmup, workers, output=None, uploads=False):
    process=call([executable,mode,plan,source,output or '-',warmup,workers,int(uploads)],240)
    data=json.loads(process.stdout)
    samples=data.pop('samples')
    data.update(frames=len(samples),fps=1000*len(samples)/data['wall_ms'])
    for name in ('work_ms','upload_ms','dispatch_ms','gpu_ms','readback_ms','write_ms'):
        data[name]=distribution([sample[name] for sample in samples if sample[name] is not None])
    return data


def compare_pictures(path, candidate, scenario, frames, *, reference=False, half=False):
    pixels=scenario.width*scenario.height
    max_rgb=max_alpha=total=abs_total=mask_edges=edge_error=0
    max_relative_highlight=max_shadow=0
    expected_reference=frames*pixels*(12 if reference else 16)
    expected_candidate=frames*pixels*(8 if half else 16)
    if path.stat().st_size!=expected_reference or candidate.stat().st_size!=expected_candidate:
        raise ValueError('The composed picture buffer does not match the declared shape and frame count')
    input_shape=(frames,3,pixels) if reference else (frames,pixels,4)
    baseline=np.memmap(path,dtype='<f4',mode='r',shape=input_shape)
    tested=np.memmap(candidate,dtype='<f2' if half else '<f4',mode='r',shape=(frames,pixels,4))
    for n in range(frames):
        for start in range(0,pixels,QUALITY_BLOCK_PIXELS):
            block=slice(start,start+QUALITY_BLOCK_PIXELS)
            prior=baseline[n,:,block][[2,0,1]].T if reference else baseline[n,block,:3]
            after=tested[n,block,:3].astype('float32')
            if not np.isfinite(prior).all() or not np.isfinite(after).all():
                raise ValueError('Non-finite linear RGB in composed pictures')
            delta=np.abs(after-prior)
            max_rgb=max(max_rgb,float(delta.max()))
            total+=float(np.sum(np.square(delta),dtype='float64'))
            abs_total+=float(np.sum(delta,dtype='float64'))
            highlight=prior>=1
            shadow=np.abs(prior)<.02
            if highlight.any():
                max_relative_highlight=max(max_relative_highlight,float((delta[highlight]/prior[highlight]).max()))
            if shadow.any():
                max_shadow=max(max_shadow,float(delta[shadow].max()))
            if not reference:
                alpha=baseline[n,block,3]
                delta_alpha=np.abs(tested[n,block,3].astype('float32')-alpha)
                if not np.isfinite(delta_alpha).all():
                    raise ValueError('Non-finite alpha in composed pictures')
                max_alpha=max(max_alpha,float(delta_alpha.max()))
                edge=(alpha>.01)&(alpha<.99)
                mask_edges+=np.count_nonzero(edge)
                edge_error+=float(np.sum(delta_alpha[edge],dtype='float64'))
    rmse=math.sqrt(total/(frames*pixels*3))
    return dict(max_rgb=max_rgb,mean_abs_rgb=abs_total/(frames*pixels*3),rmse_rgb=rmse,
                psnr_db=20*math.log10(10/rmse) if rmse else None,max_alpha=None if reference else max_alpha,
                max_relative_highlight_error=max_relative_highlight,max_shadow_error=max_shadow,
                mean_edge_alpha_error=edge_error/mask_edges if mask_edges else None,
                passed=max_rgb<=REFERENCE_POLICY['max_rgb'] and rmse<=REFERENCE_POLICY['rmse_rgb']
                    and max_alpha<=REFERENCE_POLICY['max_alpha'])


def trial_suite(args, scenario, layers):
    rows={}
    with tempfile.TemporaryDirectory(prefix=scenario.name+'-',dir=args.results) as temp:
        folder=Path(temp)
        frames=3600 if scenario.name=='uhd-sustained' else args.frames
        clips=clips_for(scenario,frames)
        modes=args.modes.split(',')
        if scenario.name=='uhd-sustained':
            # The endurance arm consumes resident native inputs only.
            modes=[mode for mode in modes if mode in ENDURANCE_MODES]
        sources,planar=write_sources(folder,scenario,args.camera,'ffmpeg' in modes)
        plan=folder/'plan.bin'
        write_plan(plan,scenario,clips,frames,precise_edges=args.precise_edges)
        for mode in modes:
            attempts=[]
            repeat=0 if args.reference_once and mode=='ffmpeg' else args.repeat
            for attempt in range(1,repeat+1):
                before=power()
                try:
                    run=reference_trial(folder,scenario,clips,frames,args.warmup,planar,layers) if mode=='ffmpeg' else native_trial(
                        args.executable,mode,plan,sources,args.warmup,args.workers)
                    expected=frames+args.warmup if mode=='ffmpeg' else frames
                    if run['frames']!=expected:
                        raise ValueError('The renderer processed a different picture count')
                except (OSError,subprocess.SubprocessError,ValueError) as error:
                    run={'failure':type(error).__name__}
                    if getattr(error,'stderr',None):
                        (args.results/f'{scenario.name}-{mode}-attempt-{attempt}-failure.log').write_bytes(error.stderr)
                attempts.append(dict(run,ac_before=before,ac_after=power()))
                print(json.dumps({'scenario':scenario.name,'mode':mode,'attempt':attempts[-1]}),flush=True)
            rows[mode]=attempts

        quality={}
        if not args.skip_quality and frames!=3600:
            # Sample every measured frame in normal runs. Bound the 8K disk footprint.
            count=min(frames,3) if scenario.width>=7680 else frames
            outputs={}
            if count!=frames:
                clips=clips_for(scenario,count)
                write_plan(plan,scenario,clips,count,precise_edges=args.precise_edges)
            for mode in modes:
                if not any('failure' not in run for run in rows[mode]) and not (args.reference_once and mode=='ffmpeg'):
                    continue
                output=folder/(mode+'.raw')
                try:
                    if mode=='ffmpeg':
                        reference_trial(folder,scenario,clips,count,0,planar,layers,output)
                    else:
                        quality[mode+'_readback']=native_trial(args.executable,mode,plan,sources,0,args.workers,output)
                    outputs[mode]=output
                except (OSError,subprocess.SubprocessError,ValueError) as error:
                    quality[mode]={'failure':'output_capture','error_type':type(error).__name__}
                    if getattr(error,'stderr',None):
                        (args.results/f'{scenario.name}-{mode}-capture.log').write_bytes(error.stderr)
            for mode,output in outputs.items():
                for reference in ('ffmpeg','scalar'):
                    if reference in outputs and mode not in ('ffmpeg',reference):
                        name=mode+'_vs_'+reference
                        try:
                            quality[name]=compare_pictures(outputs[reference],output,scenario,count,
                                                           reference=reference=='ffmpeg',half=mode=='gpu16')
                        except (OSError,ValueError) as error:
                            quality[name]={'passed':False,'failure':type(error).__name__}
            if args.transfers and 'gpu32' in outputs:
                quality['gpu32_upload_and_readback']=native_trial(args.executable,'gpu32',plan,sources,0,
                    args.workers,folder/'streamed.raw',uploads=True)
    return {'scenario':scenario.__dict__,'frames_requested':frames,'accepted_power':'AC' if args.require_ac else 'recorded',
            'runs':rows,'quality':quality}


def validate_modes(names,modes,assert_quality,skip_quality):
    if len(set(modes))!=len(modes) or not set(modes)<=(NATIVE_MODES|{'ffmpeg'}):
        raise ValueError('Select distinct known rendering modes')
    if 'uhd-sustained' in names and not ENDURANCE_MODES.intersection(modes):
        raise ValueError('Resident endurance requires a hardware D3D11 mode')
    if assert_quality and (skip_quality or 'uhd-sustained' in names or 'ffmpeg' not in modes or
                           not NATIVE_MODES.intersection(modes)):
        raise ValueError('Strict picture verification requires held pictures from FFmpeg and a native mode')


def all_ac(report):
    checkpoints=[report['conditions_start']['ac_power'],report.get('conditions_last',{}).get('ac_power')]
    checkpoints.extend(row['ac_power'] for row in report['observed_conditions']['samples'])
    checkpoints.extend(run[key] for result in report['results'] for runs in result['runs'].values()
                       for run in runs for key in ('ac_before','ac_after'))
    return all(value is True for value in checkpoints)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('results',type=Path)
    parser.add_argument('--reference',type=Path)
    parser.add_argument('--executable',type=Path)
    parser.add_argument('--compiler',type=Path)
    parser.add_argument('--cases',default='1080-transform,uhd-mask')
    parser.add_argument('--modes',default='ffmpeg,scalar,simd,gpu32,gpu16')
    parser.add_argument('--frames',type=int,default=4)
    parser.add_argument('--repeat',type=int,default=3)
    parser.add_argument('--warmup',type=int,default=1)
    parser.add_argument('--workers',type=int,default=8)
    parser.add_argument('--quick',action='store_true')
    parser.add_argument('--skip-quality',action='store_true')
    parser.add_argument('--assert-quality',action='store_true',help='Require every requested backend comparison to pass')
    parser.add_argument('--require-ac',action='store_true')
    parser.add_argument('--transfers',action='store_true')
    parser.add_argument('--precise-edges',action='store_true')
    parser.add_argument('--reference-once',action='store_true',
                        help='Capture independent FFmpeg pictures and reuse previously timed FFmpeg controls')
    parser.add_argument('--camera',type=Path)
    args=parser.parse_args()
    if args.require_ac and not power():
        parser.error('AC power is required for this qualification')
    if args.compiler and not args.executable:
        args.executable=args.results.resolve()/'VlogCraftRenderLab.exe'
    if not args.executable or not args.reference:
        parser.error('Provide the native executable or compiler and the extracted Phase 1 source')
    if not 2<=args.frames<=24 or not 1<=args.repeat<=10 or not 0<=args.warmup<=5:
        parser.error('Invalid bounded trial dimensions')
    names=args.cases.split(',')
    if not set(names)<={case.name for case in SCENARIOS}:
        parser.error('Unknown scenario')
    try:
        validate_modes(names,args.modes.split(','),args.assert_quality,args.skip_quality)
    except ValueError as error:
        parser.error(str(error))
    args.results=args.results.resolve()
    args.results.mkdir(parents=True,exist_ok=False)
    if args.compiler:
        compile_native(args.executable,args.compiler)
    reference=args.reference.resolve()
    for name in ('hdr_layers.py','animation.py'):
        expected=call(['git','show',f'{BASELINE}:{name}']).stdout
        if expected.replace(b'\r\n',b'\n')!=(reference/name).read_bytes().replace(b'\r\n',b'\n'):
            raise ValueError('The selected filter source differs from the frozen checkpoint')
    sys.path.insert(0,str(reference))
    import hdr_layers as layers

    revision=call(['git','rev-parse','HEAD']).stdout.decode().strip()
    report=dict(reference=BASELINE,checkout=revision,native_sha256=hashlib.sha256(args.executable.read_bytes()).hexdigest(),
                reference_filter_sha256=hashlib.sha256(Path(layers.__file__).read_bytes()).hexdigest(),
                benchmark_driver_sha256=hashlib.sha256(Path(__file__).read_bytes().replace(b'\r\n',b'\n')).hexdigest(),
                policy=REFERENCE_POLICY,repeat=args.repeat,workers=args.workers,precise_edges=args.precise_edges,
                conditions_start=technical_conditions(),results=[])
    conditions=Conditions()
    try:
        for name in names:
            case=next(s for s in SCENARIOS if s.name==name)
            if args.quick:
                case=replace(case,width=320,height=180)
            report['results'].append(trial_suite(args,case,layers))
            report['conditions_last']=technical_conditions()
            (args.results/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    finally:
        report['observed_conditions']=conditions.finish()
        (args.results/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    if args.require_ac and not all_ac(report):
        raise SystemExit('AC power was not continuous across the qualification observations')
    if args.assert_quality:
        for result in report['results']:
            for mode,runs in result['runs'].items():
                if any('failure' in run for run in runs):
                    raise SystemExit(f"{result['scenario']['name']} {mode} execution failed")
                if mode!='ffmpeg' and not result['quality'].get(mode+'_vs_ffmpeg',{}).get('passed'):
                    raise SystemExit(f"{result['scenario']['name']} {mode} picture comparison failed")


if __name__=='__main__':
    main()
