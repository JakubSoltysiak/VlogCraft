"""Private read-only source reload after an owned renderer failure. Safe aliases only."""
import argparse,json,sys,time,traceback,urllib.request
from pathlib import Path
import psutil
from windows_session import session
from window_visibility import WindowVisibility

def main(a):
 sources=json.loads(a.manifest.read_text('utf8'));a.results=a.results.resolve()
 assert all(not a.results.is_relative_to(Path(s['path']).resolve().parent) for s in sources)
 a.results.mkdir(parents=True,exist_ok=True);rows=[]
 for n,source in enumerate(sources):
  folder=a.results/f'source-{n}';persisted=folder/'reopen.vlogcraft'
  with session(a.executable,folder,offline=True,project_path=persisted) as (first,proc,project,errors),WindowVisibility(proc,'visible') as visibility:
   page=first;origin=page.url.rstrip('/');endpoint=page._vlogcraft_cdp_endpoint;browser_type=page.context.browser.browser_type
   result=page.evaluate("path=>request('import','POST',{paths:[path],autoProxy:false})",source['path']);assert not result['errors'],'Private import failed'
   page.evaluate("""assets=>{stopPlayback();refreshPlayers();state.assets=assets;state.output.fps='60/1';useProxies=false;const a=assets[0],c=clipFromAsset(a,0,'video');c.end=6;c.audioDetached=true;state.tracks=[{id:uid(),type:'video',name:'Picture',volume:1,clips:[c]}];if(a.hasAudio){const s=clipFromAsset(a,0,'audio');s.end=6;state.tracks.push({id:uid(),type:'audio',name:'Sound',volume:1,clips:[s]});}playhead=0;redraw();save();return flushSave();}""",result['assets'])
   page.select_option('#playbackEngine','native');page.wait_for_function('nativeState.prepared&&nativeState.ack?.queued>=12000',timeout=45000)
   expected_hdr=page.evaluate('nativeState.hdr');page.evaluate('seek(2)');page.wait_for_timeout(500)
   page.evaluate("snapshot();state.name='Private recovery fixture';save();clearTimeout(saveTimer);saveTimer=null;recoverySettled()")
   epoch=page.evaluate("request('desktop/recovery')")['epoch']
   candidates=[p for p in psutil.Process(proc.pid).children(recursive=True) if p.name().lower()=='msedgewebview2.exe' and '--type=renderer' in p.cmdline()];assert len(candidates)==1
   candidates[0].terminate();deadline=time.monotonic()+35
   while time.monotonic()<deadline:
    with urllib.request.urlopen(origin+'/api/desktop/recovery',timeout=2) as response:status=json.load(response)
    if status['epoch']>epoch and status['phase']=='ready':break
    time.sleep(.1)
   assert status['epoch']>epoch and status['phase']=='ready','Private view recovery timeout'
   first._vlogcraft_intentional_detach=True
   try:page.context.browser.close()
   except Exception:pass
   browser=browser_type.connect_over_cdp(endpoint,no_defaults=True);page=next(p for p in browser.contexts[0].pages if p.url.startswith(origin))
   page.wait_for_function('nativeState.prepared&&nativeState.ack?.queued>=12000',timeout=30000)
   assert page.evaluate('state.name')=='Private recovery fixture';assert abs(page.evaluate('playhead')-2)<.05
   assert page.evaluate('nativeState.hdr')==expected_hdr,'Color contract changed during recovery'
   page.evaluate('seek(0)');page.wait_for_function('nativeState.ack?.queued>=12000',timeout=10000);page.evaluate('nativePlayPause()')
   page.wait_for_function('!isPlaying&&nativeState.ack?.finished',timeout=20000)
   data=page.evaluate('({samples:nativeState.ack.samples,underruns:nativeState.ack.underruns,hdr:nativeState.hdr})')
   assert data['samples']==288000 and data['underruns']==0 and not errors
   page.evaluate('nativeStop()');assert not page.evaluate("request('native/status')")['running']
   window_condition=visibility.finish();assert window_condition['condition_held'],'Private recovery lost its controlled visible condition'
   row={'alias':'Camera'+chr(65+n),'renderer_recovered':True,'draft_and_position_preserved':True,'color_contract_preserved':True,'HDR_linear':data['hdr'],'post_recovery_samples':data['samples'],'underruns':data['underruns'],'native_released':True,'window_condition':window_condition}
   rows.append(row);(a.results/'recovery-safe.json').write_text(json.dumps(rows,indent=2)+'\n',encoding='utf8');print(json.dumps({'alias':row['alias'],'private_recovery_passed':True}),flush=True)
  with session(a.executable,folder/'reopened',offline=True,project_path=persisted) as (page,proc,project,errors),WindowVisibility(proc,'visible') as visibility:
   assert page.evaluate('state.name')=='Private recovery fixture'
   page.select_option('#playbackEngine','native')
   # This project was saved at its end. Let initialization settle, then use
   # the real Play action, which rewinds an ended sequence before prebuffering.
   page.wait_for_function('!nativeState.busy',timeout=30000)
   page.evaluate('nativePlayPause()')
   page.wait_for_function('isPlaying&&nativeState.ack?.samples>0',timeout=30000)
   assert page.evaluate('nativeState.hdr')==expected_hdr
   page.wait_for_function('!isPlaying&&nativeState.ack?.finished',timeout=20000)
   assert page.evaluate('nativeState.ack.samples===288000&&nativeState.ack.underruns===0') and not errors
   page.evaluate('nativeStop()');assert not page.evaluate("request('native/status')")['running']
   rows[-1]['reopen_window_condition']=visibility.finish();assert rows[-1]['reopen_window_condition']['condition_held'],'Private reopened project lost its controlled visible condition'
  rows[-1]['new_host_reopen_and_playback']=True
  (a.results/'recovery-safe.json').write_text(json.dumps(rows,indent=2)+'\n',encoding='utf8')
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('executable',type=Path);p.add_argument('manifest',type=Path);p.add_argument('results',type=Path);a=p.parse_args()
 try:main(a)
 except BaseException as exc:
  a.results.mkdir(parents=True,exist_ok=True);(a.results/'failure-private.log').write_text(traceback.format_exc(),encoding='utf8')
  print(json.dumps({'private_recovery_passed':False,'error_type':type(exc).__name__}));raise SystemExit(1)
