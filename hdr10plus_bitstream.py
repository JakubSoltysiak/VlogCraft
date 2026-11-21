"""Read version-1 HDR10+ SEI directly from HEVC samples in MP4/MOV.

FFprobe supplies container packet offsets and timestamps. It does not decode
the HDR payload for this reader. The supported payload is ST 2094-40:2020
application version 1, single processing window.
"""
from contextlib import contextmanager
import json
import re
import subprocess
import tempfile


T35 = bytes.fromhex('b5 00 3c 00 01 04')
CREATE_FLAGS = getattr(subprocess,'CREATE_NO_WINDOW',0)


class UnsupportedMetadata(ValueError):
    """The block falls outside this reader's qualified subset."""


class Bits:
    def __init__(self, data):
        self.remaining = len(data)*8
        self.value = int.from_bytes(data,'big')

    def get(self,width):
        self.remaining -= width
        if self.remaining<0:
            raise ValueError('Truncated HDR10+ payload')
        return (self.value >> self.remaining) & ((1 << width)-1)


def parse_payload(data):
    if not data.startswith(T35):
        raise ValueError('Not an HDR10+ T.35 payload')
    bits = Bits(data[len(T35):])
    version = bits.get(8)
    if version!=1:
        raise UnsupportedMetadata('Unsupported HDR10+ application version')
    if bits.get(2)!=1:
        raise ValueError('Version 1 requires one processing window')
    peak = bits.get(27)
    if bits.get(1):
        raise ValueError('Version 1 forbids the target peak matrix')
    maxrgb = tuple(bits.get(17) for _ in range(3))
    average = bits.get(17)
    distribution = tuple((bits.get(7),bits.get(17)) for _ in range(bits.get(4)))
    bright = bits.get(10)
    if bits.get(1):
        raise ValueError('Version 1 forbids the mastering peak matrix')
    knee = None
    anchors = ()
    if bits.get(1):
        knee = bits.get(12),bits.get(12)
        anchors = tuple(bits.get(10) for _ in range(bits.get(4)))
    if bits.get(1):
        raise ValueError('Version 1 forbids saturation mapping')
    if bits.remaining>7 or bits.get(bits.remaining)!=0:
        raise ValueError('Unexpected HDR10+ payload tail')
    return {'version':version,'peak':peak,'maxrgb':maxrgb,'average':average,
            'distribution':distribution,'bright':bright,'knee':knee,'anchors':anchors}


def distribution_issues(distribution):
    issues = []
    positions = [p for p,_ in distribution]
    values = [v for _,v in distribution]
    if len(positions)!=9 or positions!=sorted(set(positions)) or any(p>100 for p in positions):
        issues.append('distribution_vector')
    if positions[1:3]==[5,10]:
        if values[1]!=0:
            issues.append('reserved_5_percent')
        if values[2]!=255:
            issues.append('reserved_10_percent')
        values = values[:1]+values[3:]
    if values!=sorted(values):
        issues.append('descending_cfd')
    if any(v>100000 for v in values):
        issues.append('distribution_out_of_range')
    return issues


def conformance_issues(block):
    issues = distribution_issues(block['distribution'])
    if block['peak']>10000 or max(*block['maxrgb'],block['average'])>100000 or block['bright']>1000:
        issues.append('field_out_of_range')
    if len(block['anchors'])>9:
        issues.append('too_many_version_1_anchors')
    return issues


def sei_payloads(nal):
    # HEVC adds an emulation prevention byte after two zero bytes.
    rbsp = re.sub(b'\x00\x00\x03(?=[\x00-\x03])',b'\x00\x00',nal)
    offset = 0

    def extended():
        nonlocal offset
        start = offset
        while offset<len(rbsp) and rbsp[offset]==255:
            offset += 1
        if offset==len(rbsp):
            raise ValueError('Truncated HEVC SEI header')
        value = 255*(offset-start)+rbsp[offset]
        offset += 1
        return value

    while offset<len(rbsp):
        if rbsp[offset:]==b'\x80':
            return
        kind = extended()
        length = extended()
        end = offset+length
        if end>len(rbsp):
            raise ValueError('Truncated HEVC SEI message')
        if kind==4 and rbsp.startswith(T35,offset,end):
            yield rbsp[offset:end]
        offset = end
    raise ValueError('Missing HEVC SEI trailing bits')


def sample_metadata(source, position, length, length_width):
    source.seek(position)
    end = position+length
    payloads = []
    while source.tell()<end:
        prefix = source.read(length_width+2)
        if len(prefix)!=length_width+2:
            raise ValueError('Truncated HEVC sample')
        nal_size = int.from_bytes(prefix[:length_width],'big')
        next_offset = source.tell()+nal_size-2
        if nal_size<2 or next_offset>end:
            raise ValueError('Invalid HEVC sample NAL length')
        nal_type = (prefix[length_width] >> 1) & 63
        if nal_type in (39,40):
            if nal_size>1024*1024:
                raise UnsupportedMetadata('Oversized HEVC SEI unit')
            payloads.extend(sei_payloads(source.read(nal_size-2)))
        source.seek(next_offset)
    if len(payloads)>1:
        raise UnsupportedMetadata('Multiple HDR10+ messages per video sample')
    return parse_payload(payloads[0]) if payloads else None


def probe_streams(path):
    result = subprocess.run(['ffprobe','-v','error','-show_streams','-show_format','-show_data',
                             '-of','json',str(path)],capture_output=True,check=True,timeout=30,
                            creationflags=CREATE_FLAGS)
    return json.loads(result.stdout)


def codec_configuration(stream):
    return bytes.fromhex(''.join(line.split(': ',1)[1].split('  ',1)[0].strip()
                                 for line in stream['extradata'].splitlines() if ': ' in line))


def length_size(stream):
    data = codec_configuration(stream)
    if stream.get('codec_tag_string') not in ('hvc1','hev1') or len(data)<23 or data[0]!=1:
        raise UnsupportedMetadata('HDR10+ bitstream inspection requires MP4/MOV HEVC samples')
    width = (data[21]&3)+1
    if width not in (1,2,4):
        raise UnsupportedMetadata('Unsupported HEVC NAL length width')
    return width


@contextmanager
def packet_records(path, stream, *, hashes=False):
    fields = 'pts,dts,duration,size,pos,flags,data_hash' if hashes else 'pts,dts,duration,size,pos,flags'
    command = ['ffprobe','-v','error','-select_streams',stream,'-show_packets',
               '-show_entries','packet='+fields,'-of','compact=p=0',str(path)]
    if hashes:
        command[1:1] = ['-show_data_hash','sha256']
    with tempfile.TemporaryFile() as errors:
        with subprocess.Popen(command,stdout=subprocess.PIPE,stderr=errors,creationflags=CREATE_FLAGS) as process:
            def rows():
                for line in process.stdout:
                    if line.startswith(b'pts='):
                        yield dict(part.split(b'=',1) for part in line.strip().split(b'|') if b'=' in part)
                if process.wait() or errors.seek(0,2):
                    raise ValueError('FFprobe could not read all source packets')
            try:
                yield rows()
            finally:
                if process.poll() is None:
                    process.kill()
