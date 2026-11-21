"""Exercise both 4K60 delivery profiles and record a short matched HDR authoring cost."""
import argparse
from fractions import Fraction
import json
from pathlib import Path
import sys
import time

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'benchmarks'), str(ROOT/'tests')]
from windows_session import session
from test_hdr_color import probe
from test_hdr10plus_export import command
from hdr10plus_index import SIDE_DATA


def sample(process, folder):
    workers = []
    for child in psutil.Process(process.pid).children(recursive=True):
        try:
            if child.name().lower() in ('ffmpeg.exe','ffprobe.exe'):
                workers.append((child.pid,child.memory_info().rss,sum(child.cpu_times()[:2])))
        except psutil.Error:
            continue
    footprint = 0
    for work in folder.glob('.vlogcraft_*/**/*'):
        try:
            if work.is_file():
                footprint += work.stat().st_size
        except FileNotFoundError:
            continue
    return workers, footprint


def export(page, process, results, delivery, filename):
    page.click('#exportBtn')
    page.wait_for_function("!$('startRender').disabled")
    page.select_option('#exportWorkflow',delivery)
    if delivery=='render':
        page.select_option('#colorOutput','hdr10')
    for panel in (page.locator('details').filter(has_text='Advanced encoding and color'),
                  page.locator('#colorSetup')):
        if not panel.evaluate('element=>element.open'):
            panel.locator('summary').first.click()
    page.select_option('#masteringGamut','2020')
    page.fill('#masteringMin','0.005')
    page.fill('#masteringMax','1000')
    page.fill('#maxCLL','1000')
    page.fill('#maxFALL','400')
    output=results/filename
    page.fill('#exportPath',str(output))
    start=time.monotonic()
    with page.expect_response(lambda response:response.url.endswith('/api/export')) as submitted:
        page.click('#startRender')
    assert submitted.value.ok,submitted.value.json()
    peak_rss = disk = 0
    cpu = {}
    deadline = start+130
    while time.monotonic() < deadline:
        job = page.evaluate("request('jobs')")['export']
        workers, footprint = sample(process,results)
        peak_rss=max(peak_rss,sum(item[1] for item in workers))
        disk=max(disk,footprint)
        for pid,_,seconds in workers:
            cpu[pid]=max(seconds,cpu.get(pid,0))
        if job['status'] in ('done','error','cancelled'):
            break
        time.sleep(.10)
    assert job['status']=='done',job
    deadline=time.monotonic()+3
    while list(results.glob('.vlogcraft_*')) and time.monotonic()<deadline:
        time.sleep(.05)
    assert not list(results.glob('.vlogcraft_*'))
    report={'seconds':job['elapsedSeconds'],'wall_seconds':time.monotonic()-start,
            'media_worker_peak_rss_mib':round(peak_rss/2**20,2),
            'media_worker_observed_cpu_seconds':round(sum(cpu.values()),3),
            'sampled_scratch_bytes':disk,'bytes':output.stat().st_size}
    page.locator('#exportModal .dialog-actions [data-close]').click()
    return output,report


def decoded_hashes(path):
    raw = command('ffmpeg','-nostdin','-v','error','-threads','4','-i',str(path),
                  '-map','0:v','-map','0:a','-c:v','rawvideo','-threads:v','1',
                  '-f','framemd5','-')
    return [line for line in raw.splitlines() if not line.startswith(b'#')]


def verify(path, dynamic):
    info=probe(path)
    video,audio=info['streams']
    assert (video['width'],video['height'],video['avg_frame_rate'],video['profile'],video['codec_tag_string'],
            video['pix_fmt'],video['color_primaries'],video['color_transfer'],video['color_space'],video['color_range'])==(
            3840,2160,'60/1','Main 10','hvc1','yuv420p10le','bt2020','smpte2084','bt2020nc','tv'),video
    frames=[item for item in info['frames'] if item['media_type']=='video']
    assert len(frames)==6
    for i,frame in enumerate(frames):
        assert Fraction(frame['pts'])*Fraction(video['time_base'])==Fraction(i,60)
        assert any(side['side_data_type']==SIDE_DATA for side in frame.get('side_data_list',[]))==dynamic
    assert any(side['side_data_type']=='Mastering display metadata' for side in frames[0]['side_data_list'])
    assert (audio['codec_name'],audio['channels'],audio['sample_rate'])==('aac',2,'48000'),audio
    assert Fraction(audio['duration_ts'])*Fraction(audio['time_base'])==Fraction(1,10)
    return {'frames':len(frames),'video_size':[3840,2160],'fps':60,'dynamic_metadata':dynamic,
            'video_audio_endpoint_seconds':.1}


def main(executable, results):
    results=results.resolve()
    results.mkdir(parents=True,exist_ok=True)
    video=results/'pq.mp4'
    audio=results/'tone.wav'
    command('ffmpeg','-nostdin','-v','error','-y','-f','lavfi','-i','color=c=gray:s=3840x2160:r=60:d=0.1',
            '-vf','drawbox=x=160:y=200:w=150:h=140:color=white:t=fill,setsar=1,'
                  'setparams=range=limited:color_primaries=bt2020:color_trc=smpte2084:colorspace=bt2020nc',
            '-c:v','libx265','-preset','ultrafast','-pix_fmt','yuv420p10le',
            '-x265-params','pools=2:frame-threads=1',str(video))
    command('ffmpeg','-nostdin','-v','error','-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=0.1',
            '-c:a','pcm_s16le',str(audio))
    reports={}
    with session(executable,results,offline=True) as (page,process,_,errors):
        page.evaluate("""async paths=>{
          const imported=await request('import','POST',{paths,autoProxy:false});
          if(imported.errors.length||imported.assets.length!==2)throw Error('Fixture import failed');
          state=await request('state');
          Object.assign(state.output,{width:3840,height:2160,fps:60,crf:17,preset:'ultrafast',bitrate:0});
          addAsset(imported.assets[0]);addAsset(imported.assets[1]);await flushSave();
        }""",[str(video),str(audio)])
        static,reports['static']=export(page,process,results,'render','static.mp4')
        saved=page.evaluate('JSON.stringify(state.output)')
        samsung,reports['samsung']=export(page,process,results,'samsung-hdr10plus','samsung.mp4')
        youtube,reports['youtube']=export(page,process,results,'youtube-hdr','youtube.mp4')
        assert page.evaluate('JSON.stringify(state.output)')==saved
        assert not errors,errors
    for name,path in [('static',static),('samsung',samsung),('youtube',youtube)]:
        reports[name].update(verify(path,name=='samsung'))
    assert decoded_hashes(static)==decoded_hashes(samsung)
    assert len(decoded_hashes(youtube))>=7
    reports['static_samsung_decoded_equality']=True
    (results/'verification.json').write_text(json.dumps(reports,indent=2),encoding='utf-8')
    print(json.dumps(reports))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('executable',type=Path)
    parser.add_argument('results',type=Path)
    args=parser.parse_args()
    main(args.executable,args.results)
