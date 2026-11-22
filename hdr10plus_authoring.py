"""Whole-picture ST 2094-40 version-1 statistics for a decoded PQ master."""
from contextlib import ExitStack, contextmanager
import subprocess
import tempfile

import numpy as np

from color_management import pq_to_nits
from hdr10plus_bitstream import CREATE_FLAGS, T35


PERCENTILES = (1, 5, 10, 25, 50, 75, 90, 95, 99)
LINEAR = pq_to_nits(np.arange(65536) / 65535) / 10000
PAYLOAD_BYTES = len(T35) + (8 + 2 + 27 + 1 + 4*17 + 4 + 9*24 + 10 + 3 + 7)//8


def statistics(frame):
    """Analyze planar PQ GBR16; each output frame is one analysis interval."""
    histogram = np.zeros(65536, dtype=np.int64)
    height = frame.shape[1]
    for start in range(0, height, 128):
        tile = frame[:, start:start+128, :]
        histogram += np.bincount(np.max(tile, axis=0).ravel(), minlength=65536)
    return summarize(histogram, frame.max(axis=(1, 2)), frame.shape[1] * frame.shape[2])


def summarize(histogram, channel_maxima, count):
    """Use the same rank, PQ lookup and rounding for any exact histogram."""
    cdf = np.cumsum(histogram)
    levels = []
    for percentage in PERCENTILES:
        if percentage in (5, 10):
            levels.append(0 if percentage == 5 else 255)
        else:
            # 99 means 99.98% for this distribution vector.
            numerator = 9998 if percentage == 99 else percentage * 100
            rank = (count*numerator + 9999)//10000
            levels.append(round(LINEAR[cdf.searchsorted(rank)]*100000))
    g, b, r = channel_maxima
    maximum = tuple(round(LINEAR[code]*100000) for code in (r, g, b))
    average = round(float(np.sum(histogram*LINEAR))*100000/count)
    return maximum, average, tuple(zip(PERCENTILES, levels))


def payload(frame):
    return serialize(statistics(frame))


def serialize(values):
    maximum, average, distribution = values
    # Profile A: no target-display curve or peak matrices. FractionBrightPixels
    # is explicitly uncalculated as permitted by ST 2094-40 §8.6.
    fields = [(1,8), (1,2), (0,27), (0,1)]
    fields += [(value,17) for value in (*maximum, average)] + [(len(distribution),4)]
    for percentile, value in distribution:
        fields.extend(((percentile,7), (value,17)))
    fields.extend(((0,10), (0,1), (0,1), (0,1)))
    value = length = 0
    for field, width in fields:
        value = (value << width) | field
        length += width
    return T35 + (value << ((-length)%8)).to_bytes((length+7)//8, 'big')


def prefix_sei(data, temporal_id):
    """Encode a single registered T.35 message with HEVC emulation prevention."""
    rbsp = bytes((4, len(data))) + data + b'\x80'
    escaped = bytearray((39 << 1, temporal_id))
    zeros = 0
    for byte in rbsp:
        if zeros == 2 and byte <= 3:
            escaped.append(3)
            zeros = 0
        escaped.append(byte)
        zeros = 0 if byte else zeros+1
    return bytes(escaped)


@contextmanager
def decoded_frames(path, width, height, cancelled, owns_process=lambda _:None, *, output_pipe=None):
    """Yield exactly one reconstructed frame at a time in presentation order."""
    matrix = ('zscale=agamma=0:pin=2020:tin=smpte2084:min=2020_ncl:rin=limited:'
              'p=2020:t=smpte2084:m=gbr:r=full:filter=bilinear,format=gbrp16le')
    args = ['ffmpeg','-v','error','-nostdin','-threads','4','-i',str(path),
            '-map','0:v:0','-an','-sn','-dn','-filter_threads','2','-vf',matrix,
            '-fps_mode','passthrough','-c:v','rawvideo','-threads','1',
            '-pix_fmt','gbrp16le','-f','rawvideo','pipe:1']
    frame_bytes = width * height * 6
    with ExitStack() as stack:
        errors = stack.enter_context(tempfile.TemporaryFile())
        reader, writer = stack.enter_context(output_pipe()) if output_pipe else (None, subprocess.PIPE)
        process = stack.enter_context(subprocess.Popen(
            args, stdout=writer, stderr=errors, creationflags=CREATE_FLAGS))
        if reader is None:
            reader = process.stdout
        else:
            writer.close()
        owns_process(process)
        def pictures():
            while not cancelled():
                raw = reader.read(frame_bytes)
                if cancelled():
                    raise RuntimeError('Export cancelled')
                if not raw:
                    break
                if len(raw) != frame_bytes:
                    raise ValueError('Incomplete HDR10+ analysis picture')
                yield np.frombuffer(raw, dtype='<u2').reshape(3, height, width)
            if cancelled():
                raise RuntimeError('Export cancelled')
            if process.wait() or errors.seek(0,2):
                raise ValueError('FFmpeg could not decode all final HDR10+ pictures')
        try:
            yield pictures()
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            owns_process(None)
