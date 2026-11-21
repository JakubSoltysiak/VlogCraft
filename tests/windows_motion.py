"""Exercise batch presets, default insertion, numeric key editing and decoded export."""
import argparse
import json
from pathlib import Path
import sys
import time

from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'benchmarks'),str(ROOT/'tests')]
from windows_session import session
from test_export_workflow import ffmpeg


def apply(page,scope,preset,duration='0.5'):
    page.click('#motionPresetsBtn')
    page.select_option('#motionScope',scope)
    page.select_option('#motionPreset',preset)
    page.fill('#motionDuration',duration)
    page.locator('dialog[open] button',has_text='Apply').click()


def main(executable,results):
    results=results.resolve()
    results.mkdir(parents=True,exist_ok=True)
    paths=[]
    for i,color in enumerate([(235,34,22),(32,110,220),(43,200,100)]):
        path=results/f'photo-{i}.png'
        Image.new('RGB',(160,90),color).save(path)
        paths.append(str(path))
    project=results/'batch.vlogcraft'
    with session(executable,results,offline=True,project_path=project) as (page,_,__,errors):
        response=page.evaluate("paths=>request('import','POST',{paths,autoProxy:false})",paths)
        assert not response['errors'] and len(response['assets'])==3
        page.evaluate("""async ()=>{
          state=await request('state');Object.assign(state.output,{width:160,height:90,fps:24,preset:'ultrafast'});
          addAsset(state.assets[0]);addAsset(state.assets[1]);await flushSave();
        }""")
        apply(page,'project','fade-in')
        count="state.tracks.flatMap(t=>t.clips).filter(c=>c.keys?.opacity?.length===2).length"
        assert page.evaluate(count)==2
        page.evaluate('restoreHistory(undoStack,redoStack)')
        assert page.evaluate(count)==0
        page.evaluate('restoreHistory(redoStack,undoStack)')
        assert page.evaluate(count)==2
        apply(page,'default','zoom-in')
        page.locator('[data-add]').nth(2).click()
        assert page.evaluate("sel().clip.keys.scale.length") == 2
        page.locator('#animationPanel summary').click()
        page.select_option('#curveProperty','scale')
        page.select_option('#curveKeyList','1')
        page.fill('#curveTime','1')
        page.fill('#curveValue','1.2')
        page.click('#keySet')
        assert page.evaluate("sel().clip.keys.scale[1].time===1&&sel().clip.keys.scale[1].value===1.2&&!sel().clip.keys.scale[1].preset")
        await_save=page.evaluate('flushSave()')
        assert await_save['output']['defaultMotion']['preset']=='zoom-in'
        output=results/'animation.mp4'
        page.evaluate("path=>request('export','POST',{path})",str(output))
        deadline=time.monotonic()+35
        while time.monotonic()<deadline:
            status=page.evaluate("request('jobs')")['export']
            if status['status'] in ('done','error','cancelled'):
                break
            time.sleep(.1)
        assert status['status']=='done',status
        assert not errors,errors
    early,late=[list(ffmpeg('-ss',timecode,'-i',output,'-frames:v','1','-vf','scale=1:1',
                            '-pix_fmt','rgb24','-f','rawvideo','pipe:1')) for timecode in ('0','0.65')]
    assert late[0]-early[0]>160,(early,late)
    with session(executable,results/'reopen',offline=True,project_path=project) as (page,_,__,errors):
        assert page.evaluate(count)==2
        assert page.evaluate("state.output.defaultMotion.preset")=='zoom-in'
        assert page.evaluate("state.tracks.flatMap(t=>t.clips).some(c=>c.keys?.scale?.[1]?.time===1)")
        assert not errors,errors
    data={'batch_clips':2,'undo_redo':True,'default_and_numeric_key_persisted':True,
          'decoded_first_pixel':early,'decoded_after_fade':late}
    (results/'verification.json').write_text(json.dumps(data,indent=2),encoding='utf8')
    print(json.dumps(data))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('executable',type=Path)
    parser.add_argument('results',type=Path)
    args=parser.parse_args()
    main(args.executable,args.results)
