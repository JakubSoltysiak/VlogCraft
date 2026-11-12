"""Build a local multitrack review packet from the same picture used for export."""
import json
from copy import deepcopy
from pathlib import Path
import tempfile
import zipfile

from PIL import Image
import render_engine as engine
import timing
import timeline_proposal

PROMPT="""Review the composited program frames and multitrack_manifest.json. Use the project frame rate, source bounds, track order, locked states and audio roles. Return JSON with schema "vlogcraft.timeline/1", summary, suggestions and actions. Use edit_clip with trackId, clipId and set, or edit_track with trackId and set. For clips in a nested sequence supply sequencePath, listing parent sequence clip IDs from the root down. Positions, source in/out points and key times are seconds. Use exact IDs. Do not change locked objects. Return an empty actions list when a change cannot be expressed. The editor previews the exact changes and requires the filmmaker's approval."""


def manifest(state):
    def tracks(items):
        out=[]
        for t in items:
            row={k:t.get(k) for k in ('id','name','type','locked','solo','muted','hidden','volume')}
            row['trackId']=row.pop('id');row['clips']=[]
            for c in t['clips']:
                clip={k:v for k,v in c.items() if k not in ('id','children')}
                clip['clipId']=c['id']
                if c['kind']=='sequence':clip['tracks']=tracks(c['children'])
                row['clips'].append(clip)
            out.append(row)
        return out
    return {'schema':timeline_proposal.SCHEMA,'project':state['name'],'output':dict(state['output']),
            'duration':engine.sequence_duration(state),'tracks':tracks(state['tracks']),
            'assets':[{k:a.get(k) for k in ('id','name','kind','duration','width','height','codec','timeBase',
                                             'averageRate','nominalRate','hasAudio')} for a in state['assets']]}


def create(state,dest,legacy,selected=None):
    state=deepcopy(state);data=manifest(state);rate=timing.rate(state['output']['fps'])
    total=timing.frame_at(engine.sequence_duration(state),rate)
    if total<1:raise ValueError('Add a clip to the timeline before making a review pack')
    if selected is not None:
        if not isinstance(selected,list) or len(selected)>24 or not all(type(i) is int and 0<=i<total for i in selected):
            raise ValueError('Select up to 24 frames inside the sequence')
        indices=sorted(set(selected))
    else:
        n=min(12,total);indices=sorted(set(min(total-1,(2*i+1)*total//(2*n)) for i in range(n)))
    out=state['output'];scale=min(1,640/max(out['width'],out['height']))
    out.update(width=max(2,round(out['width']*scale/2)*2),height=max(2,round(out['height']*scale/2)*2))
    dest=Path(dest);dest.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=dest.parent) as tmp:
        job=Path(tmp);bundle=job/'packet.zip'
        with zipfile.ZipFile(bundle,'w',zipfile.ZIP_DEFLATED) as z:
            z.writestr('timeline.json',json.dumps(legacy,ensure_ascii=False))
            z.writestr('multitrack_manifest.json',json.dumps(data,ensure_ascii=False,indent=2))
            z.writestr('PROMPT.txt',PROMPT)
            z.writestr('README.txt','Read PROMPT.txt and multitrack_manifest.json together with the sampled program frames. timeline.json is the legacy rough-cut view.')
            for i in indices:
                frame=job/'sample.png'
                cmd=engine.segment_command(state,float(i/rate),float((i+1)/rate),frame,job,'frame')
                engine._run(cmd,str(job))
                jpeg=job/'sample.jpg'
                with Image.open(frame) as im:im.convert('RGB').save(jpeg,quality=80)
                z.write(jpeg,f'frames/program_{i:010d}.jpg')
        bundle.replace(dest)
    return {'file':str(dest),'frames':len(indices),'bytes':dest.stat().st_size}
