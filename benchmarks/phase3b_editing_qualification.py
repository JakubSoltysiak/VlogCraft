"""Opt-in Windows editing endurance; run only after the short playback gates."""
import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import sys
import time

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'benchmarks'), str(ROOT/'tests')]
from conditions import Conditions
from gpu_metrics import GPU
from memory_metrics import analyze, slope
from native_playback import SETUP
from observer_memory import groups
from phase3b_scrub import drag
from runtime_trace import RuntimeTrace
from window_visibility import WindowVisibility
from windows_session import session

# Hash snapshots individually OUTSIDE the measured interval. Serializing all 80
# at once would create a large observer allocation that distorts idle recovery.
HASH_TOOLS = """() => {
 const canonical = value => Array.isArray(value) ? value.map(canonical) :
  value && typeof value === 'object' ?
  Object.fromEntries(Object.keys(value).sort().map(k => [k,canonical(value[k])])) : value;
 window.qaDigest = async value => {
  const bytes=new TextEncoder().encode(JSON.stringify(canonical(value)));
  const hash=await crypto.subtle.digest('SHA-256',bytes);
  return Array.from(new Uint8Array(hash),c=>c.toString(16).padStart(2,'0')).join('');
 };
 window.qaDoc=()=>({tracks:state.tracks,output:state.output,name:state.name});
}"""
HISTORY = """async () => {
 const one = async stack => { const result=[];for(const value of stack)result.push(await qaDigest(value));return result; };
 return {undo:await one(undoStack),redo:await one(redoStack)};
}"""
EDIT = """async n => {
 const videos=state.tracks.filter(t=>t.type==='video'), layer=(n-1)%videos.length;
 const target=(n*7)%110, clip=videos[layer].clips[Math.floor(target/.5)];
 seek(target);selectedId=clip.id;renderInspector();
 $('timelineScroller').scrollLeft=(n%8)*180;
 if(!sel()||sel().clip.id!==clip.id)throw Error('Clip selection failed');
 // Mirror real slider focus (one snapshot), input, and blur handlers.
 const slider=document.querySelector('#inspectorContent [data-prop="opacity"]');
 const opacity=clip.opacity===.95?.94:.95;
 slider.focus();slider.value=opacity;slider.dispatchEvent(new Event('input',{bubbles:true}));slider.blur();
 if(clip.opacity!==opacity)throw Error('Opacity edit failed');
 const result={layer,opacity,curve:false,source_visibility:false,undo_redo:false};
 if(n%4===0){
  $('curveProperty').value='scale';$('curveProperty').dispatchEvent(new Event('change'));
  const time=clip.start+.25,value=1+(n%13)/100,keys=clip.keys?.scale||[];
  const idx=keys.findIndex(k=>Math.abs(k.time-time)<1e-8);
  $('curveKeyList').value=idx<0?'':String(idx);
  $('curveTime').value=time;$('curveValue').value=value;$('curveMode').value='linear';$('keySet').click();
  if(!clip.keys?.scale?.some(k=>k.time===time&&k.value===value))throw Error('Keyframe edit failed');
  result.curve=true;
 }
 if(n%5===0){
  const track=videos[0],previous=!!track.hidden;
  document.querySelector('[data-track-action="hidden"][data-track="'+CSS.escape(track.id)+'"]').click();
  if(!!track.hidden===previous)throw Error('Source visibility did not change');
  result.source_visibility=true;
 }
 if(n%6===0){
  const depth=undoStack.length,latest=await qaDigest(qaDoc()),prior=await qaDigest(undoStack.at(-1));
  if(latest===prior)throw Error('Expected a real edit for undo');
  $('undoBtn').click();
  if(undoStack.length!==depth-1||await qaDigest(qaDoc())!==prior)throw Error('Undo contents changed');
  $('redoBtn').click();
  if(undoStack.length!==depth||redoStack.length!==0||await qaDigest(qaDoc())!==latest)throw Error('Redo contents changed');
  result.undo_redo=true;
 }
 await flushSave();
 return {...result,undo:undoStack.length,redo:redoStack.length};
}"""
STATE = """() => {
 const m=nativeState.metrics||{},a=nativeState.ack||{};
 return {playing:isPlaying,engine:$('playbackEngine').value,gen:a.generation,samples:a.samples,
  underruns:a.underruns,queued_pcm_frames:a.queued,worklet_connected:!!nativeState.node,
  queued_pcm_float_payload_bytes:a.queued==null?null:a.queued*2*Float32Array.BYTES_PER_ELEMENT,
  program_width:$('programResolution').value,sequence_frame:m.sequence_frame,
  current_decoders:m.decoder_statistics?.map(v=>({queue:v.queued_frames,warm:v.warm_cache_frames,
   fixed_pool_frames:v.hardware_pool_frames})),gpu_slots:m.gpu_slot_budget,
  decoder_texture_estimate_MiB:m.retained_texture_estimated_MiB,
  standby_budget_bytes:m.standby_surface_budget_bytes,retained_surface_views:m.retained_surface_views,
  undo:undoStack.length,redo:redoStack.length};
}"""


