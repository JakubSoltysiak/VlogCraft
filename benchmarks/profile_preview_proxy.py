"""Matched Windows Live Layers runs on originals, during encoding, and on completed proxies."""
import argparse
import json
import math
from pathlib import Path
import sys
import time

from studio355_live_flight import resources
from windows_session import session
from window_visibility import WindowVisibility


def trial(executable, media, output, proxy, proxy_source=None, *, completed=False, playback_source=None, seconds=4):
    with session(executable, output, offline=True) as (page, process, _, errors):
        assets = page.evaluate("""async paths=>{
          const result=await request('import','POST',{paths,autoProxy:false});
          if(result.errors.length)throw Error('Generated media import failed');
          state=await request('state');
          Object.assign(state.output,{width:3840,height:2160,fps:60});
          $('playbackEngine').value='interactive';$('previewSource').value='original';
          useProxies=false;addAsset(result.assets[0]);await flushSave();
          return result.assets.map(({id,width,height,duration})=>({id,width,height,duration}));
        }""", [str((playback_source or media/'h264-4k60-0.mp4').resolve()),
               str((proxy_source or media/'h264-4k60-1.mp4').resolve())])
        first, other = assets
        if not math.isfinite(seconds) or not 0 < seconds <= min(180, first['duration'] - .5):
            raise ValueError('Choose an observation of at most 180 seconds ending before the source stops')
        page.wait_for_function("document.querySelector('#previewLayers video')?.readyState>=2")
        if completed:
            page.evaluate("asset=>request('proxy','POST',{assetId:asset.id})",first)
            page.wait_for_function("id=>readyProxies.has(id)",arg=first['id'],timeout=300000)
            page.select_option('#previewSource','auto')
            # The server also accepts proxy=1 when falling back to an original. Require actual decoder dimensions.
            page.wait_for_function("""id=>{
              const v=document.querySelector('#previewLayers video');
              if (!v?.currentSrc || v.readyState<2) return false;
              const url=new URL(v.currentSrc);
              return url.pathname==='/media/'+id && url.searchParams.get('proxy')==='1'
                 && v.videoWidth===1280 && v.videoHeight===720;
            }""",arg=first['id'],timeout=30000)
        initial = resources(process)
        with WindowVisibility(process, 'visible') as visibility:
            if proxy and not proxy_source:
                page.evaluate("assetId=>request('proxy','POST',{assetId})",other['id'])
            page.evaluate("""()=>{
              const v=document.querySelector('#previewLayers video');
              const counts=v.getVideoPlaybackQuality();
              window.capture={times:[],initial:counts};
              const tick=now=>{capture.times.push(now);capture.handle=v.requestVideoFrameCallback(tick)};
              capture.handle=v.requestVideoFrameCallback(tick);
            }""")
            page.click('#playBtn')
            page.wait_for_function('isPlaying')
            if proxy and proxy_source:
                page.evaluate("assetId=>request('proxy','POST',{assetId})",other['id'])
            deadline = time.monotonic()+seconds
            samples = []
            while time.monotonic() < deadline:
                status = page.evaluate("async()=>({status:(await request('jobs')).proxy.status,focused:document.hasFocus()})")
                samples.append({**status, **resources(process)})
                page.wait_for_timeout(250)
            page.evaluate("stopPlayback()")
            result = page.evaluate("""id=>{
              const v=document.querySelector('#previewLayers video'),q=v.getVideoPlaybackQuality();
              v.cancelVideoFrameCallback(capture.handle);
              const t=capture.times,s=t.length,url=new URL(v.currentSrc);
              const gaps=t.slice(1).map((v,i)=>v-t[i]).sort((a,b)=>a-b);
              const percentile=p=>gaps.length?gaps[Math.ceil(gaps.length*p)-1]:null;
              const box=$('previewStage').getBoundingClientRect();
              return {callbackCount:s,spanSeconds:s>1?(t.at(-1)-t[0])/1000:0,
                maxCallbackGapMs:percentile(1),p95CallbackGapMs:percentile(.95),p99CallbackGapMs:percentile(.99),
                decodedFrames:q.totalVideoFrames-capture.initial.totalVideoFrames,
                droppedFrames:q.droppedVideoFrames-capture.initial.droppedVideoFrames,
                source:[v.videoWidth,v.videoHeight],sourceUrlMatchesAsset:url.pathname==='/media/'+id,
                proxyQuery:url.searchParams.get('proxy'),composition:[state.output.width,state.output.height],
                physicalStage:[Math.round(box.width*devicePixelRatio),Math.round(box.height*devicePixelRatio)],
                dpr:devicePixelRatio};
            }""",first['id'])
            condition = visibility.finish()
            if proxy and page.evaluate("async()=>(await request('jobs')).proxy.status==='rendering'"):
                page.evaluate("request('job/cancel','POST',{job:'proxy'})")
                page.wait_for_function("async()=>(await request('jobs')).proxy.status!=='rendering'",timeout=15000)
        result.update(proxy_requested=proxy, proxy_active_samples=sum(s['status']=='rendering' for s in samples),
                      initial=initial, samples=samples, stopped=resources(process), window=condition,
                      failed=bool(errors or not condition['condition_held']), browser_errors=errors)
        dimensions = [first['width'],first['height']]
        result.update(originalDimensions=dimensions,completedProxy=completed,observationSeconds=seconds,
                      activeProxySampleFraction=result['proxy_active_samples']/max(1,len(samples)))
        if (proxy and not result['proxy_active_samples'] or not proxy and result['proxy_active_samples']
                or not result['sourceUrlMatchesAsset'] or result['proxyQuery'] != ('1' if completed else '0')
                or result['source'] != ([1280,720] if completed else dimensions) or result['callbackCount'] < 2):
            result['failed'] = True
        (output/'preview.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('executable','media','results'):
        parser.add_argument(name,type=Path)
    parser.add_argument('--proxy-source',type=Path,help='Run only the contention arm with a longer generated source')
    parser.add_argument('--case',choices=('idle','active','completed'),help='Run one explicit arm in a fresh project')
    parser.add_argument('--playback-source',type=Path,help='Generated landscape 16:9 SDR video shared by all arms')
    parser.add_argument('--seconds',type=float,default=4,help='Observation duration, below playback source duration')
    args = parser.parse_args()
    arms = (('proxy',True),) if args.proxy_source else (('idle',False),('proxy',True))
    if args.case:
        arms = ((args.case,args.case=='active'),)
    outcomes = [trial(args.executable,args.media,args.results/label,proxy,args.proxy_source,
                      completed=label=='completed',playback_source=args.playback_source,seconds=args.seconds)
                for label,proxy in arms]
    print(json.dumps(outcomes),flush=True)
    sys.exit(any(result['failed'] for result in outcomes))
