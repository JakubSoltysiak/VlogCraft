"""One installed full-resolution HDR10 camera export; original media read-only."""
import argparse,json,re,sys,time,subprocess,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from windows_session import session
from test_hdr_color import probe,run
from tools.performance_record import fingerprint

def main(a):
 a.results=a.results.resolve();a.results.mkdir(parents=True,exist_ok=True);original=json.loads(a.manifest.read_text())[0];out=a.results/'camera-UHD-HDR10.mp4'
 with session(a.executable,a.results,offline=True) as (page,proc,project,errors):
  imported=page.evaluate("p=>request('import','POST',{paths:[p],autoProxy:false})",original['path']);assert not imported['errors']
  page.evaluate("""async assets=>{state.assets=assets;const c=clipFromAsset(assets[0],0,'video');c.end=.2;c.inputColor={profile:'source',range:'auto',pixelAspect:'square'};state.tracks=[{id:uid(),type:'video',name:'HDR',volume:1,clips:[c]}];state.output={width:2160,height:3840,fps:60,encoder:'libx265',crf:20,preset:'ultrafast',color:{version:1,workingSpace:'linear-rec2020-100nits',output:'hdr10',sdrWhiteNits:100}};save();await flushSave();}""",imported['assets'])
  began=time.perf_counter();page.evaluate("p=>request('export','POST',{path:p})",str(out));deadline=began+120
  while time.perf_counter()<deadline:
   status=page.evaluate("request('jobs')")['export']
   if status['status'] in ('done','error'):break
   page.wait_for_timeout(100)
  elapsed=time.perf_counter()-began;assert status['status']=='done',status;assert not errors
 p=probe(out);v=next(s for s in p['streams'] if s['codec_type']=='video');audio=next(s for s in p['streams'] if s['codec_type']=='audio');frames=[f for f in p['frames'] if f['media_type']=='video']
 assert (v['width'],v['height'],v['pix_fmt'],v['r_frame_rate'])==(2160,3840,'yuv420p10le','60/1') and len(frames)==12
 assert v['color_transfer']=='smpte2084' and v['color_primaries']=='bt2020';assert abs(float(audio['duration'])-.2)<1/48000
 # Code-domain comparison against independently decoded/auto-oriented original, no source frames saved.
 result=run(['ffmpeg','-hide_banner','-nostdin','-i',original['path'],'-i',str(out),'-filter_complex_threads','1','-lavfi',
  '[0:v]trim=end_frame=1,setpts=PTS-STARTPTS,format=yuv420p10le[a];[1:v]trim=end_frame=1,setpts=PTS-STARTPTS,format=yuv420p10le[b];[a][b]ssim','-an','-f','null','-'])
 text=result.stderr.decode(errors='replace');all_values=re.findall(r'All:([0-9.]+)',text);assert all_values,'No actual decoded SSIM result';ssim=float(all_values[-1]);assert ssim>.98,ssim
 report={'alias':'CameraA','source_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'source_fingerprint':fingerprint(),'host_sha256':hashlib.sha256(a.executable.read_bytes()).hexdigest(),
  'dimensions':[2160,3840],'rate':v['r_frame_rate'],'frames':len(frames),'pixel_format':v['pix_fmt'],'profile':v['profile'],'primaries':v['color_primaries'],'transfer':v['color_transfer'],'matrix':v['color_space'],'video_seconds':float(v['duration']),'audio_seconds':float(audio['duration']),'seconds':elapsed,'PQ_code_domain_SSIM_vs_original':ssim,
  'square_pixel_override':True,'scope':'12-frame full-resolution portrait HDR10 export and decoded PQ-code fidelity, not sustained performance, calibrated monitoring or HDR10+ authoring.'}
 (a.results/'color-uhd.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('executable',type=Path);p.add_argument('manifest',type=Path);p.add_argument('results',type=Path);main(p.parse_args())
