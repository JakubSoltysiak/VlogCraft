"""Installed color controls, real export and exact HDR history recovery; no manual QA."""
import argparse,base64,json,sys,time,urllib.request
from pathlib import Path
import numpy as np,psutil
from PIL import Image
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'benchmarks'),str(ROOT/'tests')]
from windows_session import session
from test_hdr_color import source,probe,run

def main(a):
 a.results=a.results.resolve();a.results.mkdir(parents=True,exist_ok=True);fixture=source(a.results,'installed-pq',1000);rows=[]
 with session(a.executable,a.results,offline=True) as (first,proc,project,errors):
  page=first;endpoint=page._vlogcraft_cdp_endpoint;browser_type=page.context.browser.browser_type;origin=page.url.rstrip('/')
  page.set_default_timeout(15000)
  imported=page.evaluate("p=>request('import','POST',{paths:[p],autoProxy:false})",str(Path(fixture['path']).resolve()));assert not imported['errors']
  page.evaluate("""assets=>{stopPlayback();refreshPlayers();state.assets=assets;state.tracks=[{id:uid(),type:'video',name:'HDR',volume:1,clips:[clipFromAsset(assets[0],0,'video')]}];state.output={width:128,height:72,fps:24,encoder:'libx265',preset:'ultrafast',crf:15,bitrate:0};state.tracks[0].clips[0].end=.5;selectedId=state.tracks[0].clips[0].id;redraw();save();return flushSave();}""",imported['assets'])
  # Start comparisons from the acknowledged canonical project, not omitted fixture defaults.
  page.evaluate("async()=>{state=await request('state');redraw();}")
  page.evaluate('openExport()');page.select_option('#colorOutput','hdr10')
  page.get_by_text('Advanced encoding and color',exact=True).click()
  page.locator('#colorSetup > summary').click()
  page.select_option('#masteringGamut','unknown');page.click('#applyColorSetup');page.wait_for_function("state.output.color?.output==='hdr10'");page.evaluate("closeModal('exportModal');flushSave()")
  page.wait_for_function("renderedCurrent?.media?.videoWidth===128&&$('programPreviewStatus').textContent.includes('SDR tone-mapped')",timeout=45000)
  assert page.evaluate("state.assets[0].colorMetadata.bitDepth===10")
  page.get_by_text('Technical input color',exact=True).click()
  page.click('#indexHdr10Plus')
  page.wait_for_function("$('hdr10PlusStatus').textContent.startsWith('No supported HDR10+ metadata detected')",timeout=15000)
  page.select_option('#inputPixelAspect','square');assert page.evaluate('state.tracks[0].clips[0].inputColor.pixelAspect')=='square'
  page.get_by_text('Technical input color',exact=True).click();page.select_option('#inputColorProfile','pq2020')
  page.get_by_text('Technical input color',exact=True).click();page.select_option('#inputColorRange','limited')
  page.get_by_text('Technical input color',exact=True).click()
  field=page.locator('[data-prop=hdrExposure]');field.fill('1');page.evaluate('flushSave()');assert page.evaluate('state.tracks[0].clips[0].hdrExposure')==1
  page.evaluate('restoreHistory(undoStack,redoStack)');assert page.evaluate('state.tracks[0].clips[0].hdrExposure||0')==0
  page.evaluate('restoreHistory(redoStack,undoStack);flushSave()');assert page.evaluate('state.tracks[0].clips[0].hdrExposure')==1
  path=a.results/'installed-HDR10.mp4';page.evaluate("p=>request('export','POST',{path:p})",str(path));deadline=time.monotonic()+60
  while time.monotonic()<deadline:
   status=page.evaluate("request('jobs')")['export']
   if status['status'] in ('done','error'):break
   page.wait_for_timeout(100)
  assert status['status']=='done',status
  p=probe(path);v=next(x for x in p['streams'] if x['codec_type']=='video');assert (v['pix_fmt'],v['color_transfer'],v['color_primaries'])==('yuv420p10le','smpte2084','bt2020');assert sum(x['media_type']=='video' for x in p['frames'])==12
  image=page.evaluate("request('program/frame','POST',{frame:0})")['image'];png=a.results/'monitor.png';png.write_bytes(base64.b64decode(image.split(',',1)[1]));reference=np.asarray(Image.open(png).convert('RGB'),float)
  chain='zscale=agamma=0:pin=2020:tin=smpte2084:min=2020_ncl:rin=limited:p=709:t=linear:m=gbr:r=full:npl=100,format=gbrpf32le,tonemap=hable:desat=0:peak=100,zscale=agamma=0:pin=709:tin=linear:min=gbr:rin=full:p=709:t=709:m=709:r=limited:npl=100,format=yuv420p'
  rgb=run(['ffmpeg','-v','error','-i',str(path),'-vf',chain,'-frames:v','1','-pix_fmt','rgb24','-f','rawvideo','pipe:1']).stdout;delta=float(np.abs(reference-np.frombuffer(rgb,np.uint8).reshape(72,128,3)).mean());assert delta<3,delta
  rows.append({'installed_HDR10_export':True,'color_UI_apply':True,'technical_input_overrides_UI':True,'input_bit_depth':10,'undo_redo_exposure':True,'SDR_monitor_label':True,'monitor_vs_tonemapped_delivery_MAE_8bit':delta,'decoded_frames':12})
  # Exercise gzip checkpoints with the new technical/creative/output data in every undo entry.
  page.evaluate("async()=>{const c=state.tracks[0].clips[0];c.inputColor={profile:'source',range:'auto',pixelAspect:'square'};for(let n=0;n<80;n++){snapshot();c.hdrExposure=n/40;}redraw();save();await flushSave();await recoverySettled();}")
  for role in ('renderer','browser'):
   name='HDR draft '+role
   page.evaluate("async name=>{snapshot();state.name=name;save();clearTimeout(saveTimer);saveTimer=null;await recoverySettled();}",name)
   expected=page.evaluate('({name:state.name,tracks:state.tracks,output:state.output,undo:undoStack,redo:redoStack,metadata:state.assets[0].colorMetadata})');assert len(expected['undo'])==80
   epoch=page.evaluate("request('desktop/recovery')")['epoch'];found=[]
   for child in psutil.Process(proc.pid).children(recursive=True):
    try:
     if child.name().lower()!='msedgewebview2.exe':continue
     kind=next((s.split('=',1)[1] for s in child.cmdline() if s.startswith('--type=')),'browser')
     if kind==role:found.append(child)
    except psutil.Error:pass
   assert len(found)==1;found[0].terminate();deadline=time.monotonic()+35
   while time.monotonic()<deadline:
    with urllib.request.urlopen(origin+'/api/desktop/recovery') as r:recovered=json.load(r)
    if recovered['epoch']>epoch and recovered['phase']=='ready':break
    time.sleep(.1)
   else:raise AssertionError('HDR view recovery timeout')
   first._vlogcraft_intentional_detach=True
   try:page.context.browser.close()
   except Exception:pass
   browser=browser_type.connect_over_cdp(endpoint,no_defaults=True);page=next(p for p in browser.contexts[0].pages if p.url.startswith('http://127.0.0.1:'))
   page.wait_for_function('name=>state&&state.name===name',arg=name,timeout=15000)
   actual=page.evaluate('({name:state.name,tracks:state.tracks,output:state.output,undo:undoStack,redo:redoStack,metadata:state.assets[0].colorMetadata})')
   (a.results/('expected-'+role+'.json')).write_text(json.dumps(expected));(a.results/('actual-'+role+'.json')).write_text(json.dumps(actual))
   assert actual==expected,'HDR project/history changed through recovery'
   assert page.evaluate('!isPlaying');rows.append({'fault':role,'exact_80_history_and_project_color':True,'source_metadata_exact':True,'draft_exact':True,'paused':True})
  assert not errors,errors
 (a.results/'windows-color.json').write_text(json.dumps(rows,indent=2));print(json.dumps(rows))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('executable',type=Path);p.add_argument('results',type=Path);main(p.parse_args())
