"""Wall-time bounded diagnostic scheduling, outside editor/render threads."""
import time

def observe(seconds,wait,sample,*,period=15,clock=time.monotonic):
    if seconds<=0 or period<=0:raise ValueError('Observation durations must be positive')
    started=clock();deadline=started+seconds;next_sample=started+period
    while True:
        now=clock()
        if now>=deadline:break
        wait(min(1,deadline-now))
        now=clock()
        if now>=next_sample:
            sample()
            # Expensive samples consume the observation budget; never add
            # one extra full wait per callback or issue catch-up bursts.
            next_sample=started+(int((clock()-started)/period)+1)*period
    return clock()-started
