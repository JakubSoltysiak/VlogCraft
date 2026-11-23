"""Local packaged camera/still edit in the explicit SDR monitor of an HDR project."""
import argparse
import json
import statistics
import subprocess
import time
import traceback
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image

from window_visibility import WindowVisibility
from windows_session import session


def qualify(executable, manifest, results):
    sources = [Path(row['path']).resolve() for row in json.loads(manifest.read_text('utf8'))]
    results = results.resolve()
    if len(sources) != 3 or any(results.is_relative_to(path.parent) for path in sources):
        raise ValueError('Three input recordings and a separate output directory are required')
    results.mkdir(parents=True, exist_ok=False)
    still = results / 'generated-chart.png'
    Image.new('RGB', (160, 90), (48, 96, 144)).save(still)
    with session(executable, results, offline=True) as (page, process, _, errors):
        started = time.monotonic()
        page.evaluate("""async paths=>{
          const imported=await request('import','POST',{paths,autoProxy:false});
          if (imported.errors.length||imported.assets.length!==4) throw Error('Fixture import failed');
          state=await request('state');
          const sources=imported.assets.slice(0,3),photo=imported.assets[3];
          if (!sources.every(a=>a.kind==='video'&&a.duration>=2)||photo.kind!=='image')
            throw Error('Fixture media contract differs');
          const picture={id:uid(),name:'Picture',type:'video',volume:1,clips:[]};
          const sound={id:uid(),name:'Audio',type:'audio',volume:1,clips:[]};
          for (const [i,a] of sources.entries()){
            const clip={...clipFromAsset(a,i),start:.5,end:1.5,audioDetached:true};
            picture.clips.push(clip);
            if(a.hasAudio) sound.clips.push({...clipFromAsset(a,i,'audio'),start:.5,end:1.5});
          }
          const overlay={...clipFromAsset(photo,.5),end:2,scale:.4,x:.2,opacity:.65,
            keys:{scale:[{time:0,value:.4,mode:'linear'},{time:1.9,value:.55,mode:'linear'}]}};
          state.tracks=[{id:uid(),name:'Still',type:'video',volume:1,clips:[overlay]},picture,sound];
          Object.assign(state.output,{width:3840,height:2160,fps:60,color:{
            version:1,workingSpace:'linear-rec2020-100nits',output:'hdr10',sdrWhiteNits:100}});
          stopPlayback();useProxies=false;$('previewSource').value='original';playhead=0;
          $('playbackEngine').value='rendered';$('programResolution').value='960';
          redraw();save();await flushSave();$('playbackEngine').onchange();
        }""", [str(path) for path in [*sources, still]])
        page.wait_for_function("""renderedCurrent?.media?.readyState>=2 &&
            $('programPreviewStatus').textContent.includes('SDR tone-mapped monitor')""",timeout=300000)
        first_picture = time.monotonic() - started
        with WindowVisibility(process, 'visible') as visible:
            page.evaluate("""()=>{
              const v=renderedCurrent.media, q=v.getVideoPlaybackQuality();
              window.mixedFrames={times:[],total:q.totalVideoFrames,dropped:q.droppedVideoFrames};
              const frame=(now,meta)=>{
                mixedFrames.times.push([now,meta.mediaTime]);
                mixedFrames.id=v.requestVideoFrameCallback(frame);
              };
              mixedFrames.id=v.requestVideoFrameCallback(frame);
            }""")
            page.click('#playBtn')
            page.wait_for_function('isPlaying')
            page.wait_for_function('!isPlaying && playhead>=duration()-.001',timeout=20000)
            sample = page.evaluate("""()=>{
              const v=renderedCurrent.media,q=v.getVideoPlaybackQuality(),box=$('previewStage').getBoundingClientRect();
              v.cancelVideoFrameCallback(mixedFrames.id);
              return {times:mixedFrames.times,decoded:q.totalVideoFrames-mixedFrames.total,
                dropped:q.droppedVideoFrames-mixedFrames.dropped,sourceUrl:v.currentSrc,
                physical:[Math.round(box.width*devicePixelRatio),Math.round(box.height*devicePixelRatio)],
                dpr:devicePixelRatio,monitor:[v.videoWidth,v.videoHeight],
                program:[state.output.width,state.output.height],hdrOutput:state.output.color.output==='hdr10',
                frames:frameIndex(duration()),first:renderedCurrent.firstFrame,last:renderedCurrent.lastFrame,
                appliedStillKeys:state.tracks[0].clips[0].keys.scale.length};
            }""")
            condition = visible.finish()
        # Verify the exact derivative just presented, after the timing interval. No camera path or image is published.
        local_url = sample.pop('sourceUrl')
        parsed, origin = urlparse(local_url), urlparse(page.url)
        if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or parsed.netloc != origin.netloc:
            raise ValueError('Program monitor must use the owned loopback service')
        probe = subprocess.run(['ffprobe','-v','error','-count_frames','-select_streams','v:0',
                                '-show_entries','stream=nb_read_frames,width,height','-of','json',local_url],
                               check=True,capture_output=True,timeout=30)
        decoded = json.loads(probe.stdout)['streams'][0]
        times = sample.pop('times')
        gaps = [b[0]-a[0] for a,b in zip(times,times[1:])]
        passed = (not errors and condition['condition_held'] and sample['hdrOutput']
                  and sample['first']==0 and sample['last']==sample['frames']==180
                  and int(decoded['nb_read_frames'])==180 and sample['appliedStillKeys']==2
                  and sample['monitor']==[decoded['width'],decoded['height']]==[960,540]
                  and len(times)>1 and times[-1][1]>times[0][1])
        receipt = dict(scope='Three-second explicit Composited SDR monitor of a UHD60 HDR project',
                       passed=bool(passed),sources=3,generated_stills=1,first_ready_including_import_seconds=first_picture,
                       first_source_to_last_media_seconds=times[-1][1]-times[0][1] if times else None,
                       callback_count=len(times),max_callback_gap_ms=max(gaps,default=None),
                       median_callback_gap_ms=statistics.median(gaps) if gaps else None,
                       independent_decoded_monitor_frames=int(decoded['nb_read_frames']),visible=condition['condition_held'],
                       **sample)
        (results/'mixed-monitor-safe.json').write_text(json.dumps(receipt,indent=2),encoding='utf8')
        return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ('executable','manifest','results'):
        parser.add_argument(arg,type=Path)
    args = parser.parse_args()
    try:
        report = qualify(args.executable,args.manifest,args.results)
    except Exception as error:
        # An FFmpeg or import diagnostic can contain private paths. Only show the category here.
        if (args.results/'session-lifecycle.json').is_file():
            (args.results/'failure-private.log').write_text(traceback.format_exc(),encoding='utf8')
        print(json.dumps({'passed':False,'error':type(error).__name__}))
        raise SystemExit(1)
    print(json.dumps(report))
    raise SystemExit(not report['passed'])