def write(path, data):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, indent=2)+'\n', encoding='utf-8')
    tmp.replace(path)


def webview_roles(proc):
    roles={}
    for p in psutil.Process(proc.pid).children(recursive=True):
        try:
            if p.name().lower()!='msedgewebview2.exe':
                continue
            role=next((v.split('=',1)[1] for v in p.cmdline() if v.startswith('--type=')),'browser')
            role=role if role in ('browser','renderer','gpu-process','utility') else 'other'
            memory=p.memory_info()
            row=roles.setdefault(role,dict(processes=0,rss_MiB=0,private_commit_MiB=0))
            row['processes']+=1
            row['rss_MiB']+=memory.rss/2**20
            row['private_commit_MiB']+=getattr(memory,'private',memory.vms)/2**20
        except psutil.Error:
            pass
    return roles


def pause_and_read(page):
    before=page.evaluate(STATE)
    assert before['playing'] and before['engine']=='native', 'Unexpected transport stop or fallback'
    page.evaluate('stopPlayback()')
    # Receive a post-pause worklet acknowledgement before seeking/disposing.
    page.wait_for_timeout(100)
    after=page.evaluate(STATE)
    assert after['gen']==before['gen'] and after['samples']>=before['samples'] and after['samples']>0
    return {'generation':after['gen'],'samples':after['samples'],'underruns':after['underruns']}


def start(page):
    page.evaluate('nativePlayPause()')
    page.wait_for_function("isPlaying && nativeSelected() && nativeState.ack?.samples>0 && "
                           "nativeState.metrics?.selected?.length===state.tracks.filter(t=>t.type==='video'&&!t.hidden).length",
                           timeout=30000)


def read_project(project):
    value=json.loads(project.read_text(encoding='utf-8'))
    # 'updated' is the save timestamp. All project content, assets and schema remain in the comparison.
    value.pop('updated',None)
    return value


