"""Attach authored metadata to the existing managed HEVC encode without re-encoding."""
from fractions import Fraction
from itertools import zip_longest
from pathlib import Path
import shutil
import struct

import timing
import color_management
import hdr_render
import render_engine
import sequences
import timeline_transitions
from hdr10plus_authoring import PAYLOAD_BYTES, decoded_frames, payload, prefix_sei
from hdr10plus_bitstream import codec_configuration, length_size, packet_records, sei_payloads
from hdr10plus_export import AUDIO_FIELDS, VIDEO_FIELDS, media, static_metadata


def preflight(state, require_mastering=True):
    state = sequences.playback(state)
    if timeline_transitions.present(state):
        timeline_transitions.plan(state)
    output = state['output']
    if (output.get('color') or {}).get('output') != 'hdr10' or output.get('encoder') != 'libx265':
        raise ValueError('This HDR delivery requires managed PQ and the HEVC CPU encoder')
    contract = color_management.validate_output(output['color'])
    if require_mastering and not contract.get('mastering'):
        raise ValueError('Enter the known mastering-display gamut, black level and peak in Advanced color settings')
    duration = render_engine.sequence_duration(state)
    video,_ = render_engine.active_clips(state,0,duration)
    if not video:
        raise ValueError('This HDR delivery requires a visible video clip')
    assets = {asset['id']:asset for asset in state['assets']}
    for _,clip in video:
        hdr_render.layer_contract(assets,clip,output['width'],output['height'])
    count = timing.frame_at(duration,timing.rate(output['fps']))
    if not count:
        raise ValueError('The timeline is shorter than one output frame')
    return count


def children(atom, kind):
    offset = 8
    while offset < len(atom):
        size, name = struct.unpack_from('>I4s', atom, offset)
        if size < 8 or offset + size > len(atom):
            raise ValueError('Unexpected HDR10+ fragment structure')
        if name == kind:
            yield offset
        offset += size


def fragment_size_offset(moof, expected):
    """Accept the single-track, single-sample format generated for this job."""
    traf_offset, = children(moof, b'traf')
    size = struct.unpack_from('>I', moof, traf_offset)[0]
    traf = moof[traf_offset:traf_offset+size]
    tfhd, = children(traf, b'tfhd')
    trun, = children(traf, b'trun')
    tfhd_flags, track, _, sample_size = struct.unpack_from('>4I', traf, tfhd+8)
    trun_flags, samples, data_offset = struct.unpack_from('>3I', traf, trun+8)
    # tfhd supplies default duration, size and flags. trun may supply the
    # first-sample flags or composition offset but never a sample size.
    if (tfhd_flags != 0x020038 or track != 1 or sample_size != expected or
        trun_flags & 0xffffff not in (0x1, 0x5, 0x801, 0x805) or
        samples != 1 or data_offset != len(moof)+8):
        raise ValueError('Unsupported HDR10+ fragment sample table')
    return traf_offset+tfhd+20


def read_atom(source, wanted, expected_size=None):
    header = source.read(8)
    if len(header) != 8:
        raise ValueError('Missing HDR10+ transport atom')
    size, actual = struct.unpack('>I4s', header)
    if actual != wanted or size < 8 or (expected_size is not None and size != expected_size):
        raise ValueError('Unexpected HDR10+ transport atom')
    body = source.read(size-8)
    if len(body) != size-8:
        raise ValueError('Truncated HDR10+ transport atom')
    return header + body


def sample_with_metadata(sample, width, block):
    offset = 0
    insert = None
    while offset < len(sample):
        nal_start = offset + width
        end = nal_start + int.from_bytes(sample[offset:nal_start], 'big')
        if end < nal_start+2 or end > len(sample):
            raise ValueError('Invalid length in edited HEVC picture')
        kind = (sample[nal_start] >> 1) & 63
        if kind in (39,40) and any(sei_payloads(sample[nal_start+2:end])):
            raise ValueError('Unexpected source HDR10+ metadata in the edited encode')
        if kind < 32 and insert is None:
            nal = prefix_sei(block, sample[nal_start+1] & 7)
            insert = offset, len(nal).to_bytes(width, 'big') + nal
        offset = end
    if insert is None:
        raise ValueError('Edited HEVC sample contains no coded picture')
    offset, message = insert
    return sample[:offset] + message + sample[offset:]


def picture_number(packet, time_base, fps, count):
    frame = int(packet[b'pts']) * time_base * fps
    if (frame.denominator != 1 or not 0 <= frame < count or
        int(packet[b'duration'])*time_base*fps != 1):
        raise ValueError('Edited picture PTS or duration does not match the output frame clock')
    return int(frame)


def record_for(records, frame):
    records.seek(frame*PAYLOAD_BYTES)
    data = records.read(PAYLOAD_BYTES)
    if len(data) != PAYLOAD_BYTES:
        raise ValueError('Missing HDR10+ data for edited picture')
    return data


