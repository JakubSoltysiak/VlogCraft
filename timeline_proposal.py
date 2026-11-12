"""Pure validation of offline, track-addressed edit proposals."""
from copy import deepcopy

SCHEMA='vlogcraft.timeline/1'
PROPERTIES={'start','end','position','speed','opacity','volume','scale','x','y','fadeIn','fadeOut','grade','fit','keys'}


def apply(proposal,state,validate):
    if proposal.get('schema')!=SCHEMA:raise ValueError('Unknown proposal schema')
    actions=proposal.get('actions')
    if not isinstance(actions,list) or len(actions)>80:raise ValueError('Provide up to 80 actions')
    result=deepcopy(state)
    tracks={t['id']:t for t in result['tracks']}
    changes=[]
    for a in actions:
        if not isinstance(a,dict):raise ValueError('Invalid action')
        track=tracks.get(a.get('trackId'))
        if not track or track['locked']:raise ValueError('Track missing or locked')
        props=a.get('set')
        if not isinstance(props,dict) or not props:raise ValueError('Specify edited properties')
        if a.get('type')=='edit_clip':
            if set(a)!={'type','trackId','clipId','set'} or set(props)-PROPERTIES:
                raise ValueError('Unsupported clip edit')
            obj=next((c for c in track['clips'] if c['id']==a['clipId']),None)
            if not obj or obj['locked']:raise ValueError('Clip missing or locked')
        elif a.get('type')=='edit_track':
            if set(a)!={'type','trackId','set'} or set(props)-{'volume','muted','hidden'}:
                raise ValueError('Unsupported track edit')
            obj=track
        else:raise ValueError('Unsupported proposal action')
        for name,value in props.items():
            if name in ('muted','hidden'):
                if type(value) is not bool:raise ValueError('Track switches require a boolean')
            elif name not in ('grade','fit','keys') and type(value) not in (int,float):
                raise ValueError('Expected a numeric value')
            old=obj.get(name)
            obj[name]=deepcopy(value)
            changes.append(f'{track["name"]} / {obj["id"][:8]} · {name}: {old} → {value}')
    return validate(result,state),changes