def run(args):
    out=args.results.resolve()
    out.mkdir(parents=True,exist_ok=False)
    seconds=90 if args.smoke else 1800
    idle=15 if args.smoke else 60
    project=out/'editing.vlogcraft'
    result=dict(mode='phase3b_editing_smoke' if args.smoke else 'phase3b_editing_1800s',
                seconds=seconds,timeline_seconds=125,forced_gc=False,natural_idle_seconds=idle,
                rows=[],editing_batches=[],clock_wire={'requests':0,'encoded_bytes':0},
                failure_type=None,browser_errors=[],passed=False,
                scope='Offline generated UHD 3+3 attached editing; 30s GPU samples, 0.5s resource trace. Private commit, working set and UMA counters are separate.')
    try:
        with session(args.executable,out/'active',offline=True,project_path=project) as (page,proc,_,errors):
            paths=[str((args.media/f'h264-4k60-{i}.mp4').resolve()) for i in range(3)]
            imported=page.evaluate("paths=>request('import','POST',{paths,autoProxy:false})",paths)
            assert not imported['errors'] and len(imported['assets'])==3
            page.evaluate(SETUP,{'assets':imported['assets'],'seconds':125,'cut':.5})
            page.evaluate(HASH_TOOLS)
            page.select_option('#playbackEngine','native')
            page.wait_for_function('nativeState.prepared&&nativeState.metrics?.completed_frames>0&&!nativeState.metrics.waiting',timeout=45000)
            pending=set()
            with ExitStack() as stack:
                visibility=stack.enter_context(WindowVisibility(proc,'visible'))
                trace=RuntimeTrace(proc.pid);conditions=Conditions();gpu=GPU()
                cdp=page.context.new_cdp_session(page)
                cdp.send('Performance.enable');cdp.send('Network.enable')
                def requested(event):
                    if event['request']['url'].split('?')[0].endswith('/api/native/clock'):
                        pending.add(event['requestId']);result['clock_wire']['requests']+=1
                def finished(event):
                    if event['requestId'] in pending:
                        result['clock_wire']['encoded_bytes']+=event.get('encodedDataLength',0)
                        pending.discard(event['requestId'])
                cdp.on('Network.requestWillBeSent',requested)
                cdp.on('Network.loadingFinished',finished)
                cdp.on('Network.loadingFailed',finished)
                started=time.monotonic()
                def sample(stage):
                    heap={v['name']:v['value'] for v in cdp.send('Performance.getMetrics')['metrics']
                          if v['name'] in ('JSHeapUsedSize','JSHeapTotalSize','Nodes','Documents','JSEventListeners')}
                    # The GPU helper reports cumulative peaks. Sample into a fresh
                    # dictionary so a lower live allocation is visible after Stop.
                    earlier=gpu.memory_peak.copy();gpu.memory_peak.clear()
                    gpu.sample({proc.pid,*[p.pid for p in psutil.Process(proc.pid).children(recursive=True)]})
                    live={k:v/2**20 for k,v in gpu.memory_peak.items()}
                    for key,value in earlier.items():gpu.memory_peak[key]=max(value,gpu.memory_peak.get(key,0))
                    result['rows'].append(dict(seconds=time.monotonic()-started,stage=stage,
                        heap=heap,state=page.evaluate(STATE),groups=groups(proc),WebView_roles=webview_roles(proc),
                        gpu_process_allocation_sample_MiB=live))
                    write(out/'checkpoint.json',{'sample':result['rows'][-1],'batches':result['editing_batches']})
                try:
                    sample('prepared');start(page)
                    for n in range(1,seconds//10+1):
                        page.wait_for_timeout(max(0,(started+n*10-time.monotonic())*1000))
                        began=time.monotonic()
                        if n%3==0:sample('active')
                        audio=pause_and_read(page)
                        row={'iteration':n,'audio':audio,'scheduled_lag_seconds':max(0,began-started-n*10)}
                        result['editing_batches'].append(row)
                        if n%6==0:
                            page.evaluate("$('timelineScroller').scrollLeft=0")
                            scrub=drag(page,False)
                            row['scrub']={'timed_out':scrub['timed_out'],'release_ms':scrub['newest_picture_ms'],
                                          'target_frame':scrub['upFrame'],'checkpoints':scrub['checkpoints']}
                            assert not scrub['timed_out'] and scrub['checkpoints']==1,'Ruler release did not commit once'
                        row.update(page.evaluate(EDIT,n))
                        if n%6==0:
                            page.select_option('#programResolution','1280' if n%12==6 else '960')
                        start(page)
                        row['seconds']=time.monotonic()-started;row['wall_ms']=(time.monotonic()-began)*1000
                        assert audio['underruns']==0,'Playback segment underrun'
                    sample('end');result['last_audio']=pause_and_read(page)
                    page.wait_for_timeout(1000);sample('stopped')
                    page.wait_for_timeout(idle*1000);sample('natural_idle')
                    page.evaluate('nativeStop()')
                    page.wait_for_function('!nativeState.node&&!nativeState.prepared')
                    page.wait_for_timeout(1000);sample('native_released')
                    assert not page.evaluate("request('native/status')")['running']
                    assert not {'native','ffmpeg'}.intersection(result['rows'][-1]['groups']), 'Owned worker remained after Stop'
                finally:
                    result['runtime_trace']=trace.finish()
                    result['conditions']=conditions.finish()
                    result['gpu']=gpu.finish()
                    result['window_condition']=visibility.finish()
                    result['browser_errors'].extend(errors)
            assert result['window_condition']['condition_held'] and not errors
            power=result['conditions']['samples']
            assert power and all(row['ac_power'] is True for row in power),'AC condition did not hold'
            assert len(result['editing_batches'])==seconds//10 and result['last_audio']['underruns']==0
            assert all((row['state'].get('underruns') or 0)==0 for row in result['rows'])
            page.evaluate('async()=>{await flushSave();await recoverySettled();}')
            assert page.evaluate('recoveryAckSequence===recoverySequence')
            expected_history=page.evaluate(HISTORY)
            result['undo_entries']=len(expected_history['undo'])
            assert not expected_history['redo'] and (result['undo_entries']>=9 if args.smoke else result['undo_entries']==80)
            persisted=read_project(project)
            before_model=page.evaluate("request('state')")
            content={k:before_model[k] for k in ('name','version','tracks','output','assets','luts')}
        with session(args.executable,out/'reopened',offline=True,project_path=project) as (fresh,_,__,errors):
            fresh.evaluate(HASH_TOOLS)
            actual_history=fresh.evaluate(HISTORY)
            assert actual_history==expected_history,'Per-state project history changed across reopening'
            restored=fresh.evaluate("request('state')")
            assert all(restored[k]==v for k,v in content.items()),'Reopened editor model changed'
            assert read_project(project)==persisted and not errors
            assert not fresh.evaluate('isPlaying')
            fresh.evaluate('nativeStop()')
            result['reopened']={'all_persisted_content_exact':True,'all_history_entries_exact':True,'paused':True}
        for part in ('active','reopened'):
            ownership=json.loads((out/part/'process-ownership.json').read_text('utf-8'))
            assert not ownership['job_members_at_cleanup']
        result['audio_underruns_observed']=sum(r['audio']['underruns'] for r in result['editing_batches'])+result['last_audio']['underruns']
        summary=analyze(result)
        summary.pop('heap_samples',None)
        summary['webview_late_private_slopes']={}
        for role in ('browser','renderer','gpu-process','utility'):
            points=[(r['seconds'],r['WebView_roles'][role]['private_commit_MiB']) for r in result['rows']
                    if r['stage']=='active' and r['seconds']>=max(60,seconds-900) and role in r['WebView_roles']]
            summary['webview_late_private_slopes'][role]=slope(points)
        write(out/'memory-summary.json',summary)
        result['passed']=True
    except BaseException as error:
        result['failure_type']=type(error).__name__
        raise
    finally:
        write(out/'memory.json',result)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('executable','media','results'):parser.add_argument(name,type=Path)
    parser.add_argument('--smoke',action='store_true',help='90-second driver smoke; never qualifies endurance')
    run(parser.parse_args())