def inject(original, fragments, marked, records, width, time_base, fps, count, cancelled):
    used = bytearray(count)
    with (original.open('rb') as source, fragments.open('rb') as fragment,
          marked.open('wb') as output, records.open('rb') as metadata,
          packet_records(original,'v:0') as packets):
        output.write(read_atom(fragment, b'ftyp'))
        output.write(read_atom(fragment, b'moov'))
        for packet in packets:
            if cancelled():
                raise RuntimeError('Export cancelled')
            frame = picture_number(packet, time_base, fps, count)
            if used[frame]:
                raise ValueError('Duplicate edited picture PTS')
            used[frame] = 1
            source.seek(int(packet[b'pos']))
            size = int(packet[b'size'])
            sample = source.read(size)
            moof = bytearray(read_atom(fragment, b'moof'))
            size_offset = fragment_size_offset(moof, size)
            mdat = read_atom(fragment, b'mdat', size+8)
            if mdat[8:] != sample:
                raise ValueError('HEVC sample changed during fragment preparation')
            assembled = sample_with_metadata(sample, width, record_for(metadata,frame))
            struct.pack_into('>I', moof, size_offset, len(assembled))
            output.write(moof)
            output.write(struct.pack('>I4s', len(assembled)+8, b'mdat'))
            output.write(assembled)
        if not all(used) or fragment.read(1):
            raise ValueError('Edited frame coverage does not match the timeline')


def verify(original, output, streams, records, width, fps, count, cancelled):
    final = media(output)
    if len(streams) != len(final):
        raise ValueError('HDR10+ export changed the stream count')
    for index, (before,after) in enumerate(zip(streams,final)):
        fields = AUDIO_FIELDS if index else VIDEO_FIELDS
        before_base,after_base = (Fraction(stream['time_base']) for stream in (before,after))
        if (any(before.get(field) != after.get(field) for field in fields) or
            codec_configuration(before) != codec_configuration(after) or
            static_metadata(before) != static_metadata(after) or
            any(int(before[key])*before_base != int(after[key])*after_base
                for key in ('start_pts','duration_ts'))):
            raise ValueError('HDR10+ export changed stream signaling or duration')
        selector = 'a:0' if index else 'v:0'
        with (packet_records(original, selector, hashes=bool(index)) as source_packets,
              packet_records(output, selector, hashes=bool(index)) as output_packets,
              records.open('rb') as metadata, original.open('rb') as source, output.open('rb') as delivery):
            for a,b in zip_longest(source_packets,output_packets):
                if cancelled():
                    raise RuntimeError('Export cancelled')
                if (a is None or b is None or
                    any(int(a[k])*before_base != int(b[k])*after_base for k in (b'pts',b'dts',b'duration'))):
                    raise ValueError('HDR10+ export changed compressed packet timing')
                if index:
                    if a[b'data_hash'] != b[b'data_hash']:
                        raise ValueError('HDR10+ export changed compressed audio')
                    continue
                source.seek(int(a[b'pos']))
                delivery.seek(int(b[b'pos']))
                frame = picture_number(a, before_base, fps, count)
                expected = sample_with_metadata(source.read(int(a[b'size'])), width, record_for(metadata,frame))
                if delivery.read(int(b[b'size'])) != expected:
                    raise ValueError('HDR10+ export changed compressed pictures or metadata association')


def author(original, output, work, fps, count, runner, stage, cancelled, owns_process=lambda _:None):
    """Author, insert and verify every picture before caller publishes output."""
    original, output, work = map(Path, (original,output,work))
    fps = timing.rate(fps)
    streams = media(original)
    video = streams[0]
    width = length_size(video)
    time_base = Fraction(video['time_base'])
    if time_base.numerator != 1 or count < 1:
        raise ValueError('Unsupported edited HDR10+ output time base')
    records, fragments, marked = (work/name for name in ('pictures.bin','fragments.mp4','authored.mp4'))
    # Static output, video-only fragments, marked fragments and final output
    # coexist briefly. Leave room for metadata and container headers.
    if shutil.disk_usage(work).free < 3*original.stat().st_size + 4096*count:
        raise ValueError('Not enough free working disk space to author and verify the HDR10+ master')
    stage('Analyzing final PQ pictures for HDR10+ metadata', 93)
    with records.open('wb') as file, decoded_frames(
            original,video['width'],video['height'],cancelled,owns_process) as frames:
        actual = 0
        for frame in frames:
            actual += 1
            if actual > count:
                raise ValueError('Too many decoded HDR10+ pictures')
            file.write(payload(frame))
            if actual % 60 == 0:
                stage(f'Analyzing final PQ pictures · {actual} / {count}', 93)
        if actual != count:
            raise ValueError('Decoded HDR10+ picture count does not match the timeline')
    base = str(time_base.denominator)
    ff = ['ffmpeg','-hide_banner','-v','error','-nostdin','-y']
    stage('Attaching metadata in HEVC decode order', 95)
    runner(ff+['-i',str(original),'-map','0:v','-c','copy','-video_track_timescale',base,
              '-movflags','+empty_moov+frag_every_frame+default_base_moof+skip_trailer+negative_cts_offsets',
              str(fragments)],str(work))
    inject(original,fragments,marked,records,width,time_base,fps,count,cancelled)
    fragments.unlink()
    runner(ff+['-i',str(marked),'-i',str(original),'-map','0:v','-map','1:a:0?','-c','copy',
              '-tag:v','hvc1','-video_track_timescale',base,'-movie_timescale',base,
              '-movflags','+faststart',str(output)],str(work))
    stage('Verifying HDR10+ pictures, audio and timestamps', 98)
    verify(original,output,streams,records,width,fps,count,cancelled)
    return count
