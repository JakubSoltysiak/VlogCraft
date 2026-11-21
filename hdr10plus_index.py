"""Disk-backed index of decoded HDR10+ metadata and original presentation ticks."""
from collections import defaultdict
from contextlib import closing
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import threading
import xml.etree.ElementTree as ET

import timing


SIDE_DATA = 'HDR Dynamic Metadata SMPTE2094-40 (HDR10+)'
SCHEMA_VERSION = 2


def validated_metadata(data):
    """Accept the decoded version-1 single-window subset, preserving repeated fields."""
    fields = defaultdict(list)
    for item in data:
        if item.tag != 'side_datum':
            raise ValueError('Unexpected HDR10+ metadata structure')
        key, value = item.get('key',''), item.get('value','')
        if key != 'side_data_type':
            if not key or len(key)>96 or len(value)>48:
                raise ValueError('Invalid HDR10+ metadata field')
            fields[key].append(value)

    def values(key, count, maximum, *, integer=False):
        raw = fields.pop(key,[])
        if len(raw)!=count:
            raise ValueError('Unexpected HDR10+ field count')
        try:
            parsed = [Fraction(v) for v in raw]
        except (ValueError,ZeroDivisionError) as error:
            raise ValueError('Malformed HDR10+ numeric field') from error
        if any(v<0 or v>maximum or (integer and v.denominator!=1) for v in parsed):
            raise ValueError('HDR10+ field out of range')
        return parsed

    def count(key, maximum):
        return int(values(key,1,maximum,integer=True)[0])

    if count('application version',255)!=1 or count('num_windows',3)!=1:
        raise ValueError('Only version 1 single-window HDR10+ metadata is qualified for indexing')
    values('targeted_system_display_maximum_luminance',1,10000)
    values('maxscl',3,1)
    values('average_maxrgb',1,1)
    percentiles = count('num_distribution_maxrgb_percentiles',15)
    positions = values('distribution_maxrgb_percentage',percentiles,100,integer=True)
    levels = values('distribution_maxrgb_percentile',percentiles,1)
    if percentiles!=9 or positions!=sorted(set(positions)):
        raise ValueError('Invalid version 1 HDR10+ distribution vector')
    # ST 2094-40:2020 §8.5.4 reserves these two values. Some decoded
    # camera sources use other values. Preserve the observation but fence reuse.
    reserved = positions[1:3]==[5,10]
    histogram = levels[:1]+levels[3:] if reserved else levels
    conforming_distribution = histogram==sorted(histogram) and (
        not reserved or levels[1:3]==[0,Fraction(255,100000)]
    )
    values('fraction_bright_pixels',1,1)
    if any(key in fields for key in ('knee_point_x','knee_point_y','num_bezier_curve_anchors')):
        values('knee_point_x',1,1)
        values('knee_point_y',1,1)
        anchors = count('num_bezier_curve_anchors',15)
        values('bezier_curve_anchors',anchors,1)
    if fields:
        raise ValueError('HDR10+ metadata contains unqualified optional fields')
    return [[item.get('key'),item.get('value')] for item in data if item.get('key')!='side_data_type'], conforming_distribution


