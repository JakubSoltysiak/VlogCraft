"""Picture-identity-only HDR10+ timeline delivery."""
from fractions import Fraction
from itertools import zip_longest
from pathlib import Path

import timing
from hdr10plus_bitstream import (
    codec_configuration, conformance_issues, length_size, packet_records, probe_streams, sample_metadata,
)


NEUTRAL = {
    'position':0, 'start':0, 'speed':1, 'volume':1, 'opacity':1,
    'scale':1, 'x':0, 'y':0, 'rotation':0, 'grade':'neutral',
    'fadeIn':0, 'fadeOut':0, 'hdrExposure':0, 'brightness':0, 'contrast':1,
    'saturation':1, 'mask':'none', 'chroma':False, 'wipe':'none',
    'audioDetached':False, 'bass':0, 'treble':0, 'pan':0, 'compress':1, 'fit':'contain',
}
VIDEO_FIELDS = ('codec_name','profile','width','height','pix_fmt','sample_aspect_ratio',
                'color_range','color_space','color_transfer','color_primaries')
AUDIO_FIELDS = ('codec_name','profile','channels','channel_layout','sample_rate')


def timeline_source(state):
    entries = [(track,clip) for track in state['tracks'] for clip in track['clips']]
    if len(entries)!=1 or entries[0][1]['kind']!='video':
        raise ValueError('HDR10+ preservation requires exactly one unedited video clip')
    track, clip = entries[0]
    if track.get('hidden') or track.get('muted') or track.get('volume',1)!=1:
        raise ValueError('HDR10+ preservation requires the original video and audio')
    if any(t.get('solo') for t in state['tracks']) and not track.get('solo'):
        raise ValueError('HDR10+ preservation requires audible original audio')
    if any(clip.get(key,value)!=value for key,value in NEUTRAL.items()) or any(
        clip.get(key) for key in ('inputColor','keys','look','lutId')
    ):
        raise ValueError('HDR10+ preservation cannot apply effects, trims, retiming or audio edits')
    asset = next(a for a in state['assets'] if a['id']==clip['assetId'])
    return Path(asset['path']), clip


def media(path):
    info = probe_streams(path)
    if 'mp4' not in info['format']['format_name'].split(','):
        raise ValueError('HDR10+ preservation requires an MP4 or MOV source')
    streams = info['streams']
    if len(streams) not in (1,2) or streams[0]['codec_type']!='video' or (
        len(streams)==2 and (streams[1]['codec_type'],streams[1]['codec_name'])!=('audio','aac')
    ):
        raise ValueError('HDR10+ preservation supports one HEVC video stream and optional AAC audio')
    video = streams[0]
    expected = ('hevc','Main 10','yuv420p10le','1:1','tv','bt2020nc','smpte2084','bt2020')
    if tuple(video.get(k) for k in VIDEO_FIELDS if k not in ('width','height'))!=expected:
        raise ValueError('HDR10+ preservation requires square-pixel limited-range PQ Rec.2020 HEVC Main10')
    if any(s.get('side_data_type')=='Display Matrix' for s in video.get('side_data_list',[])):
        raise ValueError('HDR10+ preservation does not apply container orientation transforms')
    length_size(video)
    return streams


