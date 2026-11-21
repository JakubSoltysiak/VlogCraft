"""Exercise the HDR10+ preservation choice in the installed Windows editor."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'benchmarks'),str(ROOT/'tests')]
from windows_session import session
from test_hdr10plus_export import command, decoded, fixture
from hdr10plus_index import SIDE_DATA


def wait_export(page):
    end=time.monotonic()+35
    while time.monotonic()<end:
        result=page.evaluate("request('jobs')")['export']
        if result['status'] in ('done','error','cancelled'):
            return result
        time.sleep(.12)
    raise TimeoutError('HDR10+ GUI export did not complete')


def main(executable,results):
    results=results.resolve()
    results.mkdir(parents=True,exist_ok=True)
    source=fixture(results)
    output=results/'Kopia HDR żółć.mp4'
    original=hashlib.sha256(source.read_bytes()).digest()
    with session(executable,results,offline=True) as (page,_,__,errors):
        page.evaluate("""async p=>{
          const imported=await request('import','POST',{paths:[p],autoProxy:false});
          if(imported.errors.length||imported.assets.length!==1)throw Error('Fixture import failed');
          state=await request('state');
          const track=defaultTrack('video');
          const clip=clipFromAsset(imported.assets[0],0,'video');
          track.clips=[clip];state.output.width=128;state.output.height=72;state.output.fps=24;
          selectedId=clip.id;redraw();save();await flushSave();
        }""",str(source))
        saved=page.evaluate('JSON.stringify(state.output)')
        page.click('#exportBtn')
        page.wait_for_function("!$('startRender').disabled")
        page.select_option('#exportWorkflow','hdr10plus-copy')
        page.fill('#exportPath',str(output))
        page.click('#startRender')
        result=wait_export(page)
        assert result['status']=='done' and result['frames']==12,result
        assert page.evaluate('JSON.stringify(state.output)')==saved
        assert not errors,errors
    assert hashlib.sha256(source.read_bytes()).digest()==original
    assert decoded(source)==decoded(output)
    frames=json.loads(command('ffprobe','-v','error','-select_streams','v:0','-show_frames',
                              '-of','json',str(output)))['frames']
    assert [next(d['average_maxrgb'] for d in f['side_data_list'] if d['side_data_type']==SIDE_DATA)
            for f in frames]==[f'{1000+n*100}/100000' for n in range(12)]
    record={'frames':len(frames),'exact_decoded_video_and_audio':True,'metadata_per_frame':True,
            'seconds':result.get('elapsedSeconds'),'source_unchanged':True,'project_settings_unchanged':True}
    (results/'verification.json').write_text(json.dumps(record,indent=2),encoding='utf8')
    print(json.dumps(record))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('executable',type=Path)
    parser.add_argument('results',type=Path)
    args=parser.parse_args()
    main(args.executable,args.results)