def index_xml(stream, database, cancelled=lambda:False):
    """Stream FFprobe XML, releasing each decoded frame before reading the next."""
    database.executescript("""
        CREATE TABLE frames (pts INTEGER PRIMARY KEY, duration INTEGER, metadata TEXT, rejected INTEGER NOT NULL);
        CREATE TABLE summary (data TEXT NOT NULL);
    """)
    counts = {'frames':0,'dynamicFrames':0,'rejectedFrames':0,'nonconformingDistributionFrames':0}
    last = None
    base = None
    origin = '0'
    parents = []
    for event,element in ET.iterparse(stream,events=('start','end')):
        if event=='start':
            parents.append(element)
            continue
        if cancelled():
            raise ValueError('HDR10+ indexing cancelled')
        if element.tag=='frame':
            text = element.get('pts',element.get('best_effort_timestamp'))
            pts = int(text) if text is not None else None
            if pts is None or (last is not None and pts<=last):
                raise ValueError('Missing or non-increasing original presentation timestamps')
            if element.get('best_effort_timestamp',text)!=text:
                raise ValueError('Decoded PTS disagrees with the best-effort timestamp')
            last = pts
            duration = int(element.get('duration','0'))
            if duration<0:
                raise ValueError('Invalid original frame duration')
            dynamic = element.findall(f"./side_data_list/side_data[@type='{SIDE_DATA}']")
            payload = None
            rejected = False
            if dynamic:
                try:
                    if len(dynamic)!=1:
                        raise ValueError('More than one HDR10+ block for a frame')
                    metadata,distribution_ok = validated_metadata(dynamic[0])
                    payload = json.dumps(metadata,separators=(',',':'))
                    counts['dynamicFrames']+=1
                    if not distribution_ok:
                        counts['nonconformingDistributionFrames']+=1
                        rejected = True
                except ValueError:
                    counts['rejectedFrames']+=1
                    rejected = True
            database.execute('INSERT INTO frames VALUES (?,?,?,?)',(pts,duration,payload,rejected))
            counts['frames']+=1
            parents[-2].remove(element)
        elif element.tag=='stream':
            if base is not None:
                raise ValueError('HDR10+ indexing requires exactly one selected video stream')
            base = Fraction(element.get('time_base','0'))
        elif element.tag=='format':
            origin = str(Fraction(element.get('start_time','0')))
        parents.pop()
    if not base or base<0 or not counts['frames']:
        raise ValueError('No usable timestamps or time base in original video')
    summary = {**counts,'timeBase':str(base),'formatStart':origin,'schema':SCHEMA_VERSION}
    database.execute('INSERT INTO summary VALUES (?)',(json.dumps(summary),))
    return summary


