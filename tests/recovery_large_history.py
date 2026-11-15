"""Recover a large acknowledged draft and all eighty undo states after real view faults."""
import argparse,json,sys,time,urllib.request
from pathlib import Path
import psutil
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'benchmarks'))
from windows_session import session
from native_playback import SETUP
from window_geometry import alignment

def main(a):
 a.results=a.results.resolve();a.results.mkdir(parents=True,exist_ok=True);rows=[]
 with session(a.executable,a.results,offline=True) as (first,proc,project,errors):
  page=first;endpoint=page._vlogcraft_cdp_endpoint;browser_type=page.context.browser.browser_type;origin=page.url.rstrip('/')
  data=page.evaluate("paths=>request('import','POST',{paths,autoProxy:false})",[str((a.media/f'h264-4k60-{n}.mp4').resolve()) for n in range(3)])
  assert not data['errors'];page.evaluate(SETUP,{'assets':data['assets'],'seconds':125,'cut':.5})
  page.evaluate("async()=>{state.name='Large base';const c=state.tracks.find(t=>t.type==='video').clips[0];for(let n=0;n<80;n++){snapshot();c.opacity=n%2?.95:1;}redraw();save();await flushSave();await recoverySettled();}")
  page.select_option('#playbackEngine','native');page.wait_for_function('nativeState.prepared&&nativeState.ack?.queued>=12000',timeout=45000)
  for kind in ('renderer','browser'):
   page.evaluate('async()=>{await nativeState.busy;seek(2);if(nativeState.seekBusy)await nativeState.seekBusy;await flushSave();await recoverySettled();}')
   page.wait_for_function('!nativeState.seeking&&nativeState.ack?.queued>=12000',timeout=30000)
   old_name=page.evaluate('state.name');draft='Large durable '+kind
   page.evaluate("async name=>{snapshot();state.name=name;save();clearTimeout(saveTimer);saveTimer=null;await recoverySettled();}",draft)
   assert page.evaluate('recoveryAckSequence===recoverySequence&&undoStack.length===80')
   assert json.loads(project.read_text('utf8'))['name']!=draft,'Fixture accidentally published the unsaved draft'
   epoch=page.evaluate("request('desktop/recovery')")['epoch'];expected=page.evaluate("request('state')")
   digest="""async()=>{
    const canonical=v=>Array.isArray(v)?v.map(canonical):v&&typeof v==='object'?Object.fromEntries(Object.keys(v).sort().map(k=>[k,canonical(v[k])])):v;
    const text=JSON.stringify(canonical({undo:undoStack,redo:redoStack}));
    return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(text)))).map(v=>v.toString(16).padStart(2,'0')).join('');
   }"""
   history_digest=page.evaluate(digest)
   children=psutil.Process(proc.pid).children(recursive=True)
   target=next(p for p in children if p.name().lower()=='msedgewebview2.exe' and (('--type=renderer' in p.cmdline()) if kind=='renderer' else not any(x.startswith('--type=') for x in p.cmdline())))
   started=time.perf_counter();target.terminate();deadline=time.monotonic()+45
   while time.monotonic()<deadline:
    with urllib.request.urlopen(origin+'/api/desktop/recovery',timeout=2) as response:status=json.load(response)
    if status['epoch']>epoch and status['phase']=='ready':break
    time.sleep(.1)
   assert status['epoch']>epoch and status['phase']=='ready','Large history recovery did not finish'
   first._vlogcraft_intentional_detach=True
   try:page.context.browser.close()
   except Exception:pass
   browser=browser_type.connect_over_cdp(endpoint,no_defaults=True);page=next(p for p in browser.contexts[0].pages if p.url.startswith(origin));page.on('pageerror',lambda e:errors.append(str(e)))
   page.wait_for_function('nativeState.prepared&&nativeState.metrics?.completed_frames>0',timeout=30000)
   assert page.evaluate('state.name')==draft and page.evaluate('undoStack.length')==80 and not page.evaluate('isPlaying')
   assert page.evaluate(digest)==history_digest,'Recovered undo/redo snapshot content changed'
   assert abs(page.evaluate('playhead')-2)<.05;geometry=alignment(page,proc);assert max(geometry['absolute_error_pixels'])<=3
   page.locator('#undoBtn').click();assert page.evaluate('state.name')==old_name
   page.locator('#redoBtn').click();assert page.evaluate('state.name')==draft
   page.evaluate('async()=>{await nativeState.busy;await flushSave();await recoverySettled();}')
   # The project validator adds default track/clip fields on recovery. Compare
   # complete canonical project values rather than JSON property order.
   restored=page.evaluate("request('state')")
   assert restored['tracks']==expected['tracks'] and restored['output']==expected['output'] and restored['name']==draft
   rows.append({'injected':kind,'seconds':time.perf_counter()-started,'restored_undo_entries':80,'exact_all_history_content':True,'project_tracks_output_exact':True,'unsaved_draft':True,'undo_redo_exact':True,'paused_position':True,'physical_alignment_error_pixels':geometry['absolute_error_pixels']})
   (a.results/'large-recovery.json').write_text(json.dumps(rows,indent=2)+'\n',encoding='utf8')
  page.evaluate('nativeStop()');assert not errors
 print(json.dumps(rows),flush=True)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('executable',type=Path);p.add_argument('media',type=Path);p.add_argument('results',type=Path);main(p.parse_args())
