"""Exercise bounded real-camera HDR analysis without declaring a mastering display."""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tests')]
import hdr10plus_authoring
import hdr10plus_bitstream
import render_engine
import server
from test_hdr_color import project
from test_hdr10plus_export import command
from hdr10plus_index import SIDE_DATA


def main(manifest, results):
    results=results.resolve()
    results.mkdir(parents=True,exist_ok=False)
    rows=[]
    cameras=json.loads(manifest.read_text('utf-8'))[:2]
    for index, item in enumerate(cameras,1):
        original=Path(item['path'])
        asset=dict(id=f'camera-{index}',kind='video',name=f'Camera {index}',
                   path=str(original),**server.probe(original))
        w,h=(144,256) if abs(asset.get('rotation',0))%180==90 else (256,144)
        state=project([asset],w,h)
        state['output']['color']={k:v for k,v in state['output']['color'].items()
                                  if k not in ('mastering','maxCLL','maxFALL')}
        state['output'].update(fps=60,preset='ultrafast')
        clip=state['tracks'][0]['clips'][0]
        clip.update(start=.25,end=.45,hdrExposure=-.25,
                    inputColor={'profile':'source','range':'auto','pixelAspect':'square'})
        output=results/f'private-pq-{index}.mp4'
        start=time.monotonic()
        render_engine.render(state,output,results/f'render-{index}')
        render_seconds=time.monotonic()-start
        start=time.monotonic()
        count=0
        with hdr10plus_authoring.decoded_frames(output,w,h,lambda:False) as frames:
            for frame in frames:
                block=hdr10plus_bitstream.parse_payload(hdr10plus_authoring.payload(frame))
                assert not hdr10plus_bitstream.conformance_issues(block)
                count+=1
        delta=time.monotonic()-start
        decoded=json.loads(command('ffprobe','-v','error','-select_streams','v:0','-show_frames',
                                   '-of','json',str(output)))['frames']
        assert len(decoded)==count==12
        assert all(x['color_transfer']=='smpte2084' and
                   all(d['side_data_type'] not in (SIDE_DATA,'Mastering display metadata')
                       for d in x.get('side_data_list',[])) for x in decoded)
        rows.append({'camera':index,'trimmed_frames_analyzed':count,'analysis_seconds':delta,
                     'render_seconds':render_seconds,'width':w,'height':h,'fps':60,
                     'authored_delivery':False,'source_hdr10plus_copied':False})
    (results/'sanitized.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
    print(json.dumps(rows))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('manifest',type=Path)
    parser.add_argument('results',type=Path)
    args=parser.parse_args()
    main(args.manifest,args.results)
