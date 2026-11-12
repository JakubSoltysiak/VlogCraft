"""Rational project clocks. Frame intervals are half-open; boundaries round half up."""
from copy import deepcopy
import sequences
from fractions import Fraction

RATES=(Fraction(24000,1001),Fraction(24),Fraction(25),Fraction(30000,1001),Fraction(30),
       Fraction(50),Fraction(60000,1001),Fraction(60))
ALIASES={'23.976':RATES[0],'29.97':RATES[3],'59.94':RATES[6]}
FALLBACK_TICK=Fraction(1,1_000_000_000)


def rational(value):
    return value if isinstance(value,Fraction) else Fraction(str(value))


def rate(value):
    parsed=ALIASES.get(str(value))
    if parsed is None:parsed=rational(value)
    if parsed not in RATES:raise ValueError('Unsupported sequence frame rate')
    return parsed


def persisted_rate(value):
    r=rate(value)
    return r.numerator if r.denominator==1 else str(r)


def nearest(value):
    value=rational(value)+Fraction(1,2)
    return value.numerator//value.denominator


def frame_at(seconds,fps):
    return nearest(rational(seconds)*fps)


def sample_at(frame,fps):
    return nearest(Fraction(frame*48000,1)/fps)


def base_for(asset):
    return rational((asset or {}).get('timeBase') or FALLBACK_TICK)


def encode(state):
    """3.2 writes authoritative frame/tick coordinates alongside readable seconds."""
    doc=deepcopy(state)
    doc['version']=4
    fps=rate(doc['output']['fps'])
    assets={a['id']:a for a in doc['assets']}
    for clip in sequences.clips(doc['tracks']):
        base=base_for(assets.get(clip.get('assetId')))
        clip['timing']={'positionFrame':frame_at(clip['position'],fps),'sourceTimeBase':str(base),
                        'inTick':nearest(rational(clip['start'])/base),'outTick':nearest(rational(clip['end'])/base)}
    return doc


def decode(document):
    doc=deepcopy(document)
    fps=rate(doc['output']['fps'])
    for clip in sequences.clips(doc['tracks']):
        stamp=clip.pop('timing')
        base=rational(stamp['sourceTimeBase'])
        if base<=0 or any(type(stamp[k]) is not int for k in ('inTick','outTick','positionFrame')):
            raise ValueError('Invalid integer clip timing')
        if stamp['inTick']<0 or stamp['outTick']<=stamp['inTick'] or stamp['positionFrame']<0:
            raise ValueError('Invalid clip timing range')
        clip.update(position=float(stamp['positionFrame']/fps),start=float(stamp['inTick']*base),
                    end=float(stamp['outTick']*base))
    # The editable API carries seconds. Only the on-disk serializer owns v4 ticks.
    doc['version']=3
    return doc
