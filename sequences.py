"""Project nested track trees onto a flat playback stack without generating new media."""
def clips(tracks):
    for track in tracks:
        for clip in track['clips']:
            yield clip
            if clip.get('kind')=='sequence':yield from clips(clip['children'])


def flatten(tracks,offset=0,prefix='',gain=1,muted=False,hidden=False):
    has_solo=any(t.get('solo') for t in tracks)
    out=[]
    for t in tracks:
        track={**t,'id':prefix+t['id'],'volume':gain*t.get('volume',1),
               'hidden':hidden or t.get('hidden',False),'muted':muted or t.get('muted',False) or (has_solo and not t.get('solo')),
               'solo':False}
        def projected(c):return {**c,'id':prefix+c['id'],'position':offset+c['position']}
        if not any(c.get('kind')=='sequence' for c in t['clips']):
            out.append({**track,'clips':[projected(c) for c in t['clips']]});continue
        for c in reversed(sorted(t['clips'],key=lambda x:x['position'])):
            cid=prefix+c['id']
            if c['kind']=='sequence':
                out.extend(flatten(c['children'],offset+c['position'],cid+'/',track['volume'],track['muted'],track['hidden']))
            else:out.append({**track,'id':track['id']+'/'+cid,'clips':[projected(c)]})
    return out


def playback(state):
    if not any(c.get('kind')=='sequence' for t in state['tracks'] for c in t['clips']):return state
    return {**state,'tracks':flatten(state['tracks'])}
