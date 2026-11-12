"""Local FFmpeg multitrack rendering engine for VlogCraft Studio.

Segments are composed independently so long projects do not require a single
FFmpeg graph to hold hundreds of simultaneous decoders. No media is uploaded.
Source files are always read-only. Heavy operations run in a worker thread.
"""
from __future__ import annotations
import math
import animation
import audio_edit
import video_effects
import grading
import sequences
import timing
import encoders
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
                if not t.get('hidden') and (c.get('assetId') or c.get('kind') in ('title','sequence'))), default=0.0)

def active_clips(state, start, finish):
    """Bottom to top for image compositing. Muted tracks remain visible."""
    fps=timing.rate(state['output']['fps'])
    first,last=timing.frame_at(start,fps),timing.frame_at(finish,fps)
    solo=any(t.get('solo') for t in state['tracks'])
    video, audio = [], []
    for t in reversed(state['tracks']):
        if t['type'] != 'video' or t.get('hidden'): continue
        for c in sorted(t['clips'], key=lambda z: z['position']):
            if timing.frame_at(clip_finish(c),fps)>first and timing.frame_at(c['position'],fps)<last:
                video.append((t,c))
                if c.get('assetId') and not c.get('audioDetached') and not t.get('muted') and (not solo or t.get('solo')) and (c.get('volume',1)>0 or c.get('keys',{}).get('volume')):
                    audio.append((t,c))
    for t in state['tracks']:
        if t['type'] != 'audio' or t.get('muted') or (solo and not t.get('solo')): continue
        for c in t['clips']:
            if timing.frame_at(clip_finish(c),fps)>first and timing.frame_at(c['position'],fps)<last:
                audio.append((t,c))
    return video, audio

def frame_spans(state, fps):
    # Partition on integer frame boundaries, including fractional-second edits.
    marks={0}
    for track in state['tracks']:
        if track.get('hidden'):continue
        for clip in track['clips']:
            marks.add(timing.frame_at(clip['position'],fps))
            marks.add(timing.frame_at(clip_finish(clip),fps))
    points=sorted(marks)
    return list(zip(points,points[1:]))


def boundaries(state,fps):
    rate=timing.rate(fps)
    return [(float(a/rate),float(b/rate)) for a,b in frame_spans(state,rate)]


def _num(v): return f'{float(v):.9f}'

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
    fi,fo=clip.get('fadeIn',0),clip.get('fadeOut',0)
    afades=f',asetpts=PTS+{_num(offset)}/TB'
    if fi:afades+=f',afade=t=in:d={_num(fi)}'
    if fo:afades+=f',afade=t=out:st={_num(max(0,clip_length(clip)-fo))}:d={_num(fo)}'
    afades+=',asetpts=PTS-STARTPTS'
    gain=animation.expression(clip,'volume',start)
    filters.append(f'[{input_idx}:a]atrim=start=0,aresample=48000,aformat=channel_layouts=stereo,'
                   f'asetpts=PTS-STARTPTS,{_atempo(float(clip.get("speed",1)) )}{audio_edit.filters(clip)},'
                   f"volume='{_num(track.get('volume',1))}*{gain}':eval=frame{afades},apad,"
                   f'atrim=duration={_num(dur)},asetpts=PTS-STARTPTS[{label}]')

def _media_input(cmd, path, kind, at, speed, dur, fps, media_type):
    if kind=='image':
        cmd.extend(['-loop','1','-framerate',str(fps),'-i',str(path)])
    else:
        # Serial decoding avoids a reproduced multi-input FFmpeg drain stall.
        # Keep preroll intact so held VFR and fractional-frame cuts remain correct.
        cmd.extend(['-ss',_num(math.ceil(at*1_000_000-1e-8)/1_000_000),'-noaccurate_seek',
                    '-threads','1','-an' if media_type=='video' else '-vn','-i',str(path)])

def _fade_video(clip, start, dur):
    fi=float(clip.get('fadeIn',0)); fo=float(clip.get('fadeOut',0))
    off=max(0,start-float(clip['position']))
    fade=f',setpts=PTS+{_num(off)}/TB'
    if fi:fade+=f',fade=t=in:d={_num(fi)}:alpha=1'
    if fo:fade+=f',fade=t=out:st={_num(max(0,clip_length(clip)-fo))}:d={_num(fo)}:alpha=1'
    fade+=',setpts=PTS-STARTPTS'
    return fade

