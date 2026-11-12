"""Measure the installed native monitor using decoded moving media and Windows counters."""
import argparse
import ctypes
import json
import os
import psutil
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import urllib.request

from playwright.sync_api import sync_playwright
from performance import Resources

ROOT = Path(__file__).resolve().parents[1]


def fixtures(folder):
    folder.mkdir(parents=True, exist_ok=True)
    files = []
    for label, size, fps in [('1080p60', '1920x1080', 60), ('4k30', '3840x2160', 30), ('4k60', '3840x2160', 60)]:
        path = folder/(label+'.mp4')
        if not path.is_file():
            subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i', f'testsrc2=s={size}:r={fps}',
                            '-f', 'lavfi', '-i', 'sine=f=660:r=48000', '-t', '12', '-c:v', 'libx264',
                            '-preset', 'ultrafast', '-threads', '6', '-crf', '20', '-pix_fmt', 'yuv420p',
                            '-c:a', 'aac', '-movflags', '+faststart', str(path)], check=True)
        files.append(path.resolve())
    return files


MEASURE = """async seconds=>{
  const frames=[],drifts=[],audioDrifts=[],callbackGaps=[],gaps=[];
  let last=performance.now(),active=true,total=0,dropped=0,peakDb=-60,bufferMs=0;
  const startPlayhead=playhead;
  const quality=new Map(),subscriptions=new WeakMap();
  const players=()=>renderedEnabled()&&renderedCurrent?[{media:renderedCurrent.media,clipId:null}]:activePlayers.values();
  function observe(v){
    if(quality.has(v))return;
    quality.set(v,v.getVideoPlaybackQuality());
    const token={};subscriptions.set(v,token);let prev=null;
    const report=(now,meta)=>{
      if(!active||!v.isConnected||subscriptions.get(v)!==token)return;
      if(prev!==null)callbackGaps.push(now-prev);prev=now;
      frames.push(meta.mediaTime);v.requestVideoFrameCallback(report);
    };v.requestVideoFrameCallback(report);
  }
  function count(v){const q=quality.get(v),end=v.getVideoPlaybackQuality();
    total+=Math.max(0,end.totalVideoFrames-q.totalVideoFrames);
    dropped+=Math.max(0,end.droppedVideoFrames-q.droppedVideoFrames);quality.set(v,end);}
  const tick=()=>{
    if(!active)return;
    for(const [v] of quality)if(!v.isConnected){count(v);quality.delete(v);}
    const now=performance.now();gaps.push(now-last);
    peakDb=Math.max(peakDb,Number($('masterMeter').value));
    if(renderedEnabled()&&(renderedLoading||!renderedCurrent||renderedCurrent.media.readyState<3))bufferMs+=now-last;
    last=now;
    for(const p of players())if(p.media?.tagName==='VIDEO'){
      observe(p.media);
      const clip=programTracks.flatMap(t=>t.clips).find(c=>c.id===p.clipId);
      if(clip&&!p.media.seeking)drifts.push(Math.abs(p.media.currentTime-(clip.start+(playhead-clip.position)*clip.speed)));
    }
    for(const [id,media] of audioPlayers){
      const clip=programTracks.flatMap(t=>t.clips).find(c=>c.id===id);
      if(clip&&!media.seeking)audioDrifts.push(Math.abs(media.currentTime-(clip.start+(playhead-clip.position)*clip.speed)));
    }requestAnimationFrame(tick);
  };requestAnimationFrame(tick);
  await new Promise(resolve=>setTimeout(resolve,seconds*1000));active=false;
  const p95=a=>{a.sort((x,y)=>x-y);return a.length?a[Math.floor((a.length-1)*.95)]:null;};
  for(const [v] of quality)count(v);
  return {measured_seconds:seconds,video_frame_callbacks:frames.length,callbacks_per_second:frames.length/seconds,
    decoded_frames:total,dropped_video_frames:dropped,ui_animation_fps:gaps.length/seconds,
    ui_frame_gap_p95_ms:p95(gaps),video_callback_gap_p95_ms:p95(callbackGaps),
    media_clock_drift_p95_ms:drifts.length?p95(drifts)*1000:null,
    audio_clock_drift_p95_ms:audioDrifts.length?p95(audioDrifts)*1000:null,
    context_state:mixer?.state,peak_meter_db:peakDb,buffering_seconds:bufferMs/1000,advanced_seconds:playhead-startPlayhead};
}"""


