"""Offline numeric extraction. Never copy raw media, projects or identifying fields."""
import argparse,json
from pathlib import Path

def stalls(data):
    base=data['base']['wall_seconds'];rows=data['status_trace'];bursts=[]
    for a,b in zip(rows,rows[1:]):
        lost=b['skipped_sequence_frames']-a['skipped_sequence_frames']
        if lost>0:bursts.append({'native_elapsed_begin':a['wall_seconds']-base,'native_elapsed_end':b['wall_seconds']-base,'skips_delta':lost})
    bad=[r for r in data['window_condition']['samples'] if not r.get('foreground_owned',True) or not r.get('preview_center_unobscured',True)]
    return {'total_skips':data['last']['skipped_sequence_frames'],'observed_counter_increases':sum(r['skips_delta'] for r in bursts),
            'largest_counter_increases':sorted(bursts,key=lambda r:r['skips_delta'],reverse=True)[:8],
            'first_visibility_violation_seconds':min((r['seconds'] for r in bad),default=None),
            'clock_scope':'Native elapsed subtracts initial paused native status; window time starts before playback. Uncalibrated offset prevents exact alignment. Counter jumps do not timestamp the underlying stalls or individual Present calls.'}

def observation(data):
    return {k:data[k] for k in ('seconds','observation_elapsed_seconds','reconnection_and_query_tail_seconds','natural_idle_seconds','audio','transport') if k in data}|{
      'window_condition_held':data['window_condition']['condition_held'],'browser_error_count':len(data['browser_errors']),
      'stages':[{'stage':r['stage'],'seconds':r['seconds'],'private_commit_MiB':{k:v['private_commit_MiB'] for k,v in r['groups'].items()},
                 'live_JS_MiB':r.get('heap',{}).get('JSHeapUsedSize',0)/1048576 if 'heap' in r else None} for r in data['rows']]}

def roles(data):
    active=[r for r in data['rows'] if r['stage']=='active' and r.get('WebView_roles')]
    return {role:{'first_MiB':active[0]['WebView_roles'].get(role,{}).get('private_commit_MiB',0),
                  'last_MiB':active[-1]['WebView_roles'].get(role,{}).get('private_commit_MiB',0)}
            for role in sorted({k for r in active for k in r['WebView_roles']})} if active else {}

def main(a):
    load=lambda p:json.loads(p.read_text('utf8'))
    result={'historical_stalls':stalls(load(a.endurance)),'historical_memory_roles':roles(load(a.memory)),
            'new_observations':{p.parent.name:observation(load(p)) for p in a.observer}}
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'numeric_evidence_written':True,'observations':len(a.observer)}))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('endurance',type=Path);p.add_argument('memory',type=Path);p.add_argument('output',type=Path);p.add_argument('--observer',type=Path,nargs='*',default=[]);main(p.parse_args())
