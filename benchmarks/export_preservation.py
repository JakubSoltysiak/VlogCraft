"""Alternating packaged original-UHD exports, unchanged settings, full decode and SSIM."""
import argparse,json,re,statistics,subprocess,time
from pathlib import Path
from windows_session import session
from conditions import Conditions

def main(a):
 a.results=a.results.resolve();a.results.mkdir(parents=True,exist_ok=True);rows=[]
 source=(a.media/'h264-4k60-0.mp4').resolve()
 for n in range(a.repeat):
  arms=[('baseline',a.baseline),('candidate',a.candidate)]
  if n%2:arms.reverse()
  for arm,exe in arms:
   folder=a.results/f'{n}-{arm}';target=folder/'output.mp4'
   with session(exe,folder,offline=True) as (page,proc,project,errors):
    data=page.evaluate("path=>request('import','POST',{paths:[path],autoProxy:false})",str(source));assert not data['errors']
    page.evaluate("""assets=>{stopPlayback();refreshPlayers();state.assets=assets;state.tracks=[];const c=clipFromAsset(assets[0],0,'video');c.end=3;c.volume=.25;state.tracks.push({id:uid(),type:'video',name:'Picture',volume:1,clips:[c]});state.output={width:3840,height:2160,fps:60,crf:20,preset:'veryfast',encoder:'libx264',bitrate:35};redraw();save();return flushSave();}""",data['assets'])
    conditions=Conditions();began=time.perf_counter();page.evaluate("path=>request('export','POST',{path})",str(target))
    while True:
     status=page.evaluate("request('jobs')");job=status['export']
     if job['status'] in ('done','error','cancelled'):break
     page.wait_for_timeout(50)
    elapsed=time.perf_counter()-began;observed_conditions=conditions.finish();assert job['status']=='done',job
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(target)]));video=next(s for s in probe['streams'] if s['codec_type']=='video')
    assert (video['width'],video['height'],video['avg_frame_rate'],int(video['nb_frames']))==(3840,2160,'60/1',180)
    audio=next(s for s in probe['streams'] if s['codec_type']=='audio')
    assert audio['codec_name']=='aac' and int(audio['sample_rate'])==48000
    av_end_difference=abs(float(audio['duration'])-float(video['duration']))
    assert av_end_difference<.05 and abs(float(audio.get('start_time',0))-float(video.get('start_time',0)))<.05
    subprocess.run(['ffmpeg','-v','error','-i',str(target),'-f','null','-'],check=True,capture_output=True)
    q=subprocess.run(['ffmpeg','-v','info','-i',str(source),'-i',str(target),'-lavfi','ssim=shortest=1','-an','-f','null','-'],capture_output=True,text=True,check=True)
    similarity=float(re.findall(r'All:([0-9.]+)',q.stderr)[-1]);assert similarity>.997
    assert not errors
    rows.append({'arm':arm,'repeat':n,'seconds':elapsed,'frames':180,'rate':'60/1','decoded':True,'SSIM_vs_source':similarity,
                 'audio_codec':audio['codec_name'],'audio_sample_rate':int(audio['sample_rate']),'AV_endpoint_difference_seconds':av_end_difference,'conditions':observed_conditions})
   (a.results/'exports.json').write_text(json.dumps({'rows':rows},indent=2)+'\n',encoding='utf8')
 summary={arm:{'median_seconds':statistics.median(r['seconds'] for r in rows if r['arm']==arm),'worst_seconds':max(r['seconds'] for r in rows if r['arm']==arm)} for arm in ('baseline','candidate')}
 (a.results/'exports.json').write_text(json.dumps({'settings':{'codec':'libx264','resolution':[3840,2160],'fps':'60/1','preset':'veryfast','bitrate_Mbps':35,'crf':20},'rows':rows,'summary':summary},indent=2)+'\n',encoding='utf8');print(json.dumps(summary),flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('baseline',type=Path);p.add_argument('candidate',type=Path);p.add_argument('media',type=Path);p.add_argument('results',type=Path);p.add_argument('--repeat',type=int,default=3);main(p.parse_args())
