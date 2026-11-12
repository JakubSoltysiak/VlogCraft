"""Exercise the running Windows app with a real native WebView2 file drop payload."""
import argparse
import ctypes
import json
import io
from PIL import Image,ImageChops,ImageStat
from performance import Resources
import os
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def probe(path, *args):
    return json.loads(subprocess.check_output(['ffprobe','-v','error',*args,'-of','json',str(path)]))


def test(executable, source, results, record_visual=False):
    results.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='workflow-', dir=results, ignore_cleanup_errors=True) as testdir:
        project = Path(testdir)/(Path(testdir).name+'.vlogcraft')
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0))
            port=sock.getsockname()[1]
        env = dict(os.environ, WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=f'--remote-debugging-port={port}')
        cmd = [str(executable)]
        if executable.stem.lower() in ('python','pythonw'):
            cmd.append(str(ROOT/'desktop.py'))
        p = subprocess.Popen([*cmd,'--project',str(project)],env=env)
        try:
            deadline=time.monotonic()+50
            while time.monotonic()<deadline and p.poll() is None:
                try:
                    with urllib.request.urlopen(f'http://127.0.0.1:{port}/json/list',timeout=1) as res:
                        if any(t['url'].startswith('http://127.0.0.1:') for t in json.load(res)):break
                except OSError:pass
                time.sleep(.3)
            with sync_playwright() as pw:
                browser = pw.chromium.connect_over_cdp(f'http://127.0.0.1:{port}')
                context=browser.contexts[0]
                page=next(tab for tab in context.pages if tab.url.startswith('http://'))
                page.set_default_timeout(30000)
                errors=[]
                page.on('pageerror',lambda err:errors.append(str(err)))
                page.wait_for_function("document.documentElement.classList.contains('native-ready') && state?.desktop")
                page.evaluate('document.fonts.ready')
                page.screenshot(path=str(results/'empty.png'))
                baseline=ROOT/'tests'/'visual'
                if record_visual:baseline.mkdir(exist_ok=True)
                differences={}
                for selector in ('linkBtn','snapBtn','previewSource'):
                    image=Image.open(io.BytesIO(page.locator('#'+selector).screenshot(scale='css'))).convert('RGB')
                    reference=baseline/(selector+'.png')
                    if record_visual:image.save(reference)
                    else:
                        known=Image.open(reference).convert('RGB')
                        assert known.size==image.size,(selector,known.size,image.size)
                        differences[selector]=round(sum(ImageStat.Stat(ImageChops.difference(known,image)).mean)/3,3)
                        assert differences[selector]<3,differences
                for width in (1024,1440):
                    page.set_viewport_size({'width':width,'height':850})
                    page.wait_for_function("document.querySelector('.inspector-panel').getBoundingClientRect().width>100")
                    assert page.locator('#stepForward').is_visible()
                page.set_viewport_size({'width':1440,'height':850})
                meter=Resources(p.pid)
                dev=context.new_cdp_session(page)
                drop={'items':[],'files':[str(source)],'dragOperationsMask':1}
                start=time.monotonic()
                for event in ('dragEnter','dragOver','drop'):
                    dev.send('Input.dispatchDragEvent',{'type':event,'x':390,'y':210,'data':drop})
                page.wait_for_function('state.assets.length===1 && !!sel()')
                link_seconds=time.monotonic()-start
                asset=page.evaluate('state.assets[0]')
                assert Path(asset['path'])==source and asset['size']==source.stat().st_size
                assert not list((project.parent/(project.name+'.data')/'media').iterdir())
                page.wait_for_function('readyProxies.size===1',timeout=120000)
                page.wait_for_function("document.querySelector('#previewLayers video')?.readyState>=2")
                proxy_seconds=time.monotonic()-start
                seek_start=time.monotonic()
                page.evaluate("state.output.fps=60;state.output.preset='veryfast';seek(4.6)")
                page.wait_for_function("Math.abs(document.querySelector('#previewLayers video').currentTime-4.6)<.02 && !document.querySelector('#previewLayers video').seeking")
                seek_seconds=time.monotonic()-seek_start
                sample = page.evaluate("""() => {const c=document.createElement('canvas');c.width=32;c.height=18;
                    const ctx=c.getContext('2d');ctx.drawImage(document.querySelector('#previewLayers video'),0,0,32,18);
                    return new Set(ctx.getImageData(0,0,32,18).data).size;}""")
                assert sample>20, 'Program monitor failed to decode the selected frame'
                page.locator('#splitBtn').click()
                assert page.evaluate("state.tracks.flatMap(t=>t.clips).length")==2
                page.evaluate("const tr=sel().track;const right=sel().clip.id;select(tr.clips[0].id);removeSelected();select(right);commitEdit('move',{frames:-frameIndex(sel().clip.position)});seek(0);save();redraw()")
                page.locator('#undoBtn').click()
                assert page.evaluate("frameIndex(state.tracks.flatMap(t=>t.clips)[0].position)===276")
                page.locator('#redoBtn').click()
                page.evaluate('flushSave()')
                page.evaluate("select(state.tracks.flatMap(t=>t.clips)[0].id);seek(.1)")
                page.wait_for_function("document.querySelector('#previewLayers video')?.readyState>=2 && !document.querySelector('#previewLayers video').seeking")
                page.screenshot(path=str(results/'edit.png'))
                timeline=json.loads(project.read_bytes())
                clip=next(c for t in timeline['tracks'] for c in t['clips'])
                assert abs(clip['start']-4.6)<1e-7 and clip['position']==0,clip
                target=Path(testdir)/'delivery.mp4'
                start=time.monotonic()
                page.evaluate("(path)=>request('export','POST',{path})",str(target))
                deadline=time.monotonic()+120
                while time.monotonic()<deadline:
                    status=page.evaluate("(async()=>(await request('jobs')).export)()")
                    if status['status'] in ('done','error','cancelled'):break
                    time.sleep(.2)
                assert status['status']=='done',status
                export_seconds=time.monotonic()-start
                streams=probe(target,'-show_streams')['streams']
                video=next(s for s in streams if s['codec_type']=='video')
                audio=next(s for s in streams if s['codec_type']=='audio')
                assert (video['width'],video['height'],video['r_frame_rate'],video['nb_frames'])==(3840,2160,'60/1','24'),video
                assert abs(float(audio['duration'])-float(video['duration']))<1/60
                packets=probe(source,'-select_streams','v:0','-read_intervals','4.6%+#1','-show_packets')['packets']
                assert int(packets[0]['pos'])>2**32 and source.stat().st_size>4.5*1024**3
                def first_frame(path,at):
                    return subprocess.check_output(['ffmpeg','-v','error','-ss',str(at),'-i',str(path),'-an',
                                                    '-frames:v','1','-vf','scale=96:54','-pix_fmt','rgb24','-f','rawvideo','-'])
                original=first_frame(source,4.6)
                rendered=first_frame(target,0)
                mae=sum(abs(a-b) for a,b in zip(original,rendered))/len(original)
                assert mae<8,(mae,'Delivered frame differs from the selected original frame')
                assert not errors, errors
                summary={'resources':meter.finish(),'drop_through_proxy_ready_seconds':round(proxy_seconds,3),'single_seek_seconds':round(seek_seconds,3),'visual_RGB_differences':differences,'source_bytes':source.stat().st_size,'first_edited_packet_offset':int(packets[0]['pos']),
                         'native_drop_to_timeline_seconds':round(link_seconds,3),'proxy_monitor_distinct_byte_values':sample,
                         'decoded_rgb_mean_absolute_error':round(mae,3),'export_seconds':round(export_seconds,3),'video_frames':int(video['nb_frames']),
                         'resolution':[video['width'],video['height']],'rate':video['r_frame_rate'],
                         'audio_seconds':audio['duration'],'video_seconds':video['duration'],'browser_errors':errors}
                page.locator('[data-source]').first.click()
                assert page.locator('.source-media video').is_visible()
                page.locator('.close-source').click()
                page.locator('[data-track-settings]').first.click()
                page.locator('.motion-dialog input[name="name"]').fill('Wildlife overlays')
                page.locator('.motion-dialog button[type="button"]').click()
                page.locator('#motionOpen').click()
                page.locator('#motionRun').click()
                page.wait_for_function("!document.querySelector('#motionApply').hidden || (!document.querySelector('#motionRun').disabled && !document.querySelector('#motionInfo').textContent.startsWith('Reading'))")
                assert page.locator('#motionApply').is_visible(),page.locator('#motionInfo').inner_text()
                page.locator('#motionApply').click()
                assert page.evaluate("sel().clip.keys.x.length>=2")
                page.locator('#undoBtn').click()
                page.evaluate("select(state.tracks.flatMap(t=>t.clips)[0].id)")
                proposal=page.evaluate("""()=>({schema:'vlogcraft.timeline/1',actions:[{type:'edit_clip',
                    trackId:sel().track.id,clipId:sel().clip.id,set:{grade:'warm'}}]})""")
                page.locator('#aiBtn').click()
                page.locator('#proposalJson').fill(json.dumps(proposal))
                page.locator('#previewAiBtn').click()
                page.wait_for_function("!document.querySelector('#applyAiBtn').disabled")
                page.once('dialog',lambda d:d.accept())
                page.locator('#applyAiBtn').click()
                page.wait_for_function("state.tracks.flatMap(t=>t.clips)[0].grade==='warm'")
                page.once('dialog',lambda d:d.accept())
                page.locator('#undoAiBtn').click()
                page.wait_for_function("state.tracks.flatMap(t=>t.clips)[0].grade==='neutral'")
                page.locator('[data-close="aiModal"]').first.click()
                page.reload()
                page.wait_for_function("state?.assets.length===1 && state.tracks.flatMap(t=>t.clips).length===1")
                assert page.evaluate("Math.abs(state.tracks.flatMap(t=>t.clips)[0].start-4.6)<1e-6")
                assert not errors,errors
                summary.update(installed_motion_apply_undo=True,offline_proposal_approve_undo=True,
                               source_monitor=True,project_reload=True)
                print(json.dumps(summary,indent=2),flush=True)
                (results/'windows-workflow.json').write_text(json.dumps(summary,indent=2))
        finally:
            # Close only the native window owned by the process this test started.
            def close_window(hwnd, _):
                pid=ctypes.c_ulong()
                ctypes.windll.user32.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
                title=ctypes.create_unicode_buffer(256)
                ctypes.windll.user32.GetWindowTextW(hwnd,title,len(title))
                if title.value=='VlogCraft Studio • '+project.stem:
                    ctypes.windll.user32.PostMessageW(hwnd,0x10,0,0)
                return True
            callback=ctypes.WINFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)(close_window)
            ctypes.windll.user32.EnumWindows(callback,0)
            try:p.wait(timeout=12)
            except subprocess.TimeoutExpired:
                p.terminate()
                p.wait()
                raise AssertionError('Desktop window did not close normally')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('executable',type=Path)
    parser.add_argument('source',type=Path)
    parser.add_argument('results',type=Path)
    parser.add_argument('--record-visual',action='store_true')
    args=parser.parse_args()
    test(args.executable.resolve(),args.source.resolve(),args.results.resolve(),args.record_visual)