def segment_command(state, start, end, target, jobdir, quality='final', stream=None):
    state=sequences.playback(state)
    assets={a['id']:a for a in state['assets']}
    w=int(state['output']['width']); h=int(state['output']['height']); fps=timing.rate(state['output']['fps'])
    duration=end-start
    nframes=timing.frame_at(end,fps)-timing.frame_at(start,fps)
    samples=timing.sample_at(timing.frame_at(end,fps),fps)-timing.sample_at(timing.frame_at(start,fps),fps)
    video,audio=active_clips(state,start,end)
    if stream=='video':audio=[]
    if stream=='audio':video=[]
    background_size='16x16' if stream=='audio' else f'{w}x{h}'
    cmd=['ffmpeg','-hide_banner','-nostdin','-loglevel','error','-filter_complex_threads','1','-y',
         '-f','lavfi','-i',f'color=c=0x10131a:s={background_size}:r={fps}:d={_num(duration)}',
         '-f','lavfi','-i',f'anullsrc=channel_layout=stereo:sample_rate=48000:d={_num((samples+2)/48000)}']
    filters=['[0:v]format=yuv420p[back0]']; last='back0'; audio_labels=['1:a']; count=0
    # Demux audio and video separately to avoid cross-stream drain deadlocks.
    # Reuse each stream's source/seek/speed across matching clips.
    inputs={}; source_index=2
    continuous=quality=='preview'
    def first_time(c):
        return max(start,float(timing.frame_at(c['position'],fps)/fps)) if continuous else start
    def last_time(c):
        return min(end,float(timing.frame_at(clip_finish(c),fps)/fps)) if continuous else end
    def get_input(c,media_type):
        nonlocal source_index
        a=assets[c['assetId']]
        pos_offset=max(0,first_time(c)-float(c['position']))
        seek=float(c['start'])+pos_offset*float(c.get('speed',1))
        key=(c['assetId'],seek,c.get('speed',1),media_type)
        if key not in inputs:
            _media_input(cmd,a['path'],a['kind'],seek,float(c.get('speed',1)),duration,fps,media_type)
            inputs[key]=source_index;source_index+=1
        return inputs[key]

    for t,c in video:
        clip_start=first_time(c);clip_end=last_time(c)
        delay=max(0,clip_start-start)
        enabled=f"gte(t,{_num(delay)})*lt(t,{_num(clip_end-start)})"
        if c.get('kind')=='title':
            if not c.get('text'):continue
            count+=1
            f=jobdir/f'title_{count}.txt';f.write_text(c['text'],encoding='utf-8')
            text_y='(h-text_h)/2' if c.get('titleAlign','center')=='center' else 'h*0.78'
            tx=animation.expression(c,'x',start)
            ty=animation.expression(c,'y',start)
            fontsize=max(15,int(w*float(c.get('fontScale',0.048))))
            color=c.get('color','white')
            alpha=animation.expression(c,'opacity',start)
            # drawtext evaluates alpha each frame; fade timing remains correct
            # across split render segments, unlike a fade applied to the whole canvas.
            local_offset=start-float(c['position']) if continuous else max(0,start-float(c['position']))
            left=clip_length(c)-local_offset
            alpha_terms=[]
            if c.get('fadeIn',0)>0:
                alpha_terms.append(f'min(1\\,max(0\\,(t+{_num(local_offset)})/{_num(c["fadeIn"])}))')
            if c.get('fadeOut',0)>0:
                alpha_terms.append(f'min(1\\,max(0\\,({_num(left)}-t)/{_num(c["fadeOut"])}))')
            alpha_expr='*'.join([alpha,*alpha_terms])
            font_option=''
            if os.name=='nt':
                font=jobdir/'title-font.ttf'
                if not font.exists():shutil.copyfile(Path(os.environ['WINDIR'])/'Fonts'/'segoeui.ttf',font)
                font_option='fontfile=title-font.ttf:'
            filters.append(f'[{last}]drawtext={font_option}textfile={f.name}:fontcolor={color}:'
                           f"expansion=none:fontsize={fontsize}:x='(w-text_w)/2+w*({tx})':y='{text_y}+h*({ty})':" 
                           f"alpha='{alpha_expr}':box=1:boxcolor=black@0.35:boxborderw=14"+(f":enable='{enabled}'" if continuous else '')+
                           f'[back{count}]')
            last=f'back{count}'
            continue
        a=assets[c['assetId']]
        inp=get_input(c,'video')
        count+=1
        zoom=1 if c.get('keys',{}).get('scale') else float(c.get('scale',1)); targetw=max(2,round(w*zoom)//2*2);targeth=max(2,round(h*zoom)//2*2)
        scalemode='increase' if c.get('fit')=='cover' else 'decrease'
        # HDR10/HDR10+ / HLG -> SDR BT.709 tone mapping for normal TVs and web.
        # Export is SDR H.264; original 10-bit/HDR source is not modified.
        hdr=(a.get('hdr') is True or a.get('colorTransfer') in ('smpte2084','arib-std-b67'))
        hdr_filters=('zscale=t=linear:npl=100,format=gbrpf32le,'
                     'tonemap=hable:desat=0,zscale=t=bt709:m=bt709:p=bt709:r=tv,format=yuv420p,') if hdr else ''
        expr=(f'[{inp}:v]setpts=PTS/{_num(c.get("speed",1))},'
              f'fps={fps}:start_time=0:round=up,'+hdr_filters+
              f'scale={targetw}:{targeth}:force_original_aspect_ratio={scalemode}')
        if c.get('fit')=='cover':
            expr+=f',crop={targetw}:{targeth}'
        expr+=(GRADES.get(c.get('grade','neutral'), '')+
               grading.filter_for(c,state,jobdir)+video_effects.filters(c,clip_start,count,jobdir)
               +_fade_video(c,clip_start,clip_end-clip_start))
        if continuous:
            local_frames=timing.frame_at(clip_end,fps)-timing.frame_at(clip_start,fps)
            expr+=f',trim=end_frame={local_frames},setpts=PTS+{_num(delay)}/TB'
        expr+=f'[lay{count}]'
        filters.append(expr)
        # Expressions are evaluated per frame; positions are in relative canvas units.
        x=animation.expression(c,'x',start);y=animation.expression(c,'y',start)
        filters.append(f'[{last}][lay{count}]overlay='
                       f"x='(W-w)/2+({x})*W':y='(H-h)/2+({y})*H':"
                       f'eof_action=pass:shortest=0:format=auto'+(f":enable='{enabled}'" if continuous else '')+f'[back{count}]')
        last=f'back{count}'

    audio_seen=set()
    for t,c in audio:
        if c.get('kind')=='title' or not c.get('assetId') or (_gain(t,c)<=0 and not c.get('keys',{}).get('volume')):continue
        if c['id'] in audio_seen:continue
        a=assets[c['assetId']]
        if a['kind']=='image' or not a.get('hasAudio'):continue
        inp=get_input(c,'audio')
        label=f'a{len(audio_labels)}'
        if continuous:
            clip_start=first_time(c);clip_end=last_time(c)
            raw=label+'_source'
            _add_audio(filters,inp,t,c,clip_start,clip_end,clip_end-clip_start,raw)
            delay_samples=timing.sample_at(timing.frame_at(clip_start,fps),fps)-timing.sample_at(timing.frame_at(start,fps),fps)
            filters.append(f'[{raw}]adelay={delay_samples}S:all=1,apad,atrim=end_sample={samples}[{label}]')
        else:_add_audio(filters,inp,t,c,start,end,duration,label)
        audio_labels.append(label);audio_seen.add(c['id'])

    if len(audio_labels)>1:
        flabels=''.join('['+x+']' for x in audio_labels)
        filters.append(f'{flabels}amix=inputs={len(audio_labels)}:duration=first:normalize=0,'
                       f'atrim=end_sample={samples}[mixed]')
    else:
        filters.append(f'[1:a]atrim=end_sample={samples}[mixed]')

    filters.append(f'[{last}]trim=end_frame={nframes},format=yuv420p[finished]')
    if quality=='frame' or stream=='video':filters.append('[mixed]anullsink')
    if stream=='audio':filters.append('[finished]nullsink')
    script=jobdir/f'graph_{target.stem}.txt'
    script.write_text(';\n'.join(filters)+'\n',encoding='utf-8')
    if stream=='audio':
        return cmd+['-/filter_complex',str(script),'-map','[mixed]','-vn','-t',_num(duration),
                    '-c:a','pcm_s16le','-ac','2','-ar','48000',str(target)]
    if quality=='frame':
        return cmd+['-/filter_complex',str(script),'-map','[finished]','-frames:v','1','-threads','1','-c:v','png',str(target)]
    crf='26' if quality in ('review','preview') else str(state['output'].get('crf',20))
    preset='ultrafast' if continuous else 'veryfast' if quality=='review' else str(state['output'].get('preset','medium'))
    encoder='libx264' if quality in ('review','preview') else state['output'].get('encoder','libx264')
    bitrate=0 if quality in ('review','preview') else state['output'].get('bitrate',0)
    video_options=encoders.options(encoder,preset,crf,bitrate)
    if stream=='video':
        return cmd+['-/filter_complex',str(script),'-map','[finished]','-an','-t',_num(duration),
                    '-r',str(fps),*video_options,'-pix_fmt','yuv420p','-threads','4',
                    '-movie_timescale','120000','-video_track_timescale','120000','-movflags','+faststart',str(target)]
    cmd+=['-/filter_complex',str(script),'-map','[finished]','-map','[mixed]',
          '-t',_num(duration),'-r',str(fps),*video_options,'-pix_fmt','yuv420p','-c:a','aac' if continuous else 'pcm_s16le',
          '-threads','4','-ac','2','-ar','48000','-movie_timescale','120000','-video_track_timescale','120000','-movflags','+faststart',str(target)]
    return cmd

def render_range(state,start,end,target,jobdir,quality='final',runner=None):
    """Drain video and audio independently before muxing complete streams."""
    runner=runner or _run
    video=jobdir/(target.stem+'_video'+target.suffix)
    audio=jobdir/(target.stem+'_audio.wav')
    runner(segment_command(state,start,end,video,jobdir,quality,'video'),str(jobdir))
    runner(segment_command(state,start,end,audio,jobdir,quality,'audio'),str(jobdir))
    codec=['-c:a','aac','-b:a','192k'] if quality=='preview' else ['-c:a','copy']
    runner(['ffmpeg','-hide_banner','-nostdin','-loglevel','error','-y','-i',str(video),'-i',str(audio),
            '-map','0:v:0','-map','1:a:0','-c:v','copy',*codec,'-movie_timescale','120000',
            '-video_track_timescale','120000','-movflags','+faststart',str(target)],str(jobdir))
    video.unlink(missing_ok=True);audio.unlink(missing_ok=True)


def render(state, output, work, *, review=False, on_progress=None, cancelled=lambda:False, popen=None):
    """Export a sequence using a bounded-memory segment renderer.

    popen is callback(command, cwd) that runs FFmpeg and handles cancellation.
    """
    state=sequences.playback(state)
    duration=sequence_duration(state)
    if duration<=0:raise ValueError('Add at least one clip to the timeline')
    jobdir=Path(work);jobdir.mkdir(parents=True,exist_ok=True)
    fps=timing.rate(state['output']['fps'])
    segments=boundaries(state,fps)
    if any(Path(a['path']).resolve() == Path(output).resolve() for a in state['assets']):
        raise ValueError('Choose a destination different from source media')
    if not segments:raise ValueError('No usable frames in the timeline')
    runner=popen or _run
    parts=[]
    for idx,(start,end) in enumerate(segments):
        if cancelled():raise RuntimeError('Export cancelled')
        suffix='mp4' if ('av1' in state['output'].get('encoder','') and not review) else 'mov'
        target=jobdir/f'segment_{idx:05d}.{suffix}'
        if on_progress:on_progress(round(3+start/duration*91),f'Rendering scene {idx+1} / {len(segments)}')
        render_range(state,start,end,target,jobdir,'review' if review else 'final',runner)
        parts.append(target)
    files=jobdir/'concat.txt'
    entries=[]
    for part,(start,end) in zip(parts,segments):
        us=round(end*1_000_000)-round(start*1_000_000)
        entries.append(f"file '{part.name}'\nduration {us/1e6:.6f}\n")
    files.write_text(''.join(entries),encoding='utf8')
    if on_progress:on_progress(96,'Joining rendered scenesâ€¦')
    target=Path(output)
    target.parent.mkdir(parents=True,exist_ok=True)
    part=jobdir/'delivery.partial.mp4'
    if part.exists():part.unlink()
    try:
        runner(['ffmpeg','-hide_banner','-nostdin','-loglevel','error','-y',
               '-f','concat','-safe','0','-i',str(files),'-c:v','copy','-c:a','aac','-b:a','192k','-movflags','+faststart',str(part)],str(jobdir))
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
