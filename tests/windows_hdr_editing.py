"""Installed Windows acceptance for managed mixed media and boundary history."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from xml.etree import ElementTree

import numpy as np
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'benchmarks'),str(ROOT/'tests')]
from app_version import VERSION
from hdr10plus_index import SIDE_DATA
from test_hdr_color import CONTRACT,source
from test_hdr_editing import luminance
from test_hdr10plus_export import command,decoded
from windows_hdr10plus import wait_export
from windows_session import session


def main(executable,results):
    results=results.resolve()
    results.mkdir(parents=True,exist_ok=True)
    files=[Path(source(results,'dark',200)['path']),Path(source(results,'bright',800)['path'])]
    photo=results/'gray.jpg'
    Image.new('RGB',(128,72),(128,128,128)).save(photo)
    files.append(photo)
    hashes=[hashlib.sha256(path.read_bytes()).digest() for path in files]
    project=results/'editor.vlogcraft'
    master=results/'HDR edycja żółć.mp4'
    static=results/'comparison.mp4'
    with session(executable,results,offline=True,project_path=project) as (page,_,__,errors):
        assert page.locator('[data-app-version]').all_text_contents()==[VERSION]*3
        page.evaluate("""async ({paths,color})=>{
          const imported=await request('import','POST',{paths,autoProxy:false});
          if(imported.errors.length||imported.assets.length!==3)throw Error('Fixture import failed');
          state=await request('state');
          const [titleTrack,main]=state.tracks.filter(t=>t.type==='video');
          const [a,b,photo]=imported.assets;
          const first={...clipFromAsset(a,0,'video'),end:.25};
          const second={...clipFromAsset(b,.25,'video'),start:.125,end:.375};
          const still={...clipFromAsset(photo,.5,'video'),end:.25,keys:{scale:[
            {time:0,value:1,mode:'ease-in-out'},{time:.21,value:1.15,mode:'linear'}]}};
          main.clips=[first,second,still];
          titleTrack.clips=[{...first,id:'test-title',assetId:null,kind:'title',position:.5,end:.25,
            text:'HDR',color:'white',fontScale:.12,titleFont:'arial',fadeIn:.12}];
          Object.assign(state.output,{width:128,height:72,fps:24,crf:15,preset:'ultrafast',encoder:'libx265',color});
          selectedId=second.id;redraw();save();await flushSave();
        }""",{'paths':list(map(str,files)),'color':CONTRACT})
        page.click('#boundaryBtn')
        page.fill('#boundaryFrames','4')
        page.click('#boundaryApply')
        page.wait_for_selector('.boundary-badge')
        page.click('#undoBtn')
        assert page.locator('.boundary-badge').count()==0
        page.click('#redoBtn')
        assert page.locator('.boundary-badge').count()==1
        page.click('.boundary-badge')
        assert page.locator('#boundaryFrames').input_value()=='4'
        page.locator('dialog[open] button[type="button"]').click()
        await_save=page.evaluate('flushSave()')
        assert await_save['output']['color']==CONTRACT
        timing_before=page.evaluate('duration()')
        for delivery,target in [('hdr10plus-master',master),('render',static)]:
            page.click('#exportBtn')
            page.wait_for_function("!$('startRender').disabled")
            page.select_option('#exportWorkflow',delivery)
            page.fill('#exportPath',str(target))
            with page.expect_response(lambda reply:reply.url.endswith('/api/export')) as submit:
                page.click('#startRender')
            assert submit.value.ok,submit.value.json()
            result=wait_export(page)
            assert result['status']=='done' and result['frames']==18,result
            page.locator('#exportModal .dialog-actions [data-close]').click()
        assert page.evaluate('duration()')==timing_before==.75
        assert not errors,errors
    assert decoded(static)==decoded(master)
    nits=luminance(master)
    np.testing.assert_allclose(nits[4:8,36,64],[200,400,600,800],rtol=.035)
    xml=ElementTree.fromstring(command('ffprobe','-v','error','-select_streams','v:0',
                                      '-show_frames','-of','xml',str(master)))
    frames=xml.findall('./frames/frame')
    assert len(frames)==18
    assert all(len(frame.findall(f"./side_data_list/side_data[@type='{SIDE_DATA}']"))==1 for frame in frames)
    with session(executable,results/'reopened',offline=True,project_path=project) as (page,_,__,errors):
        assert page.locator('.boundary-badge').count()==1
        assert page.evaluate("state.tracks[0].clips[0].titleFont")=='arial'
        assert not errors,errors
    assert [hashlib.sha256(path.read_bytes()).digest() for path in files]==hashes
    report={'frames':18,'equal_decoded_static_and_hdr10plus':True,'dynamic_blocks':18,
            'body_duration_seconds':.75,'undo_redo_reopen':True,'versions_match':True,
            'source_hashes_match':True}
    (results/'verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('executable',type=Path)
    parser.add_argument('results',type=Path)
    args=parser.parse_args()
    main(args.executable,args.results)
