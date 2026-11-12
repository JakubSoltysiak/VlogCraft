"""Pure validation of offline, track-addressed edit proposals."""
from copy import deepcopy

SCHEMA='vlogcraft.timeline/1'
PROPERTIES={'start','end','position','speed','opacity','volume','scale','x','y','fadeIn','fadeOut','grade','fit','keys','rotation','brightness','contrast','saturation','pan','bass','treble','compress','mask','maskRadius','feather','chroma','keyColor','keyBlend','similarity'}


def apply(proposal,state,validate):
    if proposal.get('schema')!=SCHEMA:raise ValueError('Unknown proposal schema')
    actions=proposal.get('actions')
    if not isinstance(actions,list) or len(actions)>80:raise ValueError('Provide up to 80 actions')
    result=deepcopy(state)
    changes=[]
    for a in actions:
        if not isinstance(a,dict):raise ValueError('Invalid action')
        scope=result['tracks']
        path=a.get('sequencePath',[])
        if not isinstance(path,list) or any(not isinstance(cid,str) for cid in path):raise ValueError('Invalid sequence path')
        for cid in path:
            pair=next(((t,c) for t in scope for c in t['clips'] if c['id']==cid and c['kind']=='sequence'),None)
            if not pair or pair[0]['locked'] or pair[1].get('locked'):raise ValueError('Missing or locked parent sequence')
            scope=pair[1]['children']
        track=next((t for t in scope if t['id']==a.get('trackId')),None)
        fields=set(a)-{'sequencePath'}
        if not track or track['locked']:raise ValueError('Track missing or locked')
        props=a.get('set')
        if not isinstance(props,dict) or not props:raise ValueError('Specify edited properties')
        if a.get('type')=='edit_clip':
            if fields!={'type','trackId','clipId','set'} or set(props)-PROPERTIES:
                raise ValueError('Unsupported clip edit')
            obj=next((c for c in track['clips'] if c['id']==a['clipId']),None)
            if not obj or obj.get('locked'):raise ValueError('Clip missing or locked')
            if obj['kind']=='sequence':raise ValueError('Address a child clip inside the sequence')
            if obj.get('linkId') and set(props)&{'position','start','end','speed'}:
                raise ValueError('Linked timing edits require a linked timeline command')
        elif a.get('type')=='edit_track':
            if fields!={'type','trackId','set'} or set(props)-{'volume','muted','hidden'}:
                raise ValueError('Unsupported track edit')
            obj=track
        else:raise ValueError('Unsupported proposal action')
        for name,value in props.items():
            if name in ('muted','hidden','chroma'):
                if type(value) is not bool:raise ValueError('Track switches require a boolean')
            elif name not in ('grade','fit','keys','mask','keyColor') and type(value) not in (int,float):
                raise ValueError('Expected a numeric value')
            old=obj.get(name)
            obj[name]=deepcopy(value)
            changes.append(f'{track["name"]} / {obj["id"][:8]} · {name}: {old} → {value}')
    return validate(result,state),changes
