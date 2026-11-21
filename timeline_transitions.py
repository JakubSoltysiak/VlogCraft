"""Frame-centered transition contracts shared by preview and export."""
from dataclasses import dataclass
from fractions import Fraction

import timing


VIDEO = ('dissolve','dip-black','dip-white')
AUDIO = ('linear','equal-power')


def spec(value, track_type):
    if not isinstance(value,dict) or set(value)-{'from','frames','kind','ease','audio'}:
        raise ValueError('Invalid boundary transition')
    kind=value.get('kind')
    if kind not in (VIDEO if track_type=='video' else AUDIO):
        raise ValueError('Unsupported boundary transition')
    if not isinstance(value.get('from'),str) or not value['from'] or len(value['from'])>1024:
        raise ValueError('A transition needs an outgoing clip')
    if type(value.get('frames')) is not int or not 2<=value['frames']<=360:
        raise ValueError('Transition duration must be between 2 and 360 frames')
    ease=value.get('ease','linear')
    if ease not in ('linear','smooth') or (track_type=='audio' and ease!='linear'):
        raise ValueError('Unsupported transition easing')
    audio=value.get('audio','none')
    if audio not in ('none',*AUDIO) or (track_type=='audio' and audio!='none'):
        raise ValueError('Unsupported linked audio crossfade')
    return {'from':value['from'],'frames':value['frames'],'kind':kind,'ease':ease,
            **({'audio':audio} if audio!='none' else {})}


def clip_frames(clip,fps):
    first=timing.frame_at(clip['position'],fps)
    position=timing.rational(clip['position'])
    duration=(timing.rational(clip['end'])-timing.rational(clip['start']))/timing.rational(clip.get('speed',1))
    return first,timing.frame_at(position+duration,fps)


@dataclass(frozen=True)
class Boundary:
    track: dict
    left: dict
    right: dict
    start: int
    cut: int
    end: int
    kind: str
    ease: str

    def virtual(self,fps):
        after=(self.end-self.cut)/fps
        before=(self.cut-self.start)/fps
        left={**self.left,'end':self.left['end']+float(after)*self.left.get('speed',1)}
        right={**self.right,'position':float(self.start/fps),
               'start':self.right['start']-float(before)*self.right.get('speed',1)}
        # Clamp only a representation-level epsilon at a valid exact zero.
        if abs(right['start'])<1e-10:right['start']=0
        return left,right


def create_boundary(track,left,right,settings,assets,fps,audio=False):
    begin,cut=clip_frames(left,fps)
    next_start,finish=clip_frames(right,fps)
    name=track.get('name','track')
    if cut!=next_start:
        raise ValueError(f'{name}: transition requires clips that meet at the cut')
    pre=settings['frames']//2
    post=settings['frames']-pre
    if cut-pre<begin or cut+post>finish:
        raise ValueError(f'{name}: transition is longer than the neighboring clips')
    for clip,ticks,key in ((left,post,'end'),(right,pre,'start')):
        if clip.get('kind') in ('image','title') and not audio:
            continue
        item=assets.get(clip.get('assetId'),{})
        if audio and (not item.get('hasAudio') or clip.get('audioDetached')):
            raise ValueError(f'{name}: both clips need active source audio')
        limit=(item.get('duration') if audio else item.get('videoEnd') or item.get('duration')) or 0
        handle=ticks/fps*timing.rational(clip.get('speed',1))
        available=(timing.rational(limit)-timing.rational(clip['end']) if key=='end'
                   else timing.rational(clip['start']))
        if available+Fraction(1,10**9)<handle:
            direction='outgoing' if key=='end' else 'incoming'
            raise ValueError(f'{name}: {direction} clip has insufficient source handles; shorten the transition or trim more source')
    return Boundary(track,left,right,cut-pre,cut,cut+post,settings['kind'],settings.get('ease','linear'))


def plan(state):
    """Resolve saved pairs. A stale boundary is an actionable error."""
    video,audio=[],[]
    fps=timing.rate(state['output']['fps'])
    assets={a['id']:a for a in state['assets']}
    linked={}
    for track in state['tracks']:
        if track['type']=='audio':
            for clip in track['clips']:
                if clip.get('linkId'):linked[clip['linkId']]=(track,clip)
    for track in state['tracks']:
        if track.get('hidden'):continue
        kind=track['type']
        clips=sorted(track['clips'],key=lambda c:c['position'])
        previous_end=-1
        for index,right in enumerate(clips):
            raw=right.get('transitionIn')
            if not raw:continue
            settings=spec(raw,kind)
            if not index or clips[index-1]['id']!=settings['from']:
                raise ValueError(f'{track.get("name","Track")}: a transition lost its outgoing clip; edit or remove it')
            left=clips[index-1]
            pair=create_boundary(track,left,right,settings,assets,fps,audio=kind=='audio')
            if pair.start<previous_end:
                raise ValueError('Two transitions overlap; shorten one of them')
            for other in clips:
                if other is left or other is right:continue
                first,last=clip_frames(other,fps)
                if last>pair.start and first<pair.end:
                    raise ValueError('A third clip overlaps this transition on the same track')
            previous_end=pair.end
            if kind=='audio':
                audio.append(pair)
            else:
                video.append(pair)
                shape=settings.get('audio','none')
                if shape!='none':
                    t,l,r=track,left,right
                    if left.get('audioDetached') or right.get('audioDetached'):
                        pl,pr=linked.get(left.get('linkId')),linked.get(right.get('linkId'))
                        if not pl or not pr or pl[0] is not pr[0]:
                            raise ValueError('Link both camera audio clips on the same track to crossfade with video')
                        t,l,r=pl[0],pl[1],pr[1]
                    linked_pair=create_boundary(t,l,r,{**settings,'kind':shape},assets,fps,audio=True)
                    if (linked_pair.start,linked_pair.end)!=(pair.start,pair.end):
                        raise ValueError('Linked camera audio must align with the video transition')
                    audio.append(linked_pair)
    for index,pair in enumerate(audio):
        if any(pair.track is other.track and pair.start<other.end and other.start<pair.end
               for other in audio[:index]):
            raise ValueError('Audio crossfades overlap on the same track')
    return video,audio


def present(state):
    return any(c.get('transitionIn') for t in state['tracks'] for c in t['clips'])


def intervals(state,first,last):
    """Split visual sampling before/after each transition range."""
    if not present(state):return []
    pictures,_=plan(state)
    return sorted({tick for pair in pictures for tick in (pair.start,pair.end) if first<tick<last})


def audio_state(state,fps):
    """Extend audio only. Two sides of a shared clip keep independent envelopes."""
    if not present(state):
        return state
    _,pairs=plan(state)
    if not pairs:
        return state
    overrides={}
    for pair in pairs:
        left,right=pair.virtual(fps)
        first,last=(timing.sample_at(tick,fps) for tick in (pair.start,pair.end))
        for tag,clip in (('out',left),('in',right)):
            entry=overrides.setdefault((pair.track.get('id'),clip['id']),{'_crossfades':[]})
            if tag=='out':
                entry['end']=clip['end']
            else:
                entry.update(position=clip['position'],start=clip['start'])
            entry['_crossfades'].append((tag,first,last-first,'qsin' if pair.kind=='equal-power' else 'tri'))
    return {**state,'tracks':[
        {**track,'clips':[{**clip,**overrides.get((track.get('id'),clip['id']),{})} for clip in track['clips']]}
        for track in state['tracks']]}
