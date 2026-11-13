"""600-second/1500-clip decoded render stress; intentionally 320x180 SDR, not 4K."""
import argparse,hashlib,json,os,subprocess,sys,time
from pathlib import Path
from corpus import distinct
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
import server,render_engine,timing
from performance import Resources
def main(a):
 a.results.mkdir(parents=True,exist_ok=True)
 paths=distinct(a.media);originals={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
 s=server.default_state();s['assets']=[dict(id=f'{i+1:032x}',kind='video',path=str(p),name=p.name,size=p.stat().st_size,**server.probe(p)) for i,p in enumerate(paths)]
 s['tracks']=[server.make_track('video',1),server.make_track('audio',1)]
 s['output'].update(width=320,height=180,fps=60,encoder='libx264',preset='ultrafast',bitrate=0,crf=26)
 for n in range(1200):
  c=server.default_clip(s['assets'][n%32]);c.update(position=n*.5,start=(n%3)*.5,end=(n%3)*.5+.5,audioDetached=True)
  s['tracks'][0]['clips'].append(c)
 for n in range(300):
  c=server.default_clip(s['assets'][(n*7)%32],n*2,'audio');c.update(start=0,end=2,volume=.3)
  s['tracks'][1]['clips'].append(c)
 s=server.validate_state(s,s)
 started=time.perf_counter();resources=Resources(os.getpid(),gpu=True);last=[0]
 def progress(percent,message):
  if percent>=last[0]+5:
   print(json.dumps({'percent':percent,'elapsed_seconds':time.perf_counter()-started}),flush=True);last[0]=percent
 target=a.results/'long.mp4'
 render_engine.render(s,target,a.results/'work',on_progress=progress)
 elapsed=time.perf_counter()-started;measured=resources.finish()
 probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-count_frames','-show_streams','-of','json',str(target)]))
 video=next(v for v in probe['streams'] if v['codec_type']=='video');audio=next(v for v in probe['streams'] if v['codec_type']=='audio')
 # Decode the whole soundtrack and count actual stereo float sample frames, bounded memory.
 process=subprocess.Popen(['ffmpeg','-v','error','-i',str(target),'-vn','-ac','2','-ar','48000','-f','f32le','-'],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
 size=0
 while block:=process.stdout.read(1024*1024):size+=len(block)
 assert process.wait()==0,process.stderr.read().decode(errors='replace')
 subprocess.run(['ffmpeg','-v','error','-i',str(target),'-an','-f','null','-'],capture_output=True,check=True,timeout=240)
 expected=timing.sample_at(36000,timing.rate(60));samples=size//8
 result={'timeline_seconds':600,'timeline_clips':1500,'distinct_source_files':32,'source_resolution':[1280,720],
         'output_resolution':[320,180],'rate':'60/1','seconds':elapsed,'decoded_video_frames':int(video['nb_read_frames']),
         'decoded_audio_sample_frames':samples,'expected_audio_samples':expected,
         'audio_end_error_seconds':(samples-expected)/48000,'audio_stream_duration':audio.get('duration'),
         'file_bytes':target.stat().st_size,'resources':measured,'source_sha256_unchanged':all(hashlib.sha256(p.read_bytes()).hexdigest()==h for p,h in originals.items()),
         'qualification':'frame/sample counts and complete decoding; not acoustic synchronization or 4K endurance'}
 (a.results/'render.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)
 assert result['source_sha256_unchanged']
 assert result['decoded_video_frames']==36000
 # AAC decoder may expose one padded final codec frame; no unbounded segment drift.
 assert abs(samples-expected)<=1024
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('media',type=Path);p.add_argument('results',type=Path);main(p.parse_args())
