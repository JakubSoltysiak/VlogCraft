"""Verify large-library controls, removal safety and embedded audio separation."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'benchmarks'),str(ROOT/'tests')]
from windows_session import session
from windows_hdr10plus import wait_export
from test_export_workflow import ffmpeg


def main(executable,results):
    results=results.resolve()
    results.mkdir(parents=True,exist_ok=True)
    paths=[]
    for number in range(32):
        path=results/f'media-{number:02d}.png'
        Image.new('RGB',(160,90),(20,80,100+number)).save(path)
        paths.append(path)
    video=results/'camera.mp4'
    ffmpeg('-f','lavfi','-i','testsrc2=s=160x90:r=60:d=0.2','-f','lavfi','-i',
           'sine=frequency=480:sample_rate=48000:duration=0.2','-c:v','libx264','-preset','ultrafast',
           '-c:a','aac','-shortest',video)
    paths.append(video)
    original=[hashlib.sha256(p.read_bytes()).digest() for p in paths]
    project=results/'library.vlogcraft'
    with session(executable,results,offline=True,project_path=project) as (page,_,__,errors):
        response=page.evaluate("paths=>request('import','POST',{paths,autoProxy:false})",[str(p) for p in paths])
        assert len(response['assets'])==33 and not response['errors']
        camera=response['assets'][-1]['id']
        removed=response['assets'][0]['id']
        page.evaluate("""async id=>{
          state=await request('state');
          Object.assign(state.output,{width:160,height:90,fps:60,preset:'ultrafast'});
          addAsset(assetById(id));await flushSave();
        }""",camera)
        page.select_option('#libraryView','list')
        assert page.locator('#assetList').evaluate("el=>el.classList.contains('list-view')&&el.scrollHeight>el.clientHeight")
        width=page.locator('.media-panel').evaluate('el=>el.clientWidth')
        page.eval_on_selector('#libraryWidth',"el=>{el.value=330;el.dispatchEvent(new Event('input'));}")
        if page.evaluate('matchMedia("(min-width:1100px)").matches'):
            assert page.locator('.media-panel').evaluate('el=>el.clientWidth')!=width
        page.locator(f'[data-asset="{camera}"]').click()
        page.click('#libraryRemove')
        assert 'used by 1 clip' in page.locator('#toast').text_content()
        photo=page.locator(f'[data-asset="{removed}"]')
        photo.locator('img').evaluate("el=>{el.loading='eager';}")
        page.locator(f'[data-asset="{removed}"] img').evaluate("el=>el.decode()")
        photo.click()
        page.click('#libraryRemove')
        assert photo.count()==0
        page.evaluate('restoreHistory(undoStack,redoStack)')
        assert photo.count()==1
        page.evaluate('restoreHistory(redoStack,undoStack)')
        assert photo.count()==0
        page.evaluate('flushSave()')

        page.click('[data-tab=project]')
        page.click('#storageUsage')
        page.get_by_text('Source dependencies',exact=True).wait_for()
        page.once('dialog',lambda prompt:prompt.accept())
        page.click('#clearRemovedThumbs')
        page.wait_for_function("$('toast').textContent.includes('Cleared 1 cached thumbnail')")
        page.click('#closeStorage')
        page.check('#showRemovedMedia')
        assert photo.count()==1
        photo.click()
        page.click('#libraryRemove')
        page.uncheck('#showRemovedMedia')
        assert photo.count()==1
        page.locator(f'[data-asset="{removed}"] img').evaluate("el=>el.decode()")
        page.click('[data-tab=clip]')
        page.evaluate("select(state.tracks.find(t=>t.clips.length).clips[0].id);flushSave()")
        a,b=results/'embedded.mp4',results/'separate.mp4'
        page.evaluate("path=>request('export','POST',{path})",str(a))
        assert wait_export(page)['status']=='done'
        page.click('#separateCameraAudio')
        assert page.evaluate("""()=>{
          const clips=state.tracks.flatMap(t=>t.clips),v=clips.find(c=>c.kind==='video'),a=clips.find(c=>c.kind==='audio');
          return v.audioDetached&&v.linkId===a.linkId;
        }""")
        assert page.locator('.audio-clip .clip-bg').get_attribute('style').find('/wave/')!=-1
        page.evaluate('flushSave()')
        page.evaluate("path=>request('export','POST',{path})",str(b))
        assert wait_export(page)['status']=='done'
        assert not errors,errors
    samples=lambda path:ffmpeg('-i',path,'-map','0:a','-f','s16le','pipe:1')
    first,second=samples(a),samples(b)
    assert first==second and any(first)
    assert [hashlib.sha256(p.read_bytes()).digest() for p in paths]==original
    with session(executable,results/'reopen',offline=True,project_path=project) as (page,_,__,errors):
        assert page.evaluate("state.tracks.flatMap(t=>t.clips).filter(c=>c.linkId).length") == 2
        assert page.locator('[data-asset]').count()==33
        assert not errors,errors
    print(json.dumps({'assets':33,'linked_clip_persistence':True,'decoded_PCM_bytes':len(first),
                      'separation_PCM_equal':True,'removed_and_restored_thumbnail':True,'all_sources_unchanged':True}))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('executable',type=Path)
    parser.add_argument('results',type=Path)
    args=parser.parse_args()
    main(args.executable,args.results)