def timeline_frames(database, *, position, start, end, speed, first, last, fps):
    """Map a clip's sequence frames to source pictures using exact rational holds.

    The last frame index is exclusive. Metadata belongs only to the chosen
    picture, so an untagged picture stays untagged and a repeated picture repeats
    its own metadata. This mapping does not authorize reuse after a picture edit.
    """
    info = json.loads(database.execute('SELECT data FROM summary').fetchone()[0])
    base,origin = Fraction(info['timeBase']),Fraction(info['formatStart'])
    position,start,end,speed = map(timing.rational,(position,start,end,speed))
    fps = timing.rate(fps)
    if speed<=0 or start>=end or first<0 or last<first:
        raise ValueError('Invalid HDR10+ clip time mapping')
    clip_frame = timing.frame_at(position,fps)
    if first<clip_frame:
        raise ValueError('Frame requested before the clip')
    first_tick = (start+(first-clip_frame)/fps*speed+origin)/base
    seed = database.execute('SELECT max(pts) FROM frames WHERE pts<=?',(first_tick.numerator//first_tick.denominator,)).fetchone()[0]
    if seed is None:
        raise ValueError('No original picture at clip start')
    cursor = iter(database.execute('SELECT pts,duration,metadata,rejected FROM frames WHERE pts>=? ORDER BY pts',(seed,)))
    current = next(cursor)
    next_frame = next(cursor,None)
    for frame in range(first,last):
        source = start+(frame-clip_frame)/fps*speed
        if source>=end:
            raise ValueError('Frame requested beyond the clip out point')
        tick = (source+origin)/base
        while next_frame is not None and next_frame[0]<=tick:
            current,next_frame = next_frame,next(cursor,None)
        pts,duration,metadata,rejected = current
        if next_frame is None and (tick>=pts+duration if duration else tick>pts):
            raise ValueError('Frame requested beyond the final indexed source picture')
        if rejected:
            raise ValueError('Mapped source frame has unsupported, malformed or nonconforming HDR10+ metadata')
        yield frame,pts,json.loads(metadata) if metadata else None


class HDR10PlusIndex:
    """One cancellable low-priority FFprobe job per editor window."""
    def __init__(self,folder):
        self.folder = Path(folder).resolve()
        self.lock = threading.Lock()
        self.active = None
        self.closed = False
        self.last = None

    def path(self,asset):
        source = Path(asset['path']).resolve(strict=True)
        stat = source.stat()
        identity = repr((SCHEMA_VERSION,str(source),stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns))
        return self.folder/(hashlib.sha256(identity.encode()).hexdigest()+'.sqlite')

    def status(self,asset):
        destination = self.path(asset)
        with self.lock:
            if self.active and self.active['destination']==destination:
                return {'status':'indexing'}
            if self.last and self.last[0]==destination:
                return self.last[1]
        if destination.exists():
            with closing(sqlite3.connect(destination.as_uri()+'?mode=ro',uri=True)) as db:
                return {'status':'ready',**json.loads(db.execute('SELECT data FROM summary').fetchone()[0])}
        return {'status':'idle'}

    def start(self,asset):
        if asset.get('codec')!='hevc' or asset.get('colorTransfer')!='smpte2084' or asset.get('colorPrimaries')!='bt2020':
            raise ValueError('Select an original Rec.2020 PQ HEVC source for HDR10+ indexing')
        destination = self.path(asset)
        with self.lock:
            if self.closed:
                raise ValueError('HDR10+ indexing service is closed')
            if self.active:
                if self.active['destination']==destination:
                    return {'status':'indexing'}
                raise ValueError('Another HDR10+ source is being indexed')
            if not destination.is_file():
                task = {'destination':destination,'cancel':threading.Event(),'process':None}
                self.active = task
                self.last = None
                worker = threading.Thread(target=self._run,args=(asset,task),daemon=True,name='hdr10plus-index')
                task['worker'] = worker
                worker.start()
                return {'status':'indexing'}
        return self.status(asset)

    def cancel(self,asset=None):
        destination = self.path(asset) if asset else None
        with self.lock:
            task = self.active
            if task and (destination is None or destination==task['destination']):
                task['cancel'].set()
                process = task['process']
                if process and process.poll() is None:
                    process.terminate()

    def close(self):
        with self.lock:
            self.closed = True
            task = self.active
        self.cancel()
        if task:
            task['worker'].join(timeout=5)

    def _run(self,asset,task):
        destination = task['destination']
        cancelled = task['cancel'].is_set
        temporary = None
        result = {'status':'error','error':'Indexing ended before validation'}
        try:
            self.folder.mkdir(parents=True,exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=self.folder,suffix='.part',delete=False) as handle:
                temporary = Path(handle.name)
            command = ['ffprobe','-v','error','-threads','1','-select_streams','v:0',
                       '-show_frames','-show_streams','-show_format','-show_entries',
                       'frame=pts,best_effort_timestamp,duration:frame_side_data:stream=time_base:format=start_time',
                       '-of','xml',asset['path']]
            with tempfile.TemporaryFile() as errors:
                with self.lock:
                    if cancelled():
                        raise ValueError('Cancelled')
                    flags = getattr(subprocess,'CREATE_NO_WINDOW',0) | getattr(subprocess,'BELOW_NORMAL_PRIORITY_CLASS',0)
                    process = subprocess.Popen(command,stdout=subprocess.PIPE,stderr=errors,creationflags=flags)
                    task['process'] = process
                with process as probe,closing(sqlite3.connect(temporary)) as database:
                    try:
                        summary = index_xml(probe.stdout,database,cancelled)
                        if probe.wait() or errors.seek(0,os.SEEK_END):
                            raise ValueError('FFprobe reported a source decode error')
                        database.commit()
                    finally:
                        if probe.poll() is None:
                            probe.kill()
                with self.lock:
                    if cancelled() or self.path(asset)!=destination:
                        raise ValueError('Index cancelled or source identity changed')
                    os.replace(temporary,destination)
            result = {'status':'ready',**summary}
        except (OSError,ValueError,OverflowError,sqlite3.Error,ET.ParseError) as error:
            result = {'status':'cancelled'} if cancelled() else {'status':'error','error':str(error)}
        finally:
            try:
                if temporary:
                    temporary.unlink(missing_ok=True)
            finally:
                with self.lock:
                    self.last = (destination,result)
                    self.active = None
