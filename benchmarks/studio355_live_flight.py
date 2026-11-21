"""Matched short installed Live Layers seek and playback probes."""
import argparse
import json
from pathlib import Path
import statistics
import subprocess
import sys

import psutil

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'benchmarks'))
from windows_session import session


def resources(process):
    totals={'webviewMiB':0,'nativeMiB':0,'ffmpegProcesses':0}
    for child in psutil.Process(process.pid).children(recursive=True):
        try:
            name=child.name().lower()
            if name=='msedgewebview2.exe':
                totals['webviewMiB']+=child.memory_info().rss/2**20
            elif name=='vlogcraftnative.exe':
                totals['nativeMiB']+=child.memory_info().rss/2**20
            elif name=='ffmpeg.exe':
                totals['ffmpegProcesses']+=1
        except psutil.Error:
            continue
    return totals


def observe(executable,output,source):
    with session(executable,output,offline=True) as (page,process,_,errors):
        page.evaluate("""async path=>{
          const result=await request('import','POST',{paths:[path],autoProxy:false});
          if(result.errors.length)throw Error('Fixture import failed');
          state=await request('state');
          Object.assign(state.output,{width:3840,height:2160,fps:60});
          $('playbackEngine').value='interactive';$('previewSource').value='original';
          useProxies=false;addAsset(result.assets[0]);await flushSave();
        }""",str(source))
        page.wait_for_function("document.querySelector('#previewLayers video')?.readyState>=2",timeout=15000)
        video=page.locator('#previewLayers video')
        geometry=page.evaluate("""()=>{
          const v=document.querySelector('#previewLayers video'), stage=$('previewStage').getBoundingClientRect();
          return {source:[v.videoWidth,v.videoHeight],composition:[stage.width,stage.height],
                  physical:[Math.round(stage.width*devicePixelRatio),Math.round(stage.height*devicePixelRatio)],
                  dpr:devicePixelRatio,visibility:document.visibilityState};
        }""")
        assert geometry['source']==[3840,2160]
        before=resources(process)
        seek_times=page.evaluate("""async ()=>{
          const v=document.querySelector('#previewLayers video');
          const result=[];
          for(const target of [0.5,2,1,3,0.25,2.5]){
            result.push(await new Promise(resolve=>{
              const start=performance.now();
              let handle;
              const timeout=setTimeout(()=>{v.cancelVideoFrameCallback(handle);resolve({target,timeout:true});},3500);
              const frame=(_,metadata)=>{
                if(Math.abs(metadata.mediaTime-target)>.018){handle=v.requestVideoFrameCallback(frame);return;}
                clearTimeout(timeout);resolve({target,milliseconds:performance.now()-start,mediaTime:metadata.mediaTime});
              };
              handle=v.requestVideoFrameCallback(frame);
              seek(target);
            }));
          }
          return result;
        }""")
        page.evaluate("seek(0)")
        video.evaluate("""v=>{
          window.__flight={times:[]};
          const next=(now,meta)=>{window.__flight.times.push([now,meta.mediaTime]);window.__flight.handle=v.requestVideoFrameCallback(next)};
          window.__flight.handle=v.requestVideoFrameCallback(next);
          window.__flight.initial=v.getVideoPlaybackQuality();
        }""")
        page.click('#playBtn')
        page.wait_for_function('isPlaying')
        page.wait_for_timeout(1900)
        active=resources(process)
        page.wait_for_timeout(1900)
        page.evaluate('stopPlayback()')
        playback=video.evaluate("""v=>{
          const measured=window.__flight, quality=v.getVideoPlaybackQuality();
          v.cancelVideoFrameCallback(measured.handle);
          const times=measured.times;
          return {callbackCount:times.length,totalIncrement:quality.totalVideoFrames-measured.initial.totalVideoFrames,
            droppedIncrement:quality.droppedVideoFrames-measured.initial.droppedVideoFrames,
            callbackSpanSeconds:times.length>1?(times.at(-1)[0]-times[0][0])/1000:0,
            maxCallbackGapMs:Math.max(0,...times.slice(1).map((t,i)=>t[0]-times[i][0]))};
        }""")
        after=resources(process)
        assert not errors,errors
    successes=[row['milliseconds'] for row in seek_times if 'milliseconds' in row]
    return {'geometry':geometry,'seekSamples':seek_times,'seekMedianMs':statistics.median(successes) if successes else None,
            'seekTimeouts':len(seek_times)-len(successes),'browserPlayback':playback,
            'resources':{'before':before,'active':active,'after':after}}


def main(baseline_msi,candidate,results):
    results=results.resolve()
    results.mkdir(parents=True,exist_ok=False)
    frozen=results/'frozen'
    subprocess.run(['msiexec','/a',str(baseline_msi.resolve()),'/qn','/norestart','TARGETDIR='+str(frozen)],
                   check=True,timeout=120,creationflags=subprocess.CREATE_NO_WINDOW)
    baseline=next(frozen.rglob('VlogCraftStudio.exe'))
    source=results/'fixture.mp4'
    subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','testsrc2=s=3840x2160:r=60:d=5',
                    '-c:v','libx264','-preset','ultrafast','-threads','4','-pix_fmt','yuv420p',str(source)],
                   check=True,timeout=70,creationflags=subprocess.CREATE_NO_WINDOW)
    report={'scope':'Live Layers with one generated original, 6 seeks and under 4 seconds of playback per build. '
                    'No proxy, native audio or GPU metrics. CSS composition and physical viewport differ from source.',
            'runs':[]}
    for label,executable in [('3.5.4',baseline),('3.5.5',candidate)]:
        report['runs'].append({'version':label,**observe(executable,results/label,source)})
        (results/'comparison.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps(report))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('baseline_msi',type=Path)
    parser.add_argument('candidate',type=Path)
    parser.add_argument('results',type=Path)
    args=parser.parse_args()
    main(args.baseline_msi,args.candidate,args.results)
