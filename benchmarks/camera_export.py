"""Private original-media export check. Explicit SDR delivery, never HDR qualification."""
import argparse,json,subprocess,time,traceback
from pathlib import Path
from engine_profile import scene,Runner
import render_engine

def main(a):
 rows=json.loads(a.manifest.read_text('utf8'));a.results=a.results.resolve()
 if any(a.results.is_relative_to(Path(r['path']).resolve().parent) for r in rows):
  raise ValueError('Results must stay outside original media directories')
 a.results.mkdir(parents=True,exist_ok=True);results=(json.loads((a.results/'exports-safe.json').read_text('utf8')) if a.verify_existing and (a.results/'exports-safe.json').exists() else [])
 for n,row in enumerate(rows):
  if a.source_index is not None and n!=a.source_index:continue
  folder=a.results/f'source-{n}';folder.mkdir(exist_ok=a.verify_existing);target=folder/'explicit-sdr.mp4'
  state=scene([Path(row['path'])],1,3840,1);runner=Runner();began=time.perf_counter()
  if not a.verify_existing:render_engine.render(state,target,folder,popen=runner)
  else:assert target.is_file(),'No retained export to verify'
  seconds=time.perf_counter()-began
  probe=subprocess.run(['ffprobe','-v','error','-count_frames','-show_streams','-of','json',str(target)],capture_output=True,check=True)
  video=next(s for s in json.loads(probe.stdout)['streams'] if s['codec_type']=='video')
  decoded=subprocess.run(['ffmpeg','-v','error','-i',str(target),'-f','null','-'],capture_output=True)
  (folder/'decode-private.log').write_bytes(decoded.stderr)
  assert decoded.returncode==0 and int(video['nb_read_frames'])==60
  assert (video['width'],video['height'])==(3840,2160) and video['avg_frame_rate']=='60/1'
  assert video['pix_fmt'] in ('yuv420p','yuvj420p') and video.get('color_transfer') not in ('smpte2084','arib-std-b67')
  result={'alias':'Camera'+chr(65+n),'export_seconds':None if a.verify_existing else seconds,'verification_reuses_existing':a.verify_existing,'output_frames':60,'output_resolution':[3840,2160],
          'output_rate':'60/1','decoded':True,'delivery':'Explicit existing 8bit SDR reference exporter; HDR mastering unqualified'}
  results=[r for r in results if r['alias']!=result['alias']];results.append(result);(a.results/'exports-safe.json').write_text(json.dumps(results,indent=2)+'\n',encoding='utf8')
  print(json.dumps({'alias':result['alias'],'export_decoded':True,'output_frames':60}),flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('manifest',type=Path);p.add_argument('results',type=Path);p.add_argument('--source-index',type=int,choices=range(3));p.add_argument('--verify-existing',action='store_true');a=p.parse_args()
 try:main(a)
 except BaseException as exc:
  a.results.mkdir(parents=True,exist_ok=True)
  (a.results/'failure-private.log').write_text(traceback.format_exc(),encoding='utf8')
  print(json.dumps({'private_export_qualification':False,'error_type':type(exc).__name__}))
  raise SystemExit(1)
