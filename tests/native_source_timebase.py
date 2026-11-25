"""Verify physical native held pictures around a boundary expressed in different rational units."""
import argparse
from bisect import bisect_right
from fractions import Fraction
import json
import os
from pathlib import Path
import struct
import subprocess


def qualify(worker, output):
    worker = worker.resolve()
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    source = output / 'vfr.mkv'
    # Red frames at 0, 100, 200, 300 ms. The first blue frame occurs at 500 ms.
    filters = "drawbox=t=fill:color=blue:enable='gte(n,4)',settb=expr=1/1000,setpts='100*N+100*gte(N,4)'"
    subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','color=red:s=160x96:r=10:d=0.8',
                    '-vf',filters,'-c:v','libx264','-preset','ultrafast','-g','4','-bf','0',
                    '-pix_fmt','yuv420p','-colorspace','bt709','-color_primaries','bt709','-color_trc','bt709',
                    '-enc_time_base','1:1000','-fps_mode','vfr',str(source)],check=True,timeout=30)
    probe = subprocess.run(['ffprobe','-v','error','-select_streams','v','-show_entries',
                            'stream=time_base:frame=best_effort_timestamp','-of','json',str(source)],
                           check=True,capture_output=True,timeout=30)
    stream = json.loads(probe.stdout)
    base = Fraction(stream['streams'][0]['time_base'])
    stamps = [int(frame['best_effort_timestamp']) for frame in stream['frames']]
    assert base == Fraction(1,1000) and stamps == [0,100,200,300,500,600,700,800]
    samples = []
    env = os.environ.copy()
    env.pop('VLOGCRAFT_NATIVE_TRACE_FILE',None)
    def render(name, clips):
        test = output / name
        test.mkdir()
        plan = test / 'input.plan'
        plan.write_text(
            f'VLOGCRAFT_NATIVE 1\nRATE 60 1\nCANVAS 160 96\nEND {len(clips)}\nCOLOR SDR\nSOURCE a\t{source}\n'
            + ''.join(f'CLIP c{i} a {i} {i+1} {start} 1 {den} 1 1 0 0 1 0 1 0 0 0 0 {end}\n'
                      for i,(start,den,end) in enumerate(clips)),encoding='utf8')
        driver = subprocess.run([worker,'--plan',plan,'--offscreen','--frames',str(len(clips)),'--capture',test/'picture'],
                                env=env,capture_output=True,timeout=30)
        (test/'worker.log').write_bytes(driver.stdout+driver.stderr)
        driver.check_returncode()
        closed = json.loads(driver.stdout.decode().splitlines()[-1])
        selected, = closed['selected']
        colors = [struct.unpack_from('<eeee',(test/f'picture-{i}.rgba16f').read_bytes(),(48*160+80)*8)
                  for i in range(len(clips))]
        return selected,colors

    for tick in (999,1000,1001):
        selected,(rgb,) = render(str(tick),[(tick,2000,tick+33)])
        expected_tick = Fraction(tick,2000) // base
        expected_pts = stamps[bisect_right(stamps,expected_tick)-1]
        expected_channel = 0 if tick<1000 else 2
        row = dict(plan_tick=tick,expected_stream_tick=expected_tick,worker_tick=selected['target_tick'],
                   expected_pts=expected_pts,worker_pts=selected['pts'],
                   center_color_matches=rgb[expected_channel]>rgb[2-expected_channel]+.3)
        samples.append(row)
    # Adjacent clips resume the same file at 400 ms after showing its 500 ms blue frame.
    # Their end/start differ by just one *rounded* unit of the incoming coarse source base.
    # Reusing already advanced decoder state here would display the previous blue image.
    selected,(blue,red) = render('overlap',[(1000,2000,1033),(4,10,5)])
    backwards = dict(selected_pts=selected['pts'],target_tick=selected['target_tick'],
                     colors_match=blue[2]>blue[0]+.3 and red[0]>red[2]+.3)
    passed = (all(row['worker_tick']==row['expected_stream_tick'] and row['worker_pts']==row['expected_pts']
                  and row['center_color_matches'] for row in samples)
              and backwards==dict(selected_pts=300,target_tick=400,colors_match=True))
    receipt = {'passed':passed,'source_timebase':'1/1000','plan_timebase':'1/2000','independent_pts':stamps,
               'samples':samples,'adjacent_backwards_boundary':backwards,
               'scope':'Local generated VFR fixture, D3D11 offscreen, actual FP16 readback'}
    (output/'verification.json').write_text(json.dumps(receipt,indent=2),encoding='utf8')
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('worker',type=Path)
    parser.add_argument('output',type=Path)
    args = parser.parse_args()
    result = qualify(args.worker,args.output)
    print(json.dumps(result))
    raise SystemExit(not result['passed'])
