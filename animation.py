"""Source-time animation for parameters shared by the monitor and renderer."""
import math

LIMITS = {'x':(-2,2), 'y':(-2,2), 'volume':(0,3), 'scale':(.1,3), 'rotation':(-360,360), 'opacity':(0,1),
          'brightness':(-1,1), 'contrast':(0,2), 'saturation':(0,3), 'maskRadius':(.01,1)}
MODES = ('linear','hold','ease-in','ease-out','bezier')


def number(value, low, high):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not low<=value<=high:
        raise ValueError('Animation value outside parameter range')
    return float(value)


def validate(curves):
    if not isinstance(curves,dict) or set(curves)-LIMITS.keys():
        raise ValueError('Unknown animated property')
    result = {}
    for prop,keys in curves.items():
        if not isinstance(keys,list):raise ValueError('Expected a list of keys')
        clean=[]
        for key in keys:
            if not isinstance(key,dict):raise ValueError('Invalid keyframe')
            at=number(key.get('time'),0,1e12)
            mode=key.get('mode','linear')
            if mode not in MODES or (clean and at<=clean[-1]['time']):
                raise ValueError('Keys need distinct increasing times and supported interpolation')
            item={'time':at,'value':number(key.get('value'),*LIMITS[prop]),'mode':mode}
            if mode=='bezier':
                handles=key.get('handles',[.25,.1,.25,1])
                if not isinstance(handles,list) or len(handles)!=4:raise ValueError('Four Bézier handle coordinates required')
                item['handles']=[number(h,0,1) for h in handles]
            clean.append(item)
        if clean:result[prop]=clean
    return result


def bezier(x,handles):
    x1,y1,x2,y2=handles
    def cubic(t,a,b):
        return 3*(1-t)**2*t*a+3*(1-t)*t*t*b+t**3
    lo,hi=0.,1.
    for _ in range(22):
        mid=(lo+hi)/2
        if cubic(mid,x1,x2)<x:lo=mid
        else:hi=mid
    return cubic((lo+hi)/2,y1,y2)


def expression(clip,prop,start):
    """FFmpeg expression in segment-local time. Binary branches keep nesting shallow."""
    keys=clip.get('keys',{}).get(prop,[])
    if not keys:return format(clip[prop],'.12g')
    source_at=clip['start']+(start-clip['position'])*clip['speed']
    clock=f'({source_at:.12g}+t*{clip["speed"]:.12g})'
    intervals=[]
    for a,b in zip(keys,keys[1:]):
        dt=b['time']-a['time']
        base=a['value']
        delta=b['value']-base
        u=f'(({clock}-{a["time"]:.12g})/{dt:.12g})'
        if a['mode']=='bezier':
            # Piecewise-linear approximation at 64 subintervals of segment time.
            prev=0.
            for i in range(1,65):
                value=bezier(i/64,a['handles']) if i<64 else 1.
                interp=f'({prev:.12g}+({u}*64-{i-1})*{value-prev:.12g})'
                intervals.append((a['time']+dt*i/64,f'({base:.12g}+({delta:.12g})*{interp})'))
                prev=value
        else:
            weight={'linear':u,'hold':'0','ease-in':f'({u}*{u})','ease-out':f'({u}*(2-{u}))'}[a['mode']]
            intervals.append((b['time'],f'({base:.12g}+({delta:.12g})*{weight})'))
    pieces=[(keys[0]['time'],str(keys[0]['value'])),*intervals,(math.inf,str(keys[-1]['value']))]
    def tree(items):
        if len(items)==1:return items[0][1]
        cut=len(items)//2
        return f'if(lt({clock},{items[cut-1][0]:.12g}),{tree(items[:cut])},{tree(items[cut:])})'
    return tree(pieces)
