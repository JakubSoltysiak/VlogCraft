"""Rational cadence expectations; no source interpolation or timestamp mutation."""
from fractions import Fraction
def cadence(source_rate,display_rate,seconds=10):
 source=Fraction(str(source_rate));display=Fraction(str(display_rate))
 samples=int(display*seconds);held=[]
 for refresh in range(samples):
  at=Fraction(refresh,1)/display;held.append(int(at*source))
 runs=[]
 for frame in held:
  if runs and runs[-1][0]==frame:runs[-1][1]+=1
  else:runs.append([frame,1])
 return {'source_rate':str(source),'display_rate':str(display),'refresh_samples':samples,'unique_source_frames':len(runs),
  'refreshes_per_frame_values':sorted({n for f,n in runs[1:-1]}),'interpolated_frames':0,
  'method':'Exact rational hold on refresh grid; mathematical expectation, not physical display measurement'}
if __name__=='__main__':
 import json
 print(json.dumps([cadence(r,120) for r in (24,25,30,50,'60000/1001',60,120)],indent=2))
