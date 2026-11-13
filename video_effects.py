"""Clip-local FFmpeg filter construction for the program reference and export."""
import re

import animation


def active(c,prop,default):
    return c.get(prop,default)!=default or bool(c.get('keys',{}).get(prop))


def value(c,prop,time,default):
    return animation.expression({prop:default,**c},prop,time)


def filters(c,start,count,jobdir,*,alpha=True):
    parts=[]
    if any(active(c,k,d) for k,d in [('brightness',0),('contrast',1),('saturation',1)]):
        params=[f"{p}='{value(c,p,start,d)}'" for p,d in [('brightness',0),('contrast',1),('saturation',1)]]
        parts.append('eq='+':'.join(params)+':eval=frame')
    if alpha:parts.append('format=rgba')
    if c.get('chroma'):
        parts.append(f"colorkey=0x{c.get('keyColor','#00ff00')[1:]}:{c.get('similarity',.16)}:{c.get('keyBlend',.08)}")
    if c.get('mask')=='ellipse':
        r=re.sub(r'\bt\b','T',value(c,'maskRadius',start,.5))
        feather=c.get('feather',.1)
        dist=f'sqrt(pow((X/W-0.5)/({r}),2)+pow((Y/H-0.5)/({r}),2))'
        weight=f'clip((1-{dist})/{max(.00001,feather)},0,1)'
        parts.append(f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='alpha(X,Y)*{weight}':i=nearest")
    wipe=c.get('wipe','none')
    if wipe!='none' and c.get('wipeDuration',0)>0:
        coord={'right':'(X+.5)/W','left':'1-(X+.5)/W','down':'(Y+.5)/H','up':'1-(Y+.5)/H'}[wipe]
        progress=f"clip((T+{max(0,start-c['position'])})/{c['wipeDuration']},0,1)"
        parts.append(f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='alpha(X,Y)*lte({coord},{progress})':i=nearest")
    opacity=value(c,'opacity',start,1)
    if c.get('keys',{}).get('opacity'):
        commands=jobdir/f'alpha_{count}.cmd'
        expr=re.sub(r'\bt\b','T',opacity)
        commands.write_text(f"0 [expr] colorchannelmixer@alpha{count} aa '{expr}';\n",encoding='ascii')
        parts+=['sendcmd=f='+commands.name,f'colorchannelmixer@alpha{count}=aa=1']
    elif c.get('opacity',1)!=1:
        parts.append('colorchannelmixer=aa='+opacity)
    if active(c,'rotation',0):
        angle=value(c,'rotation',start,0)
        diameter='ceil(hypot(iw,ih)/2)*2'
        parts.append(f"rotate=angle='({angle})*PI/180':ow='{diameter}':oh='{diameter}':fillcolor=none")
    if c.get('keys',{}).get('scale'):
        scale=value(c,'scale',start,1)
        parts.append(f"scale=w='max(2,2*round(iw*({scale})/2))':h='max(2,2*round(ih*({scale})/2))':eval=frame")
    return ','+','.join(parts) if parts else ''
