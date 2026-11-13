"""Cold range preparation vs current-range vs persisted-file reopen; generated CFR only."""
import argparse,json,time
from pathlib import Path
from windows_session import session
SETUP="""assets=>{
 stopPlayback();refreshPlayers();state.assets=assets;state.output.fps=60;useProxies=false;
 state.tracks=[{id:uid(),type:'video',name:'Original4K seek',volume:1,hidden:false,muted:false,locked:false,clips:[]}];
 assets.forEach((a,n)=>{const c=clipFromAsset(a,n*6,'video');c.start=0;c.end=6;c.volume=.25;state.tracks[0].clips.push(c);});
 selectedId=null;playhead=0;redraw();save();return flushSave();
}"""
def main(a):
 with session(a.executable,a.results) as (page,process,project,errors):
  data=page.evaluate("paths=>request('import','POST',{paths,autoProxy:false})",[str((a.media/f'h264-4k60-{n}.mp4').resolve()) for n in range(3)])
  assert not data['errors'],data
  page.evaluate(SETUP,data['assets']);page.wait_for_function("(async()=>{const j=await request('jobs');return j.readyAudio.length===3})()")
  page.evaluate("""()=>{window.seekRequests=[];const original=request;request=async(...args)=>{const v=await original(...args);if(args[0]==='preview')seekRequests.push({id:v.id,cacheHit:v.cacheHit,start:v.start,end:v.end});return v;};}""")
  begin=time.perf_counter();page.select_option('#playbackEngine','rendered')
  page.wait_for_function('renderedCurrent?.media.readyState>=2&&!renderedLoading&&!renderedCurrent.media.seeking')
  first=time.perf_counter()-begin;rows=[]
  for label,target in [('cold-range',9),('current-range',9.5),('cold-range',17),('current-range',17.5),('cached-file-reopen',9),('current-range',9.5),('cached-file-reopen',17)]:
   start=time.perf_counter();page.evaluate('at=>seek(at)',target)
   page.wait_for_function("""at=>renderedCurrent&&!renderedLoading&&renderedCurrent.media.readyState>=2&&!renderedCurrent.media.seeking
      &&at>=renderedCurrent.start&&at<renderedCurrent.end&&Math.abs(renderedCurrent.start+renderedCurrent.media.currentTime-at)<.002""",arg=target,timeout=180000)
   rows.append({'kind':label,'target_seconds':target,'seconds':time.perf_counter()-start})
  report={'initial_ready_seconds':first,'seeks':rows,'preview_requests':page.evaluate('seekRequests'),'source_files':3,
          'source_resolution':[3840,2160],'source_rate':'60/1','program_resolution':[960,540],'proxies':False,
          'endpoint':'program media loaded and seek complete; not physical screen display','browser_errors':errors}
  (a.results/'seek.json').write_text(json.dumps(report,indent=2));print(json.dumps(report),flush=True);assert not errors
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('executable',type=Path);p.add_argument('media',type=Path);p.add_argument('results',type=Path);main(p.parse_args())
