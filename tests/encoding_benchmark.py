"""Compare complete CPU and AMF exports of identical decoded 4K60 material."""
import json
from pathlib import Path
import subprocess
import sys
import time
import os

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import encoders
import render_engine
import server
from performance import Resources


def main(source,results):
    results.mkdir(parents=True,exist_ok=True)
    a=dict(id='a'*32,kind='video',name=source.name,path=str(source),size=source.stat().st_size,**server.probe(source))
    state=server.default_state();state['assets']=[a]
    c=server.default_clip(a);c['end']=3
    state['tracks'][1]['clips']=[c]
    state['output'].update(width=3840,height=2160,fps=60,bitrate=35,preset='veryfast')
    results_data={}
    available=encoders.available()
    for encoder in ('libx264','h264_amf'):
        if encoder not in available:
            results_data[encoder]={'unavailable':True};continue
        state['output']['encoder']=encoder
        dest=results/(encoder+'.mp4')
        resources=Resources(os.getpid(),gpu=True)
        start=time.monotonic()
        render_engine.render(state,dest,results/('job-'+encoder))
        elapsed=time.monotonic()-start
        measured=resources.finish()
        streams=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(dest)]))['streams']
        v=next(s for s in streams if s['codec_type']=='video')
        assert (v['width'],v['height'],v['r_frame_rate'],v['nb_frames'])==(3840,2160,'60/1','180'),v
        subprocess.run(['ffmpeg','-nostdin','-v','error','-i',str(dest),'-f','null','-'],check=True)
        results_data[encoder]={'seconds':round(elapsed,3),'encoding_fps':round(180/elapsed,2),
            'video_frames':180,'file_bytes':dest.stat().st_size,'resources':measured}
        print(json.dumps({encoder:results_data[encoder]}),flush=True)
    (results/'encoding.json').write_text(json.dumps(results_data,indent=2))


if __name__=='__main__':
    main(Path(sys.argv[1]).resolve(),Path(sys.argv[2]).resolve())
