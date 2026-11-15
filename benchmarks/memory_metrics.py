"""Thirty-second medians and within-session HAC slope intervals; no leak-free inference."""
import argparse,json,statistics
from pathlib import Path
import numpy as np

def slope(points):
    if len(points)<6:return {'samples':len(points),'available':False}
    x=np.asarray([p[0]/60 for p in points],dtype=float);y=np.asarray([p[1] for p in points],dtype=float)
    design=np.column_stack((np.ones(len(x)),x-x[0]));inverse=np.linalg.inv(design.T@design)
    beta=inverse@design.T@y;residual=y-design@beta;scores=design*residual[:,None];middle=scores.T@scores
    for lag in range(1,min(2,len(x)-1)+1):
        cross=scores[lag:].T@scores[:-lag];middle+=(1-lag/3)*(cross+cross.T)
    covariance=inverse@middle@inverse*len(x)/(len(x)-2);se=float(np.sqrt(max(0,covariance[1,1])))
    return {'available':True,'samples':len(x),'MiB_per_minute':float(beta[1]),'approximate_95_percent_interval':[float(beta[1]-1.96*se),float(beta[1]+1.96*se)],
            'method':'OLS on30s medians, Newey-West2-lag covariance with finite-sample correction and normal1.96 interval. Single session, approximate serial-correlation treatment; not a population reliability guarantee.'}

def analyze(data):
    seconds=data['seconds'];samples=data['runtime_trace']['samples'];groups=sorted({g for r in samples for g in r['groups']});result={}
    for group in [*groups,'total']:
        values={}
        for field in ('rss_MiB','private_commit_MiB'):
            points=[]
            for r in samples:
                if r['seconds']>=seconds:continue
                value=sum(v[field] for v in r['groups'].values()) if group=='total' else r['groups'].get(group,{}).get(field,0)
                points.append((r['seconds'],value))
            if not points:continue
            bins=[]
            for start in range(0,seconds,30):
                v=[value for t,value in points if start<=t<start+30]
                if v:bins.append((start+15,statistics.median(v)))
            values[field]={'first30_median':bins[0][1],'last30_median':bins[-1][1],'peak':max(v for t,v in points),
                           'after_warmup_slope':slope([p for p in bins if p[0]>=60]),
                           'late_slope':slope([p for p in bins if p[0]>=max(60,seconds-900)]),'30s_medians':bins}
        result[group]=values
    return {'mode':data['mode'],'seconds':seconds,'groups':result,'heap_samples':data['rows'],'clock_wire':data['clock_wire'],
            'failure_type':data['failure_type'],'browser_errors':data['browser_errors'],
            'scope':'RSS sums may duplicate shared UMA pages. Private commit, heap, GPU estimates are separate. No forced GC during active measurement.'}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('input',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
    a.output.write_text(json.dumps(analyze(json.loads(a.input.read_text('utf8'))),indent=2)+'\n',encoding='utf8')
