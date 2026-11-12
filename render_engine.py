"""Local FFmpeg multitrack rendering engine for VlogCraft Studio.

Segments are composed independently so long projects do not require a single
FFmpeg graph to hold hundreds of simultaneous decoders. No media is uploaded.
Source files are always read-only. Heavy operations run in a worker thread.
"""
from __future__ import annotations
import math
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

GRADES = {
    'neutral': '',
    'warm': ',colorbalance=rs=.065:bs=-.06,eq=saturation=1.07',
    'cool': ',colorbalance=bs=.07:rs=-.045',
    'vivid': ',eq=contrast=1.09:saturation=1.18',
    'cinematic': ',eq=contrast=1.08:saturation=.86:brightness=-.012',
    'mono': ',hue=s=0',
}

def clip_length(clip):
    return max(0.0, (float(clip['end'])-float(clip['start']))/float(clip.get('speed', 1)))

def clip_finish(clip):
    return float(clip['position'])+clip_length(clip)

def sequence_duration(state):
    return max((clip_finish(c) for t in state['tracks'] for c in t['clips']
                if not t.get('hidden') and (c.get('assetId') or c.get('kind') == 'title')), default=0.0)

def active_clips(state, start, finish):
    """Bottom to top for image compositing. Muted tracks remain visible."""
    video, audio = [], []
    for t in reversed(state['tracks']):
        if t['type'] != 'video' or t.get('hidden'): continue
        for c in sorted(t['clips'], key=lambda z: z['position']):
            if clip_finish(c)>start+1e-6 and c['position']<finish-1e-6:
                video.append((t,c))
                if c.get('assetId') and not t.get('muted') and c.get('volume',1)>0:
                    audio.append((t,c))
    for t in state['tracks']:
        if t['type'] != 'audio' or t.get('muted'): continue
        for c in t['clips']:
            if clip_finish(c)>start+1e-6 and c['position']<finish-1e-6:
                audio.append((t,c))
    return video, audio

def boundaries(state, fps):
    total=sequence_duration(state)
    marks={0, math.ceil(total*fps)/fps}
    for track in state['tracks']:
        if track.get('hidden'): continue
        for c in track['clips']:
            for at in (c['position'], clip_finish(c)):
                marks.add(min(math.ceil(total*fps),max(0,round(float(at)*fps)))/fps)
            # FFmpeg alpha fades are constrained within a segment; splitting at
            # fade boundaries avoids resetting the source effect unexpectedly.
            fi=float(c.get('fadeIn',0)); fo=float(c.get('fadeOut',0));
            if fi>0:marks.add(round(min(total,c['position']+fi)*fps)/fps)
            if fo>0:marks.add(round(max(0,clip_finish(c)-fo)*fps)/fps)
    points=sorted(t for t in marks if 0<=t<=math.ceil(total*fps)/fps)
    return [(a,b) for a,b in zip(points,points[1:]) if b-a>=1/fps-.0001]

def _num(v): return f'{float(v):.5f}'

def _atempo(speed):
    effects=[]
    while speed<.5:
        effects.append('atempo=.5'); speed*=2
    while speed>2:
        effects.append('atempo=2'); speed/=2
    effects.append('atempo='+_num(speed))
    return ','.join(effects)

def _gain(track,clip):
    return max(0,min(3,float(track.get('volume',1))*float(clip.get('volume',1))))

def _add_audio(filters, input_idx, track, clip, start, end, dur, label):
    offset=max(0,start-float(clip['position']))
    remaining=max(0, min(clip_length(clip),end-float(clip['position'])))
    fadein=float(clip.get('fadeIn',0))
    fadeout=float(clip.get('fadeOut',0))
    afades=''
    if fadein>offset+1e-3:
        # Remaining fade portion, approximately preserving its starting gain.
        afades+=f',afade=t=in:st=0:d={_num(min(dur,fadein-offset))}'
    end_at=clip_length(clip)-fadeout
    if fadeout>0 and end_at<offset+dur:
        afades+=f',afade=t=out:st={_num(max(0,end_at-offset))}:d={_num(min(fadeout,dur))}'
    filters.append(f'[{input_idx}:a]aresample=48000,aformat=channel_layouts=stereo,'
                   f'asetpts=PTS-STARTPTS,{_atempo(float(clip.get("speed",1)) )},'
                   f'volume={_num(_gain(track,clip))}{afades},apad,'
                   f'atrim=duration={_num(dur)},asetpts=PTS-STARTPTS[{label}]')

