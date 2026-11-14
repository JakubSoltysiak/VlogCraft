"""Compare only compatible repeated benchmark trials; thresholds trigger investigation."""
import argparse,json,statistics
from pathlib import Path
COMPATIBILITY=('hardware','workload','input_class','composition','surface','rate','proxy','cache_state','power','driver','active_refresh','observer')
METRICS={'present_fps':('throughput',.05),'export_fps':('throughput',.05),'first_frame_ms':('latency',.1),'seek_p95_ms':('latency',.1),'startup_ms':('latency',.1),
 'frame_p95_ms':('latency',.1),'frame_p99_ms':('latency',.1)}
def compare(baseline,candidate):
 mismatch=[k for k in COMPATIBILITY if k not in baseline['contract'] or k not in candidate['contract'] or baseline['contract'].get(k)!=candidate['contract'].get(k)]
 if mismatch:return {'compatible':False,'mismatches':mismatch,'investigate':True}
 result={}
 for key,(kind,threshold) in METRICS.items():
  a=[t[key] for t in baseline['trials'] if key in t];b=[t[key] for t in candidate['trials'] if key in t]
  if not a or not b:continue
  before,after=statistics.median(a),statistics.median(b)
  change=(after-before)/before if before else 0
  trigger=change< -threshold if kind=='throughput' else change>threshold
  worst_a=min(a) if kind=='throughput' else max(a);worst_b=min(b) if kind=='throughput' else max(b)
  worst_change=(worst_b-worst_a)/worst_a if worst_a else 0
  worst_trigger=worst_change< -threshold if kind=='throughput' else worst_change>threshold
  result[key]={'baseline_median':before,'candidate_median':after,'change_percent':change*100,'baseline_range':[min(a),max(a)],
   'candidate_range':[min(b),max(b)],'baseline_worst':worst_a,'candidate_worst':worst_b,'worst_change_percent':worst_change*100,
   'median_investigate':trigger,'worst_investigate':worst_trigger,'investigate':trigger or worst_trigger,'repeated':len(a)>=3 and len(b)>=3}
 return {'compatible':True,'metrics':result,'investigate':any(v['investigate'] for v in result.values()),
  'interpretation':'Investigation trigger, not automatic failure; inspect variation, quality and completeness'}
def main():
 p=argparse.ArgumentParser();p.add_argument('baseline',type=Path);p.add_argument('candidate',type=Path);p.add_argument('--output',type=Path);a=p.parse_args()
 result=compare(json.loads(a.baseline.read_text('utf8')),json.loads(a.candidate.read_text('utf8')))
 if a.output:a.output.write_text(json.dumps(result,indent=2),encoding='utf8')
 print(json.dumps(result));raise SystemExit(not result['compatible'])
if __name__=='__main__':main()
