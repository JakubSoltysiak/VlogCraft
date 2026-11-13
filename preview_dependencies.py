"""Project a preview range onto its render dependencies, excluding unrelated edits."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import render_engine
import sequences
import timing

FORMAT='program-preview/3.4.5/1'


def file_identity(path):
    path=Path(path)
    try:
        stat=path.stat()
        return [str(path.resolve()),stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns,stat.st_ino]
    except FileNotFoundError:
        return [str(path.resolve()),None]


def project(state,first,last,width,proxy_paths=None):
    fps=timing.rate(state['output']['fps'])
    flat=sequences.playback(state)
    video,audio=render_engine.active_clips(flat,float(first/fps),float(last/fps))
    wanted={clip['id'] for _,clip in video+audio}
    tracks=[]
    for track in flat['tracks']:
        # Retain empty solo tracks: global solo semantics still affect this range.
        item={k:deepcopy(track[k]) for k in ('type','hidden','muted','solo','volume') if k in track}
        item['clips']=[deepcopy(c) for c in track['clips'] if c['id'] in wanted]
        tracks.append(item)
    used={c['assetId'] for t in tracks for c in t['clips'] if c.get('assetId')}
    luts={c['lutId'] for t in tracks for c in t['clips'] if c.get('lutId')}
    assets=[];files=[]
    for original in state['assets']:
        if original['id'] not in used:continue
        asset=deepcopy(original);path=Path(asset['path']);identity=file_identity(path)
        proxy=(proxy_paths or {}).get(asset['id'])
        if proxy and not asset.get('hdr'):
            candidate=Path(proxy)
            # An older derivative cannot represent a subsequently changed original.
            if candidate.is_file() and (not path.is_file() or candidate.stat().st_mtime_ns>=path.stat().st_mtime_ns):
                path=candidate;asset.update(path=str(path),hdr=False,colorTransfer='bt709')
        files.append([asset['id'],identity,file_identity(path)])
        assets.append(asset)
    output=state['output'];scale=min(1,width/output['width'])
    snapshot={'output':{'width':max(2,round(output['width']*scale/2)*2),
                        'height':max(2,round(output['height']*scale/2)*2),'fps':str(fps)},
              'tracks':tracks,'assets':assets,
              'luts':{key:deepcopy(state.get('luts',{}).get(key)) for key in sorted(luts)}}
    payload=[FORMAT,first,last,snapshot,files]
    key=hashlib.sha256(json.dumps(payload,sort_keys=True,allow_nan=False).encode()).hexdigest()
    return key,snapshot