def _media_input(cmd, path, kind, at, speed, dur, fps):
    if kind=='image':
        cmd.extend(['-loop','1','-framerate',str(fps),'-i',str(path)])
    else:
        cmd.extend(['-ss',_num(at),'-i',str(path)])

def _fade_video(clip, start, dur):
    fi=float(clip.get('fadeIn',0)); fo=float(clip.get('fadeOut',0))
    off=max(0,start-float(clip['position']))
    fade=''
    if fi>off+0.00001:
        fade+=f',fade=t=in:st=0:d={_num(min(dur,fi-off))}:alpha=1'
    fade_end=clip_length(clip)-fo
    if fo>0 and fade_end<off+dur:
        fade+=f',fade=t=out:st={_num(max(0,fade_end-off))}:d={_num(min(fo,dur))}:alpha=1'
    return fade

def segment_command(state, start, end, target, jobdir, quality='final'):
    assets={a['id']:a for a in state['assets']}
    w=int(state['output']['width']); h=int(state['output']['height']); fps=int(state['output']['fps'])
    duration=end-start
    video,audio=active_clips(state,start,end)
    cmd=['ffmpeg','-hide_banner','-nostdin','-loglevel','error','-y',
         '-f','lavfi','-i',f'color=c=0x10131a:s={w}x{h}:r={fps}:d={_num(duration)}',
         '-f','lavfi','-i',f'anullsrc=channel_layout=stereo:sample_rate=48000:d={_num(duration)}']
    filters=['[0:v]format=yuv420p[back0]']; last='back0'; audio_labels=['1:a']; count=0
    # Reuse source inputs only when the same clip appears in both video and audio.
    inputs={}; source_index=2
    def get_input(c):
        nonlocal source_index
        key=c['id']
        if key not in inputs:
            a=assets[c['assetId']]
            pos_offset=max(0,start-float(c['position']))
            seek=float(c['start'])+pos_offset*float(c.get('speed',1))
            _media_input(cmd,a['path'],a['kind'],seek,float(c.get('speed',1)),duration,fps)
            inputs[key]=source_index;source_index+=1
        return inputs[key]

    for t,c in video:
        if c.get('kind')=='title':
            if not c.get('text'):continue
            count+=1
            f=jobdir/f'title_{count}.txt';f.write_text(c['text'],encoding='utf-8')
            text_y='(h-text_h)/2' if c.get('titleAlign','center')=='center' else 'h*0.78'
            fontsize=max(15,int(w*float(c.get('fontScale',0.048))))
            color=c.get('color','white')
            alpha=float(c.get('opacity',1))
            # drawtext evaluates alpha each frame; fade timing remains correct
            # across split render segments, unlike a fade applied to the whole canvas.
            local_offset=max(0,start-float(c['position']))
            left=clip_length(c)-local_offset
            alpha_terms=[]
            if c.get('fadeIn',0)>0:
                alpha_terms.append(f'min(1\\,max(0\\,(t+{_num(local_offset)})/{_num(c["fadeIn"])}))')
            if c.get('fadeOut',0)>0:
                alpha_terms.append(f'min(1\\,max(0\\,({_num(left)}-t)/{_num(c["fadeOut"])}))')
            alpha_expr='*'.join(alpha_terms) if alpha_terms else '1'
            filters.append(f'[{last}]drawtext=textfile={f.name}:fontcolor={color}@{alpha:.3f}:'
                           f'fontsize={fontsize}:x=(w-text_w)/2:y={text_y}:'
                           f'alpha={alpha_expr}:box=1:boxcolor=black@0.35:boxborderw=14'
                           f'[back{count}]')
            last=f'back{count}'
            continue
        a=assets[c['assetId']]
        inp=get_input(c)
        count+=1
        zoom=float(c.get('scale',1)); targetw=max(2,round(w*zoom)//2*2);targeth=max(2,round(h*zoom)//2*2)
        scalemode='increase' if c.get('fit')=='cover' else 'decrease'
        # HDR10/HDR10+ / HLG -> SDR BT.709 tone mapping for normal TVs and web.
        # Export is SDR H.264; original 10-bit/HDR source is not modified.
        hdr=(a.get('hdr') is True or a.get('colorTransfer') in ('smpte2084','arib-std-b67'))
        hdr_filters=('zscale=t=linear:npl=100,format=gbrpf32le,'
                     'tonemap=hable:desat=0,zscale=t=bt709:m=bt709:p=bt709:r=tv,format=yuv420p,') if hdr else ''
        expr=(f'[{inp}:v]setpts=(PTS-STARTPTS)/{_num(c.get("speed",1))},'
              f'fps={fps},'+hdr_filters+
              f'scale={targetw}:{targeth}:force_original_aspect_ratio={scalemode}')
        if c.get('fit')=='cover':
            expr+=f',crop={targetw}:{targeth}'
        expr+=(GRADES.get(c.get('grade','neutral'), '')+
               f',format=rgba,colorchannelmixer=aa={_num(c.get("opacity",1))}'
               +_fade_video(c,start,duration)+f'[lay{count}]')
        filters.append(expr)
        # Expressions are evaluated per frame; positions are in relative canvas units.
        x=float(c.get('x',0));y=float(c.get('y',0))
        filters.append(f'[{last}][lay{count}]overlay='
                       f'x=(W-w)/2+({x:.5f})*W:y=(H-h)/2+({y:.5f})*H:'
                       f'eof_action=pass:shortest=0:format=auto[back{count}]')
        last=f'back{count}'

    audio_seen=set()
    for t,c in audio:
        if c.get('kind')=='title' or not c.get('assetId') or _gain(t,c)<=0:continue
        if c['id'] in audio_seen:continue
        a=assets[c['assetId']]
        if a['kind']=='image' or not a.get('hasAudio'):continue
        inp=get_input(c)
        label=f'a{len(audio_labels)}'
        _add_audio(filters,inp,t,c,start,end,duration,label)
        audio_labels.append(label);audio_seen.add(c['id'])

    if len(audio_labels)>1:
        flabels=''.join('['+x+']' for x in audio_labels)
        filters.append(f'{flabels}amix=inputs={len(audio_labels)}:duration=first:normalize=0,'
                       f'atrim=duration={_num(duration)}[mixed]')
    else:
        filters.append(f'[1:a]anull[mixed]')

    filters.append(f'[{last}]format=yuv420p[finished]')
    script=jobdir/f'graph_{target.stem}.txt'
    script.write_text(';\n'.join(filters)+'\n',encoding='utf-8')
    crf='26' if quality=='review' else str(state['output'].get('crf',20))
    preset='veryfast' if quality=='review' else str(state['output'].get('preset','medium'))
    cmd+=['-filter_complex_script',str(script),'-map','[finished]','-map','[mixed]',
          '-t',_num(duration),'-r',str(fps),'-c:v','libx264','-preset',preset,
          '-crf',crf,'-pix_fmt','yuv420p','-c:a','aac','-b:a','192k',
          '-ac','2','-ar','48000','-movflags','+faststart',str(target)]
    return cmd

def render(state, output, work, *, review=False, on_progress=None, cancelled=lambda:False, popen=None):
    """Export a sequence using a bounded-memory segment renderer.

    popen is callback(command, cwd) that runs FFmpeg and handles cancellation.
    """
    duration=sequence_duration(state)
    if duration<0.04:raise ValueError('Add at least one clip to the timeline')
    jobdir=Path(work);jobdir.mkdir(parents=True,exist_ok=True)
    segments=boundaries(state,int(state['output']['fps']))
    if not segments:raise ValueError('No usable frames in the timeline')
    runner=popen or _run
    parts=[]
    for idx,(start,end) in enumerate(segments):
        if cancelled():raise RuntimeError('Export cancelled')
        target=jobdir/f'segment_{idx:05d}.mp4'
        if on_progress:on_progress(round(3+idx/len(segments)*91),f'Rendering scene {idx+1} / {len(segments)}')
        runner(segment_command(state,start,end,target,jobdir,'review' if review else 'final'),str(jobdir))
        parts.append(target)
    files=jobdir/'concat.txt';files.write_text(''.join(f"file '{p.name}'\n" for p in parts),encoding='utf-8')
    if on_progress:on_progress(96,'Joining rendered scenes…')
    target=Path(output)
    target.parent.mkdir(parents=True,exist_ok=True)
    part=target.with_name('.'+target.stem+'.partial.mp4')
    if part.exists():part.unlink()
    try:
        runner(['ffmpeg','-hide_banner','-nostdin','-loglevel','error','-y',
               '-f','concat','-safe','0','-i',str(files),'-c','copy','-movflags','+faststart',str(part)],str(jobdir))
        if cancelled():raise RuntimeError('Export cancelled')
        os.replace(part,target)
    finally:
        if part.exists():part.unlink()
    if on_progress:on_progress(100,'Export complete')
    return str(target)

def _run(cmd,cwd):
    r=subprocess.run(cmd,cwd=cwd,capture_output=True,text=True,timeout=120*60)
    if r.returncode:
        raise RuntimeError(r.stderr[-1500:])
