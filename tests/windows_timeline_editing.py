"""Exercise real trim/zoom gestures and canvas persistence in the desktop editor."""
import argparse
import json
from pathlib import Path
import sys

from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'benchmarks')]
from windows_session import session


def main(executable,results):
    results=results.resolve()
    results.mkdir(parents=True,exist_ok=True)
    project=results/'editing.vlogcraft'
    paths=[]
    for number in range(32):
        path=results/f'fixture-{number:02d}.png'
        Image.new('RGB',(160,90),(20,80,100+number)).save(path)
        paths.append(str(path))
    with session(executable,results,offline=True,project_path=project) as (page,_,__,errors):
        imported=page.evaluate("paths=>request('import','POST',{paths,autoProxy:false})",paths)
        assert len(imported['assets'])==32 and not imported['errors']
        page.evaluate("""async ()=>{state=await request('state');
          const track=defaultTrack('video'),clip=clipFromAsset(state.assets[0],0,'video');
          clip.end=8;clip.x=.1;clip.scale=1.2;track.clips=[clip];selectedId=clip.id;
          state.output.fps=60;redraw();save();await flushSave();
        }""")
        page.select_option('#snapGrid','5')
        handle=page.locator('[data-handle=right]').first
        bounds=handle.bounding_box()
        x,y=bounds['x']+bounds['width']/2,bounds['y']+bounds['height']/2
        page.mouse.move(x,y)
        page.mouse.down()
        page.mouse.move(x+136,y,steps=9)  # 8 + 136/70 ≈ 9.94 seconds
        assert page.locator('#timelineSnapGuide').is_visible()
        assert '00:00:10:00' in page.locator('.clip-content small').first.text_content()
        page.mouse.up()
        clip_frames="frameIndex(lengthOf(state.tracks.flatMap(t=>t.clips)[0]))"
        assert page.evaluate(clip_frames)==600
        page.evaluate('restoreHistory(undoStack,redoStack)')
        assert page.evaluate(clip_frames)==480
        page.evaluate('restoreHistory(redoStack,undoStack)')
        assert page.evaluate(clip_frames)==600

        # Use a nonzero viewport scroll and a visible playhead as anchor.
        before=page.evaluate("""()=>{
          playhead=7;positionPlayhead();$('timelineScroller').scrollLeft=170;
          return 151+playhead*zoom-$('timelineScroller').scrollLeft;
        }""")
        page.click('#zoomIn')
        after=page.evaluate("151+playhead*zoom-$('timelineScroller').scrollLeft")
        assert abs(before-after)<=1,(before,after)

        page.click('[data-tab=project]')
        page.select_option('#sequenceAspect','9:16')
        assert page.evaluate('[state.output.width,state.output.height]')==[2160,3840]
        assert page.evaluate("Math.abs($('previewStage').getBoundingClientRect().width/$('previewStage').getBoundingClientRect().height-9/16)")<.02
        page.select_option('#sequenceAspect','custom')
        page.fill('#sequenceWidth','90')
        page.fill('#sequenceHeight','160')
        page.click('#applySequenceSize')
        assert page.evaluate('[state.output.width,state.output.height]')==[90,160]
        assert page.evaluate("state.tracks.flatMap(t=>t.clips).some(c=>c.x===.1&&c.scale===1.2)")
        page.evaluate('flushSave()')
        assert not errors,errors
    with session(executable,results/'reopen',offline=True,project_path=project) as (page,_,__,errors):
        assert page.evaluate('[state.output.width,state.output.height,state.assets.length]')==[90,160,32]
        assert page.evaluate("state.tracks.flatMap(t=>t.clips).some(c=>frameIndex(lengthOf(c))===600&&c.x===.1&&c.scale===1.2)")
        assert not errors,errors
    result={'linked_asset_count':32,'mouse_trim_frames':600,'live_guide':True,'undo_redo':True,
            'playhead_zoom_delta_pixels':abs(before-after),'portrait_and_custom_reopen':True,'transforms_preserved':True}
    (results/'timeline.json').write_text(json.dumps(result,indent=2),encoding='utf8')
    print(json.dumps(result))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('executable',type=Path)
    parser.add_argument('results',type=Path)
    args=parser.parse_args()
    main(args.executable,args.results)
