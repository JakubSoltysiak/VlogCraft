"""Verify the application exports an edited master through its normal dialog."""
import argparse
import json
from pathlib import Path
import sys
from fractions import Fraction
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'benchmarks'), str(ROOT/'tests')]
from windows_session import session
from windows_hdr10plus import wait_export
from test_hdr_color import project, source
from test_hdr10plus_master import verify_master
from render_engine import render
from app_version import VERSION


def main(executable, results):
    results = results.resolve()
    results.mkdir(parents=True, exist_ok=True)
    # Use generated, neutral-chroma sources for the independent Y-plane oracle.
    inputs = [source(results,'rec709',sdr=True), source(results,'pq',1000)]
    timeline = project(inputs)
    timeline['tracks'][0]['clips'][0].update(hdrExposure=1,fadeIn=.18)
    master = results/'Edytowany HDR żółć.mp4'
    static = results/'static.mp4'
    with session(executable,results,offline=True) as (page,_,__,errors):
        assert page.locator('[data-app-version]').all_text_contents() == [VERSION]*3
        page.evaluate("""async paths=>{
          const imported=await request('import','POST',{paths,autoProxy:false});
          if(imported.errors.length || imported.assets.length!==2)throw Error('Fixture import failed');
          state=await request('state');
          const [a,b]=imported.assets, [top,bottom]=state.tracks.filter(t=>t.type==='video');
          top.clips=[{...clipFromAsset(a,0,'video'),opacity:.5,hdrExposure:1,fadeIn:.18}];
          bottom.clips=[clipFromAsset(b,0,'video')];
          Object.assign(state.output,{width:128,height:72,fps:24,crf:15,preset:'ultrafast'});
          state.tracks=[top,bottom];
          redraw();save();await flushSave();
        }""",[a['path'] for a in inputs])
        saved = page.evaluate('JSON.stringify(state.output)')
        page.click('#exportBtn')
        page.wait_for_function("!$('startRender').disabled")
        page.select_option('#exportWorkflow','hdr10plus-master')
        assert page.locator('#encoderChoice').is_disabled()
        assert page.locator('#colorOutput').input_value()=='hdr10'
        page.locator('details').filter(has_text='Advanced encoding and color').locator('summary').first.click()
        page.locator('#colorSetup summary').click()
        page.select_option('#masteringGamut','2020')
        page.fill('#masteringMin','0.005')
        page.fill('#masteringMax','1000')
        page.fill('#maxCLL','1000')
        page.fill('#maxFALL','400')
        page.fill('#exportPath',str(master))
        with page.expect_response(lambda response:response.url.endswith('/api/export')) as submitted:
            page.click('#startRender')
        assert submitted.value.ok, submitted.value.json()
        result = wait_export(page)
        assert result['status']=='done' and result.get('frames')==12,result
        assert page.evaluate('JSON.stringify(state.output)')==saved
        assert not errors,errors
    render(timeline,static,results/'static-render')
    values = verify_master(unittest.TestCase(),static,master,Fraction(24),12)
    assert values[0] > values[-1]
    print(json.dumps({'frames':len(values),'video_audio_and_timing_match_static':True,
                      'dynamic_data_matches_each_decoded_picture':True,'project_output_preserved':True}))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('executable',type=Path)
    parser.add_argument('results',type=Path)
    args=parser.parse_args()
    main(args.executable,args.results)
