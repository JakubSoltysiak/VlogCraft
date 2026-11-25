"""Index verified H.264 and HEVC random access points in local MP4/MOV media."""
from bisect import bisect_left
from dataclasses import dataclass
import json

from hdr10plus_bitstream import codec_configuration


MAX_PICTURES = 100_000
MAX_LEADING = 32


@dataclass(frozen=True)
class AccessPoint:
    picture: int
    kind: int
    dts: int
    position: int
    decodable_leading: tuple


def picture_type(source, packet, length_width, hevc):
    """Read one sample's NAL headers, including all its slices."""
    _, _, position, size, _ = packet
    source.seek(position)
    end = position + size
    header_width = 2 if hevc else 1
    kinds = set()
    while source.tell() < end:
        header = source.read(length_width + header_width)
        if len(header) != length_width + header_width:
            return None
        length = int.from_bytes(header[:length_width], "big")
        next_nal = source.tell() + length - header_width
        if length < header_width or next_nal > end or header[length_width] & 0x80:
            return None
        if hevc:
            kind = (header[length_width] >> 1) & 63
            # This index supports one independently decoded video layer.
            if header[length_width] & 1 or header[-1] >> 3 or not header[-1] & 7:
                return None
            if kind < 32:
                kinds.add(kind)
        else:
            kind = header[length_width] & 31
            if kind in (14, 19, 20, 21):
                return None
            if 1 <= kind <= 5:
                kinds.add(kind)
        source.seek(next_nal)
    return kinds.pop() if len(kinds) == 1 else None


def access_points(path, packets, stamps, length_width, hevc):
    keys = [index for index, packet in enumerate(packets) if packet[4]]
    if not keys:
        return []
    last = len(packets)
    # Every retained timestamp after the anchor must still be reachable in
    # decode order. Reject edits or reordered groups that cross this boundary.
    preceding_max = max((row[0] for row in packets[:keys[0]]), default=None)
    points = []
    with path.open("rb") as source:
        for first, end in zip(keys, [*keys[1:], last], strict=True):
            packet = packets[first]
            pts, dts, position, _, _ = packet
            group = packets[first:end]
            before = preceding_max
            preceding_max = max(row[0] for row in group)
            if before is not None:
                preceding_max = max(preceding_max, before)
            if before is not None and before >= pts:
                continue
            kind = picture_type(source, packet, length_width, hevc)
            if kind not in (range(16, 22) if hevc else (5,)):
                continue
            leading = [row for row in group[1:] if row[0] < pts]
            if len(leading) > MAX_LEADING or (leading and not hevc):
                continue
            # A CRA/BLA can be followed in decode order by pictures presented
            # before it. libavcodec suppresses RASL when starting at that IRAP.
            # Only the independently decodable RADL pictures may be returned.
            leading_kinds = [(row[0], picture_type(source, row, length_width, hevc)) for row in leading]
            allowed = {6, 7, 8, 9} if kind in (16, 21) else {6, 7} if kind in (17, 19) else set()
            if any(nal not in allowed for _, nal in leading_kinds):
                continue
            radl = tuple(sorted(tick for tick, nal in leading_kinds if nal in (6, 7)))
            points.append(AccessPoint(bisect_left(stamps, pts), kind, dts, position, radl))
    return points


def probe(path, limit, stream_fields, capture, cancelled):
    """Return the packet picture clock and access points, or use decoded probing."""
    stream_data, errors = capture(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_data", "-show_entries",
         f"{stream_fields},codec_tag_string,extradata:format=start_time,format_name:stream_side_data=rotation",
         "-of", "json", path],
        cancelled=cancelled)
    info = json.loads(stream_data)
    streams = info.get("streams", ())
    if errors or len(streams) != 1 or "mp4" not in info.get("format", {}).get("format_name", "").split(","):
        return None
    stream = streams[0]
    codec = (stream.get("codec_name"), stream.get("codec_tag_string"))
    # avc1 and hvc1 carry their parameter sets in the sample description.
    # In-band configuration changes require a separate qualification.
    if codec not in (("h264", "avc1"), ("hevc", "hvc1")) or "extradata" not in stream:
        return None
    hevc = codec[0] == "hevc"
    try:
        config = codec_configuration(stream)
    except (ValueError, IndexError):
        return None
    length_offset = 21 if hevc else 4
    if len(config) <= length_offset or config[0] != 1:
        return None
    length_width = (config[length_offset] & 3) + 1
    if length_width not in (1, 2, 4):
        return None
    packet_data, errors = capture(
        ["ffprobe", "-v", "error", "-read_intervals", f"%+{float(limit):.8f}", "-select_streams", "v:0",
         "-show_entries", "packet=pts,dts,pos,size,flags", "-of", "json", path], cancelled=cancelled)
    rows = json.loads(packet_data).get("packets", ())
    if errors or not 0 < len(rows) <= MAX_PICTURES:
        return None
    packets = []
    file_size = path.stat().st_size
    for row in rows:
        pts, dts, flags = (row.get(field) for field in ("pts", "dts", "flags"))
        try:
            position, size = (int(row[field]) for field in ("pos", "size"))
        except (KeyError, TypeError, ValueError):
            return None
        if (type(pts) is not int or type(dts) is not int or
                not isinstance(flags, str) or "D" in flags or "C" in flags or
                position < 0 or size <= 0 or position + size > file_size):
            return None
        if packets and dts <= packets[-1][1]:
            return None
        packets.append((pts, dts, position, size, "K" in flags))
    stamps = sorted(packet[0] for packet in packets)
    if any(a == b for a, b in zip(stamps, stamps[1:])):
        return None
    return info, stamps, access_points(path, packets, stamps, length_width, hevc)