def check_source(path,video,clip,output,cancelled):
    if (video['width'],video['height'])!=(output['width'],output['height']):
        raise ValueError('Match the sequence dimensions to the original for HDR10+ preservation')
    base = Fraction(video['time_base'])
    if base.numerator!=1:
        raise ValueError('Unsupported original video time base')
    rate = timing.rate(output['fps'])
    expected_frames = timing.frame_at(clip['end'],rate)
    if expected_frames<=0:
        raise ValueError('No video frames to preserve')
    seen = bytearray(expected_frames)
    width = length_size(video)
    count = 0
    with path.open('rb') as source, packet_records(path,'v:0') as packets:
        for row in packets:
            if cancelled():
                raise RuntimeError('Export cancelled')
            block = sample_metadata(source,int(row[b'pos']),int(row[b'size']),width)
            if block is None:
                raise ValueError('HDR10+ preservation requires dynamic metadata on every picture')
            issues = conformance_issues(block)
            if issues:
                raise ValueError('Original HDR10+ metadata fails the version 1 reuse gate ('+', '.join(issues)+')')
            if block['anchors']!=tuple(sorted(block['anchors'])):
                raise ValueError('Original tone mapping curve is outside the verified reuse subset')
            frame = int(row[b'pts'])*base*rate
            frame_duration = int(row[b'duration'])*base*rate
            if frame.denominator!=1 or not 0<=frame<expected_frames or frame_duration!=1 or seen[int(frame)]:
                raise ValueError('HDR10+ preservation requires the original constant frame rate and exact sequence cadence')
            seen[int(frame)] = 1
            count += 1
    if count!=expected_frames:
        raise ValueError('HDR10+ preservation requires the complete original video duration')
    return count, base.denominator


def static_metadata(stream):
    return [d for d in stream.get('side_data_list',[]) if d.get('side_data_type') in (
        'Mastering display metadata','Content light level metadata')]


def verify_copy(source,dest,streams,cancelled):
    completed = media(dest)
    if len(streams)!=len(completed):
        raise ValueError('HDR10+ stream count changed during remux')
    for i,(before,after) in enumerate(zip(streams,completed)):
        fields = VIDEO_FIELDS if i==0 else AUDIO_FIELDS
        if any(before.get(k)!=after.get(k) for k in fields) or (
            codec_configuration(before)!=codec_configuration(after) or static_metadata(before)!=static_metadata(after)
        ):
            raise ValueError('HDR10+ codec or color information changed during remux')
        a_base,b_base = Fraction(before['time_base']),Fraction(after['time_base'])
        if any(int(before[key])*a_base!=int(after[key])*b_base for key in ('start_pts','duration_ts')):
            raise ValueError('HDR10+ stream endpoints changed during remux')
        selector = 'a:0' if i else 'v:0'
        with packet_records(source,selector,hashes=True) as originals, packet_records(dest,selector,hashes=True) as copies:
            for a,b in zip_longest(originals,copies):
                if cancelled():
                    raise RuntimeError('Export cancelled')
                if a is None or b is None or a[b'data_hash']!=b[b'data_hash'] or any(
                    int(a[k])*a_base!=int(b[k])*b_base for k in (b'pts',b'dts',b'duration')
                ):
                    raise ValueError('HDR10+ compressed picture/audio or packet timing changed during remux')


def render(state,partial,runner,stage,cancelled):
    source,clip = timeline_source(state)
    streams = media(source)
    identity = source.stat()
    frames, timescale = check_source(source,streams[0],clip,state['output'],cancelled)
    if len(streams)==2:
        audio = streams[1]
        base = Fraction(audio['time_base'])
        endpoint = (int(audio['start_pts'])+int(audio['duration_ts']))*base
        fps = timing.rate(state['output']['fps'])
        if abs(endpoint*fps-frames)>1:
            raise ValueError('Original audio endpoint differs from the complete video by more than one frame')
    stage('Copying original HDR10+ video and audio',10)
    command = ['ffmpeg','-nostdin','-v','error','-y','-copyts','-i',str(source),
               '-map','0:v:0','-map','0:a:0?','-map_metadata','-1','-map_chapters','-1',
               '-c','copy','-tag:v','hvc1','-avoid_negative_ts','disabled',
               '-video_track_timescale',str(timescale),'-movflags','+faststart',str(partial)]
    runner(command,str(partial.parent))
    stage('Comparing compressed packets, HDR signalling and timestamps',90)
    verify_copy(source,partial,streams,cancelled)
    newest = source.stat()
    if (identity.st_size,identity.st_mtime_ns,identity.st_ino)!=(newest.st_size,newest.st_mtime_ns,newest.st_ino):
        raise ValueError('Original changed while preserving HDR10+')
    return frames
