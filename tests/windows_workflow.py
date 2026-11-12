"""Exercise the running Windows app with a real native WebView2 file drop payload."""
import argparse
import ctypes
import json
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


def test(executable, source, results):
    results.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='workflow-', dir=results, ignore_cleanup_errors=True) as testdir:
        project = Path(testdir)/'Verification.vlogcraft'
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
                page.screenshot(path=str(results/'empty.png'))
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
                page.evaluate("state.output.fps=60;state.output.preset='veryfast';seek(4.6)")
                page.wait_for_function("Math.abs(document.querySelector('#previewLayers video').currentTime-4.6)<.02 && !document.querySelector('#previewLayers video').seeking")
                sample = page.evaluate("""() => {const c=document.createElement('canvas');c.width=32;c.height=18;
                    const ctx=c.getContext('2d');ctx.drawImage(document.querySelector('#previewLayers video'),0,0,32,18);
                    return new Set(ctx.getImageData(0,0,32,18).data).size;}""")
                assert sample>20, 'Program monitor failed to decode the selected frame'
                page.locator('#splitBtn').click()
                assert page.evaluate("state.tracks.flatMap(t=>t.clips).length")==2
                page.evaluate("const tr=sel().track;const right=sel().clip;select(tr.clips[0].id);removeSelected();right.position=0;seek(0);save();redraw()")
                page.locator('#undoBtn').click()
                assert page.evaluate("state.tracks.flatMap(t=>t.clips).length")==2
                page.locator('#redoBtn').click()
                page.evaluate('flushSave()')
                page.screenshot(path=str(results/'edit.png'))
                timeline=json.loads(project.read_bytes())
                clip=next(c for t in timeline['tracks'] for c in t['clips'])
                assert abs(clip['start']-4.6)<1e-7 and clip['position']==0,clip
                target=Path(testdir)/'delivery.mp4'
                start=time.monotonic()
                page.evaluate("(path)=>request('export','POST',{path})",str(target))
                page.wait_for_function("async()=>['done','error','cancelled'].includes((await request('jobs')).export.status)",timeout=120000)
                status=page.evaluate("(async()=>(await request('jobs')).export)()")
                assert status['status']=='done',status
                export_seconds=time.monotonic()-start
                streams=probe(target,'-show_streams')['streams']
                video=next(s for s in streams if s['codec_type']=='video')
                audio=next(s for s in streams if s['codec_type']=='audio')
                assert (video['width'],video['height'],video['r_frame_rate'],video['nb_frames'])==(3840,2160,'60/1','24'),video
                assert abs(float(audio['duration'])-float(video['duration']))<1/60
                packets=probe(source,'-select_streams','v:0','-read_intervals','4.6%+#1','-show_packets')['packets']
                assert int(packets[0]['pos'])>2**32 and source.stat().st_size>4.5*1024**3
                assert not errors, errors
                summary={'source_bytes':source.stat().st_size,'first_edited_packet_offset':int(packets[0]['pos']),
                         'native_drop_to_timeline_seconds':round(link_seconds,3),'proxy_monitor_distinct_byte_values':sample,
                         'export_seconds':round(export_seconds,3),'video_frames':int(video['nb_frames']),
                         'resolution':[video['width'],video['height']],'rate':video['r_frame_rate'],
                         'audio_seconds':audio['duration'],'video_seconds':video['duration'],'browser_errors':errors}
                print(json.dumps(summary,indent=2),flush=True)
                (results/'windows-workflow.json').write_text(json.dumps(summary,indent=2))
        finally:
            # Close only the native window owned by the process this test started.
            def close_window(hwnd, _):
                pid=ctypes.c_ulong()
                ctypes.windll.user32.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
                if pid.value==p.pid:ctypes.windll.user32.PostMessageW(hwnd,0x10,0,0)
                return True
            callback=ctypes.WINFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)(close_window)
            ctypes.windll.user32.EnumWindows(callback,0)
            try:p.wait(timeout=12)
            except subprocess.TimeoutExpired:p.terminate();p.wait()


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('executable',type=Path)
    parser.add_argument('source',type=Path)
    parser.add_argument('results',type=Path)
    args=parser.parse_args()
    test(args.executable.resolve(),args.source.resolve(),args.results.resolve())