def run(executable, folder, results,scenario=None,engine='interactive'):
    media = fixtures(folder)
    results.mkdir(parents=True, exist_ok=True)
    records = []
    with tempfile.TemporaryDirectory(prefix='bench-', dir=results, ignore_cleanup_errors=True) as tmp:
        project = Path(tmp)/'benchmark.vlogcraft'
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        env = dict(os.environ, WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=f'--remote-debugging-port={port}')
        cmd = [str(executable)]
        if executable.stem.lower() in ('python', 'pythonw'):
            cmd.append(str(ROOT/'desktop.py'))
        log = (results/'host.log').open('w', encoding='utf8')
        process = subprocess.Popen([*cmd, '--project', str(project)], env=env, stdout=log, stderr=log)
        try:
            for _ in range(150):
                try:
                    with urllib.request.urlopen(f'http://127.0.0.1:{port}/json/list', timeout=1) as response:
                        if any(t['url'].startswith('http://127.0.0.1:') for t in json.load(response)):break
                except OSError:pass
                time.sleep(.3)
            with sync_playwright() as playwright:
                browser = playwright.chromium.connect_over_cdp(f'http://127.0.0.1:{port}')
                context=browser.contexts[0]
                page=context.pages[0] if context.pages else context.wait_for_event('page',timeout=30000)
                page.wait_for_url('http://127.0.0.1:*/**',timeout=30000)
                page.set_default_timeout(90000)
                errors = []
                page.on('pageerror', lambda err: errors.append(str(err)))
                page.wait_for_function('state?.desktop')
                response = page.evaluate("paths=>request('import','POST',{paths,autoProxy:false})", [str(p) for p in media])
                assert not response['errors'], response
                page.evaluate('assets=>{state.assets=assets;useProxies=false}', response['assets'])
                page.wait_for_function("(async()=>{const jobs=await request('jobs');return jobs.readyAudio.length===3;})()")
                scenarios = [('1080p60', 0, 1, 7), ('4k30', 1, 1, 7), ('4k60', 2, 1, 7),
                             ('4k60-3video-3audio-effects', 2, 3, 9), ('1080p60-stabilized', 0, 1, 7), ('10minute-1500clips', 0, 1, 70), ('4k60-3video-3audio-proxy', 2, 3, 9)]
                for name, index, layers, seconds in scenarios:
                    if scenario and name!=scenario:continue
                    if name.endswith('-proxy'):
                        page.evaluate("(async()=>{for(const a of state.assets)await request('proxy','POST',{assetId:a.id});})()")
                        page.wait_for_function('readyProxies.size===3',timeout=180000)
                    page.evaluate('enabled=>{useProxies=enabled;refreshPlayers()}',name.endswith('-proxy'))
                    page.evaluate("""({index,layers,long})=>{
                      stopPlayback();state.output.fps=60;
                      const trackTemplate=(type,n)=>({id:uid(),type,name:type+' '+n,volume:1,hidden:false,muted:false,solo:false,locked:false,clips:[]});
                      state.tracks=[];const a=state.assets[index];
                      for(let i=0;i<layers;i++){
                        const t=trackTemplate('video',i+1),c=clipFromAsset(a,0,'video');c.end=12;
                        c.volume=layers===1?1:0;c.scale=layers===1?1:.6;c.x=(i-1)*.12;
                        if(layers>1)c.keys={rotation:[{time:0,value:-3,mode:'linear'},{time:12,value:3,mode:'linear'}],
                          x:[{time:0,value:c.x,mode:'linear'},{time:12,value:c.x+.08,mode:'linear'}]};
                        t.clips=[c];state.tracks.push(t);
                      }
                      for(let i=0;i<(layers>1?3:0);i++){
                        const t=trackTemplate('audio',i+1),c=clipFromAsset(a,0,'audio');c.end=12;c.volume=.2;
                        c.pan=(i-1)*.6;t.clips=[c];state.tracks.push(t);
                      }
                      if(long){
                        const t=state.tracks[0];t.clips=[];
                        for(let i=0;i<1500;i++){const c=clipFromAsset(a,i*.4,'video');c.start=2;c.end=2.4;t.clips.push(c);}
                      }
                      selectedId=null;playhead=0;redraw();
                    }""", {'index': index, 'layers': layers, 'long': name.startswith('10minute')})
                    if name.endswith('-stabilized'):
                        page.evaluate('save();flushSave()')
                        page.evaluate("""(async()=>{
                          const c=state.tracks[0].clips[0];
                          const r=await request('motion','POST',{clipId:c.id,mode:'stabilizeRotation',strength:.8});
                          c.keys={};
                          ['x','y','rotation'].forEach((prop,i)=>c.keys[prop]=r.points.map(p=>({time:p[0],value:p[i+1],mode:'linear'})));
                          c.scale=1.1;redraw();
                        })()""")
                    page.wait_for_function("document.querySelector('#previewLayers video')?.readyState>=2")
                    prepare_started=time.monotonic()
                    prepare_resources=None
                    if engine=='rendered':
                        prepare_meter=Resources(process.pid,gpu=True)
                        page.evaluate('save();flushSave()')
                        page.locator('#playbackEngine').select_option('rendered')
                        page.wait_for_function('renderedCurrent?.media.readyState>=2 && !renderedLoading',timeout=120000)
                        prepare_resources=prepare_meter.finish()
                    prepare_seconds=time.monotonic()-prepare_started
                    meter = Resources(process.pid, gpu=True)
                    page.locator('#playBtn').click()
                    page.wait_for_function('isPlaying && mixer?.state==="running"')
                    page.wait_for_timeout(350)
                    data = page.evaluate(MEASURE, seconds)
                    page.evaluate('stopPlayback()')
                    seeks = []
                    for at in (1.5, 6.5, 3.25):
                        started = time.monotonic()
                        page.evaluate('at=>seek(at)', at)
                        page.wait_for_function("renderedEnabled()?renderedCurrent?.media.readyState>=2&&!renderedCurrent.media.seeking&&!renderedLoading:Array.from(document.querySelectorAll('#previewLayers video')).every(v=>v.readyState>=2&&!v.seeking)")
                        seeks.append(round((time.monotonic()-started)*1000, 2))
                    data.update(name=name, engine=engine,prepare_seconds=round(prepare_seconds,3),prepare_resources=prepare_resources, resources=meter.finish(), seek_latency_ms=seeks,
                                timeline_seconds=page.evaluate('duration()'), timeline_clips=page.evaluate('state.tracks.flatMap(t=>t.clips).length'))
                    records.append(data)
                    print(json.dumps(data), flush=True)
                    assert data['context_state']=='running'
                    assert data['ui_animation_fps']>3, data
                    assert data['video_frame_callbacks']>0, data
                    if layers>1:
                        assert data['peak_meter_db']>-59,data
                        if engine=='interactive':assert data['audio_clock_drift_p95_ms'] is not None,data
                assert not errors, errors
                (results/'playback.json').write_text(json.dumps({'scenarios':records,'browser_errors':errors},indent=2))
                page.evaluate('flushSave()')
        finally:
            # Close the window of this isolated benchmark, with no other editor affected.
            try:family={process.pid,*[p.pid for p in psutil.Process(process.pid).children(recursive=True)]}
            except psutil.Error:family={process.pid}
            def close(hwnd, _):
                owner=ctypes.c_ulong()
                ctypes.windll.user32.GetWindowThreadProcessId(hwnd,ctypes.byref(owner))
                title=ctypes.create_unicode_buffer(256)
                ctypes.windll.user32.GetWindowTextW(hwnd,title,len(title))
                if owner.value in family and title.value=='VlogCraft Studio • '+project.stem:
                    ctypes.windll.user32.PostMessageW(hwnd,0x10,0,0)
                return True
            callback=ctypes.WINFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)(close)
            ctypes.windll.user32.EnumWindows(callback,0)
            try:process.wait(timeout=15)
            except subprocess.TimeoutExpired:process.terminate();process.wait()
            log.close()


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('executable',type=Path)
    parser.add_argument('media',type=Path)
    parser.add_argument('results',type=Path)
    parser.add_argument('--scenario')
    parser.add_argument('--engine',choices=['interactive','rendered'],default='interactive')
    args=parser.parse_args()
    run(args.executable.resolve(),args.media.resolve(),args.results.resolve(),args.scenario,args.engine)
