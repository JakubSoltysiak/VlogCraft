"""Audio analysis reads fixed-duration PCM blocks from the original streams."""
import math
import subprocess

import numpy as np


def filters(clip):
    chain=[]
    if clip.get('bass',0):chain.append(f"bass=f=160:g={clip['bass']}")
    if clip.get('treble',0):chain.append(f"treble=f=4200:g={clip['treble']}")
    if clip.get('compress',1)>1:
        chain.append(f"acompressor=threshold=0.1259:ratio={clip['compress']}:attack=5:release=120")
    pan=clip.get('pan',0)
    if pan:
        angle=(pan+1 if pan<0 else pan)*math.pi/2
        a,b=math.cos(angle),math.sin(angle)
        chain.append(f'pan=stereo|c0=c0+{a:.8f}*c1|c1={b:.8f}*c1' if pan<0 else
                     f'pan=stereo|c0={a:.8f}*c0|c1=c1+{b:.8f}*c0')
    return ''.join(','+effect for effect in chain)


def blocks(path,start,end,rate,channels,block_samples):
    args=['ffmpeg','-nostdin','-v','error','-ss',str(start),'-i',str(path),'-t',str(end-start),
          '-map','0:a:0','-vn','-ar',str(rate),'-ac',str(channels),'-f','f32le','pipe:1']
    with subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                          creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)) as proc:
        try:
            while data:=proc.stdout.read(4*block_samples*channels):
                yield np.frombuffer(data,dtype='<f4')
            if proc.wait():raise ValueError('Could not analyze the original audio stream')
        finally:
            if proc.poll() is None:proc.kill()


def analysis(state,data):
    assets={a['id']:a for a in state['assets']}
    tr,c=next(((t,c) for t in state['tracks'] for c in t['clips'] if c['id']==data.get('clipId')),(None,None))
    if not c or tr['locked'] or c['locked']:raise ValueError('Choose an unlocked clip')
    a=assets.get(c['assetId'])
    if not a or not a.get('hasAudio') or c.get('audioDetached'):raise ValueError('This clip has no active source audio')
    if data.get('mode')=='normalize':
        peak=max((float(np.abs(x).max()) for x in blocks(a['path'],c['start'],c['end'],48000,2,8192)),default=0.)
        if peak<1e-8:raise ValueError('This range contains silence')
        gain=min(3,10**(-1/20)/peak)
        return {'gain':gain,'peakDb':20*math.log10(peak),'capped':gain>=3}
    if data.get('mode')!='duck':raise ValueError('Unknown audio analysis')
    voice=next((t for t in state['tracks'] if t['id']==data.get('voiceTrack')),None)
    if not voice or voice['id']==tr['id']:raise ValueError('Choose a separate dialogue track')
    clock_start=c['position'];clock_end=clock_start+(c['end']-c['start'])/c['speed']
    spans=[]
    for speech in voice['clips']:
        src=assets.get(speech.get('assetId'))
        if not src or not src.get('hasAudio') or speech.get('audioDetached'):continue
        speed=speech['speed'];pos=speech['position']
        lo=max(clock_start,pos);hi=min(clock_end,pos+(speech['end']-speech['start'])/speed)
        if lo>=hi:continue
        inside=False
        for i,chunk in enumerate(blocks(src['path'],speech['start']+(lo-pos)*speed,
                                      speech['start']+(hi-pos)*speed,8000,1,400)):
            t=lo+i*.05/speed
            active=float(np.sqrt(np.mean(chunk*chunk)))*speech.get('volume',1)*voice.get('volume',1)>.018
            if active and not inside:begin=t
            if inside and not active:spans.append((begin,t))
            inside=active
        if inside:spans.append((begin,hi))
    merged=[]
    for lo,hi in sorted(spans):
        if merged and lo<=merged[-1][1]+.45:merged[-1]=(merged[-1][0],max(merged[-1][1],hi))
        else:merged.append((lo,hi))
    if not merged:raise ValueError('No dialogue-track signal above the activity threshold in this range')
    points={clock_start:1.,clock_end:1.}
    for lo,hi in merged:
        points[max(clock_start,lo-.12)]=1.
        points[lo]=.25;points[hi]=.25
        if hi<clock_end:points[min(clock_end,hi+.3)]=1.
    return {'regions':len(merged),'keys':[{'time':c['start']+(t-clock_start)*c['speed'],
            'value':factor*c.get('volume',1),'mode':'linear'} for t,factor in sorted(points.items())]}
