"""Measure timeline/UI work independently from playback on 1500 real clips."""
import argparse,json,statistics,time
from pathlib import Path
from corpus import distinct,SETUP
from windows_session import session
MEASURE="""async ()=>{
 const records={};
 const collect=async(name,fn)=>{
  const cpu=[],paint=[];
  for(let n=0;n<30;n++){const start=performance.now();fn(n);cpu.push(performance.now()-start);await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));paint.push(performance.now()-start);}
  const stats=a=>{a.sort((x,y)=>x-y);return {median:a[15],p95:a[28],max:a[29]};};
  records[name]={synchronous_ms:stats(cpu),through_next_frame_ms:stats(paint)};
 };
 await collect('interval_index',()=>rebuildIndex());
 await collect('visible_timeline',()=>renderTimeline(true));
 await collect('clip_selection',n=>select(state.tracks[0].clips[n].id));
 await collect('zoom',n=>{zoom=40+(n%4)*20;renderTimeline();});
 await collect('scroll',n=>{$('timelineScroller').scrollLeft=(n%6)*3000;renderTimeline(true);});
 await collect('media_library',()=>renderAssets());
 await collect('inspector',()=>renderInspector());
 return {operations:records,clips:state.tracks.flatMap(t=>t.clips).length,assets:state.assets.length,
         sequence_seconds:duration(),visible_clip_nodes:document.querySelectorAll('[data-clip]').length,
         dpr:devicePixelRatio,viewport:[innerWidth,innerHeight]};
}"""
def main(a):
 paths=distinct(a.media)
 with session(a.executable,a.results) as (page,process,project,errors):
  start=time.perf_counter()
  response=page.evaluate("paths=>request('import','POST',{paths,autoProxy:false})",[str(p) for p in paths])
  assert not response['errors'],response
  page.evaluate(SETUP,response['assets'])
  page.wait_for_function("(async()=>{const j=await request('jobs');return j.readyAudio.length===32})()")
  page.wait_for_timeout(1500)
  settled=time.perf_counter()-start
  data=page.evaluate(MEASURE);assert data['clips']==1500 and data['assets']==32,data
  assert not errors,errors
  data['import_and_cache_settle_seconds']=settled
  data['browser_errors']=errors;data['sources']='32 independent allocated generated 720p60 H264/AAC, 2 seconds each'
  (a.results/'ui.json').write_text(json.dumps(data,indent=2));print(json.dumps(data),flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('executable',type=Path);p.add_argument('media',type=Path);p.add_argument('results',type=Path);main(p.parse_args())
