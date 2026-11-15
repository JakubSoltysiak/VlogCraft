"""An authorized FFmpeg export survives an isolated editor-renderer failure."""
import argparse,json,subprocess,sys,time,urllib.request
from pathlib import Path
import psutil
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'benchmarks'))
from windows_session import session
from native_playback import SETUP

def main(a):
 a.results=a.results.resolve();a.results.mkdir(parents=True,exist_ok=True);target=a.results/'background.mp4'
 with session(a.executable,a.results,offline=True) as (first,proc,project,errors):
  page=first;endpoint=page._vlogcraft_cdp_endpoint;origin=page.url.rstrip('/');kind=page.context.browser.browser_type
  data=page.evaluate("path=>request('import','POST',{paths:[path],autoProxy:false})",str((a.media/'h264-4k60-0.mp4').resolve()));assert not data['errors']
  page.evaluate(SETUP,{'assets':data['assets'],'seconds':12,'cut':.5});page.evaluate("state.output.preset='veryfast';state.output.bitrate=35;save();flushSave()")
  page.evaluate("path=>request('export','POST',{path})",str(target))
  assert page.evaluate("request('jobs')")['export']['status']=='rendering'
  page.evaluate("snapshot();state.name='Draft during export';save();clearTimeout(saveTimer);saveTimer=null;recoverySettled()")
  before=page.evaluate("request('desktop/recovery')")['epoch']
  renderers=[p for p in psutil.Process(proc.pid).children(recursive=True) if p.name().lower()=='msedgewebview2.exe' and '--type=renderer' in p.cmdline()];assert len(renderers)==1
  renderers[0].terminate();deadline=time.monotonic()+35
  while time.monotonic()<deadline:
   with urllib.request.urlopen(origin+'/api/desktop/recovery',timeout=2) as response:status=json.load(response)
   if status['epoch']>before and status['phase']=='ready':break
   time.sleep(.1)
  assert status['epoch']>before and status['phase']=='ready'
  first._vlogcraft_intentional_detach=True
  try:page.context.browser.close()
  except Exception:pass
  browser=kind.connect_over_cdp(endpoint,no_defaults=True);page=next(p for p in browser.contexts[0].pages if p.url.startswith(origin))
  assert page.evaluate('state.name')=='Draft during export'
  deadline=time.monotonic()+120
  while time.monotonic()<deadline:
   job=page.evaluate("request('jobs')")['export']
   if job['status']!='rendering':break
   page.wait_for_timeout(100)
  (a.results/'export-job.json').write_text(json.dumps(job,indent=2),encoding='utf8')
  assert job['status']=='done',job
  probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(target)]));video=next(s for s in probe['streams'] if s['codec_type']=='video')
  assert int(video['nb_frames'])==720 and video['avg_frame_rate']=='60/1' and (video['width'],video['height'])==(3840,2160)
  subprocess.run(['ffmpeg','-v','error','-i',str(target),'-f','null','-'],capture_output=True,check=True)
  assert not errors
  result={'renderer_recovered':True,'draft_preserved':True,'authorized_export_completed':True,'video_frames':720,'resolution':[3840,2160],'rate':'60/1','fully_decoded':True,'browser_errors':errors}
  (a.results/'background.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8');print(json.dumps(result),flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('executable',type=Path);p.add_argument('media',type=Path);p.add_argument('results',type=Path);main(p.parse_args())
