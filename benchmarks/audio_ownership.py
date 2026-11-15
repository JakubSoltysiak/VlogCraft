"""Controlled seek/stop ownership diagnostic. GC is diagnostic only, outside playback."""
import argparse,json
from pathlib import Path
from windows_session import session
from native_playback import SETUP

def main(a):
 with session(a.executable,a.results,offline=True) as (page,proc,project,errors):
  cdp=page.context.new_cdp_session(page);events={'created':0,'destroyed':0};nodes=set()
  def created(e):
   if 'worklet' in e['node']['nodeType'].lower():nodes.add(e['node']['nodeId']);events['created']+=1
  def destroyed(e):
   if e['nodeId'] in nodes:nodes.discard(e['nodeId']);events['destroyed']+=1
  cdp.on('WebAudio.audioNodeCreated',created);cdp.on('WebAudio.audioNodeWillBeDestroyed',destroyed);cdp.send('WebAudio.enable')
  data=page.evaluate("paths=>request('import','POST',{paths,autoProxy:false})",[str((a.media/'h264-4k60-0.mp4').resolve())]);assert not data['errors']
  page.evaluate(SETUP,{'assets':data['assets'],'seconds':30,'cut':.5});page.select_option('#playbackEngine','native')
  page.wait_for_function('nativeState.prepared&&nativeState.ack?.queued>=12000',timeout=30000)
  def wrappers():
   cdp.send('HeapProfiler.collectGarbage');page.wait_for_timeout(150)
   proto=cdp.send('Runtime.evaluate',{'expression':'AudioWorkletNode.prototype','objectGroup':'ownership'})['result']['objectId']
   group=cdp.send('Runtime.queryObjects',{'prototypeObjectId':proto,'objectGroup':'ownership'})['objects']['objectId']
   count=cdp.send('Runtime.callFunctionOn',{'objectId':group,'functionDeclaration':'function(){return this.length}','returnByValue':True})['result']['value']
   cdp.send('Runtime.releaseObjectGroup',{'objectGroup':'ownership'});return count
  before=wrappers()
  for n in range(a.repeat):
   page.evaluate('frame=>nativeSeek(frame)',(n%10)*30)
   page.wait_for_function('nativeState.ack?.queued>=12000',timeout=10000)
  after=wrappers();page.evaluate('nativeStop()');stopped=wrappers()
  result={'diagnostic_only':True,'seek_cycles':a.repeat,'JS_worklet_wrappers':{'before':before,'after_seeks':after,'after_stop':stopped},'native_audio_events':events,'graph_worklets_remaining':len(nodes),'browser_errors':errors}
  (a.results/'ownership.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8');print(json.dumps(result),flush=True);assert not errors
  if a.expect_disposed:
   assert after==1 and stopped==0 and not nodes,'Replaced/stopped worklets remain owned'
   assert events['created']==events['destroyed'],'Audio graph did not release every created worklet'
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('executable',type=Path);p.add_argument('media',type=Path);p.add_argument('results',type=Path);p.add_argument('--repeat',type=int,default=20);p.add_argument('--expect-disposed',action='store_true');main(p.parse_args())
