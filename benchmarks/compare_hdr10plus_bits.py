"""Audit original video samples against an existing decoded metadata cache."""
import argparse
from collections import Counter
from contextlib import closing
from fractions import Fraction
import json
from pathlib import Path
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from hdr10plus_bitstream import UnsupportedMetadata, conformance_issues, length_size, packet_records, probe_streams, sample_metadata
from hdr10plus_index import HDR10PlusIndex


def indexed_integers(data):
    values = {}
    for key,value in data:
        values.setdefault(key,[]).append(Fraction(value))

    def scaled(key,multiplier=1):
        result = tuple(x*multiplier for x in values.get(key,[]))
        if any(v.denominator!=1 for v in result):
            raise ValueError('Decoded field is not exactly on the encoded grid')
        return tuple(map(int,result))

    knee = scaled('knee_point_x',4095)+scaled('knee_point_y',4095)
    return {
        'version':scaled('application version')[0],
        'peak':scaled('targeted_system_display_maximum_luminance')[0],
        'maxrgb':scaled('maxscl',100000),
        'average':scaled('average_maxrgb',100000)[0],
        'distribution':tuple(zip(scaled('distribution_maxrgb_percentage'),scaled('distribution_maxrgb_percentile',100000),strict=True)),
        'bright':scaled('fraction_bright_pixels',1000)[0],
        'knee':knee or None,
        'anchors':scaled('bezier_curve_anchors',1023),
    }


def compare(source,cache,diagnostics):
    started = time.perf_counter()
    format_info = probe_streams(source)
    video = next(s for s in format_info['streams'] if s['codec_type']=='video')
    width = length_size(video)
    counts, reasons, field_differences = Counter(), Counter(), Counter()
    visited = set()
    with closing(sqlite3.connect(cache.as_uri()+'?mode=ro',uri=True)) as db, source.open('rb') as handle, \
            packet_records(source,'v:0') as packets, diagnostics.open('x',encoding='utf8') as raw:
        summary = json.loads(db.execute('SELECT data FROM summary').fetchone()[0])
        assert Fraction(video['time_base'])==Fraction(summary['timeBase'])
        for record in packets:
            pts = int(record[b'pts'])
            if pts in visited:
                raise ValueError('Duplicate encoded video presentation timestamp')
            visited.add(pts)
            row = db.execute('SELECT metadata,rejected FROM frames WHERE pts=?',(pts,)).fetchone()
            if row is None:
                counts['implementation_limited']+=1
                reasons['packet_without_indexed_frame']+=1
                continue
            try:
                block = sample_metadata(handle,int(record[b'pos']),int(record[b'size']),width)
            except UnsupportedMetadata as error:
                counts['unsupported']+=1
                reasons[str(error)]+=1
                continue
            except ValueError as error:
                counts['invalid']+=1
                reasons[str(error)]+=1
                continue
            indexed = indexed_integers(json.loads(row[0])) if row[0] else None
            different = [key for key in block if block[key]!=indexed[key]] if block and indexed else []
            if different or bool(block)!=bool(indexed):
                counts['implementation_limited']+=1
                field_differences.update(different or ['missing_payload'])
            elif block is None:
                counts['untagged']+=1
            else:
                counts['exact_bitstream_matches']+=1
                issues = conformance_issues(block)
                counts['invalid' if issues else 'valid']+=1
                if not issues and row[1]:
                    counts['valid_fenced_by_index']+=1
                reasons.update(issues)
                raw.write(json.dumps({'pts':pts,'raw':block,'reason':issues,'indexed_equal':True})+'\n')
        if len(visited)!=summary['frames']:
            raise ValueError('Encoded sample count differs from decoded index')
    return {'frames':len(visited),'seconds':time.perf_counter()-started,
            **{key:counts[key] for key in ('valid','invalid','unsupported','implementation_limited',
                                           'untagged','exact_bitstream_matches','valid_fenced_by_index')},
            'reasons':dict(reasons),'field_differences':dict(field_differences)}


def main(manifest,cache_dir,results):
    results.mkdir(parents=True,exist_ok=False)
    index = HDR10PlusIndex(cache_dir)
    rows=[]
    for asset in json.loads(manifest.read_text('utf8')):
        cache = index.path(asset)
        if cache.is_file():
            alias = 'Camera '+str(len(rows)+1)
            row = compare(Path(asset['path']),cache,results/(alias+'-private.jsonl'))
            rows.append({'source':alias,**row})
    if not rows:
        raise ValueError('No matching verified decoded index for the local sources')
    (results/'sanitized.json').write_text(json.dumps(rows,indent=2)+'\n',encoding='utf8')
    print(json.dumps(rows))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('manifest',type=Path)
    parser.add_argument('cache',type=Path)
    parser.add_argument('results',type=Path)
    args=parser.parse_args()
    main(args.manifest,args.cache,args.results)
