"""Short, matched Windows Live Layers runs with and without background proxy work."""
import argparse
import json
from pathlib import Path
import sys
import time

from studio355_live_flight import resources
from windows_session import session
from window_visibility import WindowVisibility


def trial(executable, media, output, proxy):
    with session(executable, output, offline=True) as (page, process, _, errors):
        assets = page.evaluate("""async paths=>{
          const result=await request('import','POST',{paths,autoProxy:false});
          if(result.errors.length)throw Error('Generated media import failed');
          state=await request('state');
          Object.assign(state.output,{width:3840,height:2160,fps:60});
          $('playbackEngine').value='interactive';$('previewSource').value='original';
          useProxies=false;addAsset(result.assets[0]);await flushSave();
          return result.assets.map(a=>a.id);
        }""", [str((media/f'h264-4k60-{n}.mp4').resolve()) for n in range(2)])
        page.wait_for_function("document.querySelector('#previewLayers video')?.readyState>=2")
        initial = resources(process)
        with WindowVisibility(process, 'visible') as visibility:
            if proxy:
                page.evaluate("assetId=>request('proxy','POST',{assetId})",assets[1])
            page.evaluate("""()=>{
              const v=document.querySelector('#previewLayers video');
              const counts=v.getVideoPlaybackQuality();
              window.capture={times:[],initial:counts};
              const tick=now=>{capture.times.push(now);capture.handle=v.requestVideoFrameCallback(tick)};
              capture.handle=v.requestVideoFrameCallback(tick);
            }""")
            page.click('#playBtn')
            page.wait_for_function('isPlaying')
            deadline = time.monotonic()+4
            samples = []
            while time.monotonic() < deadline:
                status = page.evaluate("async()=>({status:(await request('jobs')).proxy.status,focused:document.hasFocus()})")
                samples.append({**status, **resources(process)})
                page.wait_for_timeout(250)
            page.evaluate("stopPlayback()")
            result = page.evaluate("""()=>{
              const v=document.querySelector('#previewLayers video'),q=v.getVideoPlaybackQuality();
              v.cancelVideoFrameCallback(capture.handle);
              const t=capture.times,s=t.length;
              return {callbackCount:s,spanSeconds:s>1?(t.at(-1)-t[0])/1000:0,
                maxCallbackGapMs:Math.max(0,...t.slice(1).map((v,i)=>v-t[i])),
                decodedFrames:q.totalVideoFrames-capture.initial.totalVideoFrames,
                droppedFrames:q.droppedVideoFrames-capture.initial.droppedVideoFrames,
                source:[v.videoWidth,v.videoHeight]};
            }""")
            condition = visibility.finish()
        result.update(proxy_requested=proxy, proxy_active_samples=sum(s['status']=='rendering' for s in samples),
                      initial=initial, samples=samples, stopped=resources(process), window=condition,
                      failed=bool(errors or not condition['condition_held']), browser_errors=errors)
        if proxy and not result['proxy_active_samples']:
            result['failed'] = True
        (output/'preview.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('executable','media','results'):
        parser.add_argument(name,type=Path)
    args = parser.parse_args()
    outcomes = [trial(args.executable,args.media,args.results/label,proxy)
                for label,proxy in (('idle',False),('proxy',True))]
    print(json.dumps(outcomes),flush=True)
    sys.exit(any(result['failed'] for result in outcomes))
