"""Exercise native timeline ruler drag in a packaged Windows editor."""
import argparse
import ctypes
import json
from pathlib import Path
from statistics import median
import time

from conditions import Conditions
from native_playback import SETUP
from studio355_live_flight import resources
from windows_session import session
from window_visibility import WindowVisibility


def distribution(values):
    if not values:
        return None
    order = sorted(values)
    return {'count':len(order),'median':median(order),'p95':order[int(.95*(len(order)-1))],
            'maximum':order[-1]}


OBSERVE = """() => {
  const originalSeek=seek,originalRequest=request,originalFetch=window.fetch;
  const trace=window.scrubTrace={uiMs:[],requested:0,audioFetches:0,pointerUp:null,upFrame:null,afterUp:[]};
  trace.checkpointStart=recoverySequence;
  seek=(...args)=>{
    const before=performance.now();const result=originalSeek(...args);
    trace.uiMs.push(performance.now()-before);return result;
  };
  request=(...args)=>{
    if(args[0]==='native/seek') trace.requested++;
    return originalRequest(...args);
  };
  window.fetch=(...args)=>{
    if(String(args[0]).startsWith('api/native/audio?'))trace.audioFetches++;
    return originalFetch(...args);
  };
  const watch=now=>{
    if(trace.pointerUp!==null && trace.afterUp.length<150)trace.afterUp.push([now-trace.pointerUp,frameIndex(playhead)]);
    trace.raf=requestAnimationFrame(watch);
  };
  trace.raf=requestAnimationFrame(watch);
  window.addEventListener('pointerup',event=>{
    trace.pointerUp=performance.now();
    const ruler=document.querySelector('[data-ruler]');
    trace.upFrame=frameIndex(clamp((event.clientX-ruler.getBoundingClientRect().left)/zoom,0,duration()));
  },{once:true});
  trace.finish=()=>{
    seek=originalSeek;request=originalRequest;window.fetch=originalFetch;cancelAnimationFrame(trace.raf);
    return {...trace,checkpoints:recoverySequence-trace.checkpointStart,
      generation:nativeState.generation,completed:nativeState.metrics?.completed_sequence_frame,
      acknowledged:nativeState.metrics?.completed_generation,underruns:nativeState.ack?.underruns};
  };
}"""


def drag(page, playing):
    page.evaluate(OBSERVE)
    ruler=page.locator('[data-ruler]').bounding_box()
    viewport=page.locator('#timelineScroller').bounding_box()
    left=max(ruler['x']+20,viewport['x']+170)
    right=min(ruler['x']+650,viewport['x']+viewport['width']-28)
    assert right-left>100,'Timeline ruler too narrow for the controlled gesture'
    y=ruler['y']+ruler['height']/2
    page.mouse.move(left,y)
    page.mouse.down()
    for x in [right,left+35,right-65,left+75,right-30]:
        page.mouse.move(x,y,steps=9)
    page.mouse.up()
    predicate=('scrubTrace.upFrame!==null && !nativeState.seeking && !nativeState.seekBusy && '
               'nativeState.metrics?.completed_generation===nativeState.generation && '
               'nativeState.metrics.completed_sequence_frame'+('>=' if playing else '===')+'scrubTrace.upFrame')
    timed_out=False
    try:
        page.wait_for_function(predicate,timeout=3500)
    except Exception as failure:
        if type(failure).__name__!='TimeoutError':
            raise
        timed_out=True
    ended=page.evaluate('performance.now()-scrubTrace.pointerUp')
    if playing:
        page.wait_for_timeout(280)
    record=page.evaluate('scrubTrace.finish()')
    record['timed_out']=timed_out
    record['newest_picture_ms']=ended if not timed_out else None
    record['gesture_ui_cost_ms']=distribution(record.pop('uiMs'))
    record['post_release_frames_before_target']=sum(row[1]<record['upFrame'] for row in record.pop('afterUp'))
    return record


def desktop_refresh_hz():
    user32=ctypes.windll.user32
    user32.GetDC.restype=ctypes.c_void_p
    device=user32.GetDC(None)
    try:
        return ctypes.windll.gdi32.GetDeviceCaps(ctypes.c_void_p(device),116) if device else None
    finally:
        if device:
            user32.ReleaseDC(None,ctypes.c_void_p(device))


def measure(args):
    report={'source_resolution':[3840,2160],'program_resolution':[960,540],'video_tracks':3,
            'audio_tracks':3,'sequence_seconds':90,'cut_seconds':.5,'proxy_used':False,
            'desktop_reported_refresh_hz':desktop_refresh_hz()}
    args.results.mkdir(parents=True,exist_ok=False)
    conditions=Conditions()
    try:
        with session(args.executable,args.results,offline=True) as (page,process,_,errors):
            start=time.perf_counter()
            data=page.evaluate("paths=>request('import','POST',{paths,autoProxy:false})",
                               [str((args.media/f'h264-4k60-{i}.mp4').resolve()) for i in range(3)])
            assert not data['errors']
            page.evaluate(SETUP,{'assets':data['assets'],'seconds':90,'cut':.5})
            page.wait_for_function("Array.from($('playbackEngine').options).some(o=>o.value==='native'&&!o.disabled)")
            report['project_setup_ms']=1000*(time.perf_counter()-start)
            report['app_ready_ms']=1000*page._vlogcraft_launch_seconds
            page.evaluate("()=>{$('timelineFollow').value='off';snap=false;$('programResolution').value='960';}")
            with WindowVisibility(process,'visible') as visibility:
                page.select_option('#playbackEngine','native')
                page.wait_for_function('nativeState.metrics?.completed_frames>0',timeout=30000)
                report['preview_geometry']=page.evaluate('nativeRect()')
                report['ready_resources']=resources(process)
                report['paused']=[drag(page,False) for _ in range(3)]
                report['after_paused_resources']=resources(process)
                begin=time.perf_counter()
                page.click('#playBtn')
                page.wait_for_function('isPlaying && nativeState.ack?.samples>0',timeout=12000)
                report['play_after_seek_ms']=1000*(time.perf_counter()-begin)
                report['playing']=drag(page,True)
                page.evaluate("()=>{stopPlayback();return recoverySettled()}")
                page.wait_for_timeout(1200)
                report['idle_resources']=resources(process)
                report['window']=visibility.finish()
            report['browser_error_count']=len(errors)
    except Exception as error:
        report['failure_type']=type(error).__name__
        raise
    finally:
        report['conditions']=conditions.finish()
        (args.results/'scrub.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    return int(not report['window']['condition_held'] or bool(report['browser_error_count'])
               or any(row['timed_out'] for row in [*report['paused'],report['playing']]))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('executable','media','results'):
        parser.add_argument(name,type=Path)
    raise SystemExit(measure(parser.parse_args()))
