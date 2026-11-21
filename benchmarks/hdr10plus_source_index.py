"""Qualify frame-index caching and cancellation with approved local PQ originals."""
import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from hdr10plus_index import HDR10PlusIndex
from server import probe


def wait(index,asset,limit=210):
    deadline = time.monotonic()+limit
    while time.monotonic()<deadline:
        status=index.status(asset)
        if status['status']!='indexing':
            return status
        time.sleep(.1)
    raise TimeoutError('HDR10+ scan did not finish')


def main(manifest,results):
    results = results.resolve()
    results.mkdir(parents=True,exist_ok=True)
    sources = json.loads(manifest.read_text('utf8'))
    index = HDR10PlusIndex(results/'indexes')
    rows = []
    eligible = None
    try:
        for row in sources:
            asset = {'path':row['path'],**probe(row['path'])}
            if asset['codec']!='hevc' or asset['colorTransfer']!='smpte2084':
                continue
            eligible = asset
            started = time.perf_counter()
            assert index.start(asset)['status']=='indexing'
            state = wait(index,asset)
            assert state['status']=='ready',state
            assert state['dynamicFrames']>0 and state['rejectedFrames']==0,state
            cached = index.path(asset)
            stamp = cached.stat().st_mtime_ns
            assert index.start(asset)==state and cached.stat().st_mtime_ns==stamp
            with closing(sqlite3.connect(cached.as_uri()+'?mode=ro',uri=True)) as db:
                samples = db.execute('SELECT count(*), count(metadata) FROM frames').fetchone()
                assert samples==(state['frames'],state['dynamicFrames'])
                intervals = db.execute('SELECT count(DISTINCT delta) FROM '
                                       '(SELECT pts-lag(pts) OVER (ORDER BY pts) AS delta FROM frames)').fetchone()[0]
            rows.append({'source':'Camera '+str(len(rows)+1),'seconds':time.perf_counter()-started,
                         'distinct_frame_intervals':intervals,'cached_reused':True,'index_bytes':cached.stat().st_size,**state})
        assert rows
    finally:
        index.close()
    cancellation = HDR10PlusIndex(results/'cancellation')
    try:
        assert cancellation.start(eligible)['status']=='indexing'
        time.sleep(.25)
        cancellation.cancel(eligible)
        assert wait(cancellation,eligible,10)['status']=='cancelled'
        assert not cancellation.path(eligible).exists()
        assert not list(cancellation.folder.glob('*.part'))
    finally:
        cancellation.close()
    report={'sources':rows,'cancelled_without_cache_publication':True,'scope':'Decoded source metadata only; no HDR10+ export.'}
    (results/'summary.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps(report))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('manifest',type=Path)
    parser.add_argument('results',type=Path)
    args=parser.parse_args()
    main(args.manifest,args.results)
