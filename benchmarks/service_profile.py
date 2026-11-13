"""Read-only source/probe/index/audio and controlled project-save stage measurements."""
import argparse,json,os,statistics,subprocess,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests'),str(ROOT/'benchmarks')]
import audio_cache,source_frames,waveform,server,project_store,timing
from engine_profile import asset
from performance import Resources
def timed(fn,repeat=3):
 rows=[]
 for _ in range(repeat):
  start=time.perf_counter();fn();rows.append(time.perf_counter()-start)
 return {'seconds':rows,'median_seconds':statistics.median(rows)}
def main(a):
 a.results.mkdir(parents=True,exist_ok=True)
 result={'file_cache_state':'uncontrolled; repeated warm-process measurements','source_bytes':a.large.stat().st_size}
 result['ffmpeg_process_start']=timed(lambda:subprocess.run(['ffmpeg','-version'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True),5)
 result['probe']=timed(lambda:server.probe(a.video),5)
 with tempfile.TemporaryDirectory(dir=a.results) as folder:
  root=Path(folder);v=asset(a.video)
  index=source_frames.FrameIndex(root/'pts')
  result['first_source_index']=timed(lambda:index.locate(v,0,0),1)
  result['warm_source_lookup']=timed(lambda:index.locate(v,2,0),20);index.close()
  large=dict(asset(a.large),hasAudio=True);cached=root/'audio.flac'
  meter=Resources(os.getpid());start=time.perf_counter();audio_cache.build(large,cached)
  result['audio_cache']={'seconds':time.perf_counter()-start,'resources':meter.finish(),'bytes':cached.stat().st_size}
  reference=root/'from-original.png'
  result['waveform_original']=timed(lambda:(reference.unlink(missing_ok=True),waveform.build(large,reference)))
  copy=root/'from-flac.png';preview={**large,'path':str(cached)}
  result['waveform_flac']=timed(lambda:(copy.unlink(missing_ok=True),waveform.build(preview,copy)))
  result['waveform_same_bytes']=reference.read_bytes()==copy.read_bytes()
  s=server.default_state();s['assets']=[v];s['output']['fps']=60
  for n in range(1500):
   clip=server.default_clip(v,n*.4);clip.update(id=f'{n+100:032x}',end=.4);s['tracks'][1]['clips'].append(clip)
  result['serialize_1500']=timed(lambda:timing.encode(s))
  doc=timing.encode(s);project=root/'profile.vlogcraft'
  result['save_1500']=timed(lambda:project_store.save(project,doc,server.validate_document))
  result['project_bytes']=project.stat().st_size
 (a.results/'services.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('video',type=Path);p.add_argument('large',type=Path);p.add_argument('results',type=Path);main(p.parse_args())
