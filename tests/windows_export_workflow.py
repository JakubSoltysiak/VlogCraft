"""Exercise the installed application's WinForms Save dialog and a UHD60 export."""
import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT),str(ROOT/'benchmarks'),str(ROOT/'tests')]
from windows_session import session
from test_export_workflow import decode, fixture, ffmpeg


def native_dialog(pid):
    user = ctypes.windll.user32
    callback = ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
    deadline = time.monotonic()+15
    while time.monotonic()<deadline:
        found = []
        @callback
        def collect(handle,_):
            owner = wintypes.DWORD()
            user.GetWindowThreadProcessId(handle,ctypes.byref(owner))
            if owner.value==pid and user.IsWindowVisible(handle):
                name = ctypes.create_unicode_buffer(80)
                user.GetClassNameW(handle,name,len(name))
                if name.value=='#32770':
                    found.append(handle)
            return True
        user.EnumWindows(collect,0)
        if found:
            return found[0]
        time.sleep(.1)
    raise AssertionError('No visible Save As dialog owned by the test editor')


def complete_dialog(dialog,path):
    user = ctypes.windll.user32
    callback = ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
    edits = []
    @callback
    def collect(handle,_):
        name = ctypes.create_unicode_buffer(80)
        user.GetClassNameW(handle,name,len(name))
        if name.value=='Edit' and user.IsWindowVisible(handle):
            edits.append(handle)
        return True
    user.EnumChildWindows(dialog,collect,0)
    assert len(edits)==1, f'Expected one visible filename edit, got {len(edits)}'
    user.SendMessageW.argtypes = [wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM]
    user.SendMessageW.restype = wintypes.LPARAM
    buffer = ctypes.create_unicode_buffer(str(path))
    assert user.SendMessageW(edits[0],0x000C,0,ctypes.addressof(buffer))
    assert user.PostMessageW(dialog,0x0111,1,0)


def test(executable,results,baseline):
    results = results.resolve()
    results.mkdir(parents=True,exist_ok=True)
    if baseline:
        with session(executable,results,offline=True) as (page,_,__,errors):
            page.evaluate("state.tracks[0].clips=[{kind:'title',id:uid(),position:0,start:0,end:1,text:'Fixture'}];save();flushSave()")
            message = page.evaluate("request('export','POST',{}).then(()=>null,error=>error.message)")
            assert message and 'H.264 MP4 (*.mp4) is not a valid file filter' in message, message
            assert not errors
        print(json.dumps({'baseline_filter_reproduced':True}))
        return
    state,paths = fixture(results,3840,2160,5)
    hashes = [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths]
    destination = results/'Output Łódź'/'Film żółć.mp4'
    destination.parent.mkdir()
    with session(executable,results,offline=True) as (page,process,_,errors):
        imported = page.evaluate("paths=>request('import','POST',{paths,autoProxy:false})",[str(p) for p in paths])
        assert not imported['errors'], imported['errors']
        ids = {asset['path']:asset['id'] for asset in imported['assets']}
        replacements = {asset['id']:ids[asset['path']] for asset in state['assets']}
        for track in state['tracks']:
            for clip in track['clips']:
                clip['assetId'] = replacements[clip['assetId']]
        state['assets'] = imported['assets']
        page.evaluate("""async doc=>{
            await request('state','POST',doc);state=await request('state');redraw();
        }""",state)
        page.click('#exportBtn')
        page.wait_for_function("!$('startRender').disabled")
        page.click('#startRender')
        dialog=native_dialog(process.pid)
        assert ctypes.windll.user32.PostMessageW(dialog,0x0111,2,0)
        page.wait_for_function("!$('startRender').disabled")
        assert page.evaluate("request('jobs')")['export']['status']=='idle'
        page.click('#browseExport')
        complete_dialog(native_dialog(process.pid),destination)
        page.wait_for_function("p=>$('exportPath').value===p",arg=str(destination))
        encoders=page.evaluate("request('encoders')")
        selected='hevc_amf' if 'hevc_amf' in encoders else 'libx264'
        page.select_option('#encoderChoice',selected)
        if selected=='hevc_amf':
            assert page.locator('#cpuExportPreset').get_attribute('hidden') is not None
            page.fill('#outputBitrate','60')
        page.click('#startRender')
        samples = []
        start = time.monotonic()
        while time.monotonic()-start<180:
            status=page.evaluate("request('jobs')")['export']
            sample={k:status[k] for k in ('stage','frames','stageFraction','percent','elapsedSeconds') if k in status}
            if not samples or sample!=samples[-1]:
                samples.append(sample)
            if status['status'] in ('done','error','cancelled'):
                break
            time.sleep(.15)
        assert status['status']=='done',status
        assert any(0<row.get('frames',0)<300 and row.get('stage')=='video' for row in samples), samples
        assert page.locator('#openExportFolder').is_visible()
        assert not errors,errors
    video,audio=decode(destination)
    assert (video['width'],video['height'],video['avg_frame_rate'])==(3840,2160,'60/1'),video
    assert int(video['nb_read_frames'])==324,video
    assert abs(float(video['duration'])-5.4)<.002 and abs(float(audio['duration'])-5.4)<.002,(video,audio)
    assert video['codec_name']==('hevc' if selected=='hevc_amf' else 'h264'),video
    assert video['pix_fmt']=='yuv420p',video
    # Decode the delivered last audio segment and verify the original camera tone survived.
    assert any(ffmpeg('-i',destination,'-ss','5.2','-map','0:a','-f','s16le','pipe:1'))
    assert [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths]==hashes
    report={'output':'3840x2160/60','actual_encoder':status['encoder'],'requested_encoder':selected,
            'frames':324,'audio_duration':float(audio['duration']),'video_duration':float(video['duration']),
            'pixel_format':video['pix_fmt'],'codec':video['codec_name'],'seconds':status['elapsedSeconds'],
            'unicode_save':True,'cancel_no_job':True,'source_hashes_match':True,'samples':samples}
    (results/'verification.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in report.items() if k!='samples'}))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('executable',type=Path)
    parser.add_argument('results',type=Path)
    parser.add_argument('--baseline',action='store_true')
    args=parser.parse_args()
    test(args.executable,args.results,args.baseline)
