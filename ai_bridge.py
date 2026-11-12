"""Explicit, consent-based AI review bridge for the local Kenya video editor.

Local review packs contain only sampled frames and an editable clip manifest.
No network calls are made unless the user clicks 'Analyze with OpenAI API'.
"""
from __future__ import annotations
import base64
import io
import json
import math
import os
import shutil
import subprocess
import time
import uuid
import zipfile
from copy import deepcopy
from pathlib import Path
from urllib import request, error

MAX_REVIEW_SHOTS = 24
MAX_API_SHOTS = 8
ALLOWED_ACTIONS = {'trim', 'split', 'move', 'remove', 'volume', 'fade', 'music_volume', 'grade', 'caption', 'fit'}


def manifest(state):
    """No absolute paths in review data."""
    assets = {a['id']: a for a in state['assets']}
    out = []
    at = 0.
    for i, clip in enumerate(state['timeline']):
        a = assets.get(clip['assetId'])
        if not a:
            continue
        d = round(float(clip['end'])-float(clip['start']), 3)
        out.append({'index':i,'clipId':clip['id'],'assetId':a['id'],'name':a['name'],
                    'kind':a['kind'],'timelineStart':round(at,3), 'timelineEnd':round(at+d,3),
                    'sourceIn':clip['start'],'sourceOut':clip['end'],'duration':d,
                    'sourceDuration':a['duration'],'sourceWidth':a['width'],'sourceHeight':a['height'],
                    'codec':a.get('codec'), 'volume':clip.get('volume',1), 'fade':clip.get('fade',True),
                    'caption':clip.get('caption',''), 'grade':clip.get('grade','neutral'), 'fit':clip.get('fit','contain')})
        at += d
    return {'project':state.get('name','Untitled'), 'output':state.get('output'),
            'music':next((a['name'] for a in state['assets'] if a['id']==state.get('musicId')),None),
            'musicVolume':state.get('musicVolume',0.2),'totalDuration':round(at,3), 'clips':out}


def sample_frames(state, max_shots=MAX_REVIEW_SHOTS):
    """Return (filename, bytes) for representative shots, bounded memory."""
    clips = state.get('timeline',[])
    if not clips:
        return []
    assets = {a['id']: a for a in state['assets']}
    step = max(1, math.ceil(len(clips)/max_shots))
    images = []
    for i in range(0,len(clips),step):
        if len(images)>=max_shots:
            break
        c = clips[i]; a = assets.get(c['assetId'])
        if not a or a['kind'] not in ('video','image') or not Path(a['path']).is_file():
            continue
        middle = (float(c['start'])+float(c['end']))/2 if a['kind']=='video' else 0.
        args=['ffmpeg','-v','error','-nostdin','-ss',f'{middle:.3f}','-i',a['path'],
              '-vf','scale=640:360:force_original_aspect_ratio=decrease,pad=640:360:(ow-iw)/2:(oh-ih)/2:black',
              '-frames:v','1','-q:v','7','-f','image2pipe','-vcodec','mjpeg','pipe:1']
        try:
            p = subprocess.run(args, capture_output=True,timeout=30)
            if p.returncode==0 and p.stdout.startswith(b'\xff\xd8'):
                images.append((f'{i:03d}_{c["id"][:8]}.jpg',p.stdout))
        except (OSError,subprocess.TimeoutExpired):
            pass
    return images


PROMPT = """You are my video editing assistant for a private Kenya travel vlog. Analyze the sampled screenshots and the precise timeline manifest. Give useful, specific, actionable edit feedback: pacing, composition, repeated shots, cutting, transitions, color, audio mixing, travel story arc. Do NOT invent unseen motion, sounds or dialogue: still frames cannot reveal those. Prefer classical/orchestral mood (e.g. John Barry's Flying Over Africa). Preserve wildlife authenticity and natural sound. Note I want 16:9 4K when possible. Output suggestions AND an optional edit proposal in JSON with format:\n{\"summary\":\"...\",\"suggestions\":[\"...\"],\"actions\":[{\"type\":\"trim\",\"clipId\":\"EXACT_ID\",\"start\":0.5,\"end\":5.2}]}\nSupported actions: trim (source seconds), split (source time), remove, move (index), volume (value 0..3), fade (enabled bool), music_volume (value 0..1), grade (preset neutral/warm/cool/vivid), fit (mode contain/cover), caption (text max 120 chars). A suggested action only takes effect if the user reviews and applies it. Use EXACT clipIds from manifest, sensible source bounds. If unsure, leave actions empty, just give suggestions. Never automatically delete footage without suggesting why.\n"""


def create_review_zip(state, dest):
    data = manifest(state)
    frames = sample_frames(state)
    dest = Path(dest)
    dest.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(dest,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('timeline.json',json.dumps(data,ensure_ascii=False,indent=2))
        z.writestr('README.txt', 'Private Kenya Vlog review bundle. These are SAMPLE FRAMES, not the full videos.\n'+
                   'Upload this ZIP to ChatGPT and ask for specific editing advice.\n'+
                   'Then paste ChatGPT\'s proposed JSON into the AI Assistant pane to preview/apply changes.\n'+
                   'Your original footage is not included and remains on your PC.\n')
        z.writestr('PROMPT.txt',PROMPT+'\n\nTIMELINE MANIFEST:\n'+json.dumps(data,ensure_ascii=False,indent=2))
        for name,content in frames:
            z.writestr('frames/'+name,content)
    return {'file':str(dest),'frames':len(frames),'clips':len(data['clips']),
            'bytes':dest.stat().st_size}


def _finite(value, name):
    try: v = float(value)
    except (ValueError,TypeError): raise ValueError(f'{name} must be a number')
    if not math.isfinite(v): raise ValueError(f'{name} must be finite')
    return v


def validate_and_apply(proposal, state):
    """Pure, transactional patch; returns a new state and an audit log."""
    if not isinstance(proposal,dict): raise ValueError('Expected JSON object with actions')
    actions=proposal.get('actions')
    if not isinstance(actions,list) or len(actions)>80: raise ValueError('actions must be an array of at most 80 items')
    result=deepcopy(state)
    timeline=result['timeline']
    asset_map={a['id']:a for a in result['assets']}
    audit=[]
    def find(cid):
        if not isinstance(cid,str): raise ValueError('clipId must be a string')
        for idx,clip in enumerate(timeline):
            if clip['id']==cid: return idx,clip
        raise ValueError(f'Unknown clipId: {cid}')
    for n,action in enumerate(actions):
        if not isinstance(action,dict): raise ValueError(f'Action #{n+1} must be an object')
        typ=action.get('type'); cid=action.get('clipId')
        if typ not in ALLOWED_ACTIONS: raise ValueError(f'Unknown action type: {typ}')
        if typ=='music_volume':
            v=_finite(action.get('value'),'music volume')
            if not 0<=v<=1: raise ValueError('music volume must be 0..1')
            result['musicVolume']=v;audit.append(f'Music volume → {round(v*100)}%');continue
        i,c=find(cid)
        source=asset_map[c['assetId']]
        if typ=='trim':
            start=_finite(action.get('start'),'start');end=_finite(action.get('end'),'end')
            limit=source['duration']+.08 if source['kind']=='video' else 3600
            if start<0 or end<=start or end-start<0.15 or end>limit or source['kind']=='image' and start!=0:
                raise ValueError(f'Invalid trim bounds for {source["name"]}')
            c['start']=round(start,3);c['end']=round(end,3)
            audit.append(f'Clip {i+1}: trim {start:.1f}–{end:.1f}s')
        elif typ=='split':
            at=_finite(action.get('at'),'split point')
            if not c['start']+0.15<=at<=c['end']-0.15: raise ValueError('Split outside clip (min 0.15s per half)')
            if source['kind']=='image': raise ValueError('Cannot split still image by source time')
            suffix=deepcopy(c);suffix['id']=uuid.uuid4().hex;suffix['start']=round(at,3);c['end']=round(at,3)
            timeline.insert(i+1,suffix);audit.append(f'Clip {i+1}: split at {at:.2f}s')
        elif typ=='remove':
            timeline.pop(i);audit.append(f'Remove clip {i+1}: {source["name"]}')
        elif typ=='move':
            j=action.get('index')
            if not isinstance(j,int) or isinstance(j,bool) or j<0 or j>=len(timeline):raise ValueError('Move index out of range')
            timeline.insert(j,timeline.pop(i));audit.append(f'Move clip {i+1} to slot {j+1}')
        elif typ=='volume':
            v=_finite(action.get('value'),'volume')
            if not 0<=v<=3: raise ValueError('Volume must be 0..3')
            c['volume']=v;audit.append(f'Clip {i+1}: volume {round(v*100)}%')
        elif typ=='fade':
            if type(action.get('enabled')) is not bool: raise ValueError('fade.enabled must be boolean')
            c['fade']=action['enabled'];audit.append(f'Clip {i+1}: fade {"on" if c["fade"] else "off"}')
        elif typ=='grade':
            val=action.get('preset')
            if val not in {'neutral','warm','cool','vivid'}:raise ValueError('Invalid grade preset')
            c['grade']=val;audit.append(f'Clip {i+1}: grade {val}')
        elif typ=='fit':
            mode=action.get('mode')
            if mode not in ('contain','cover'):raise ValueError('fit mode must be contain or cover')
            c['fit']=mode;audit.append(f'Clip {i+1}: fit {mode}')
        elif typ=='caption':
            val=action.get('text')
            if not isinstance(val,str) or len(val)>120 or any(ord(ch)<32 and ch!='\n' for ch in val):
                raise ValueError('Invalid caption text')
            c['caption']=val;audit.append(f'Clip {i+1}: caption changed')
    return result,audit


def analyze_with_openai(state, api_key, goal=''):
    """Opt-in remote request: samples (max 8 JPEGs) and manifest are sent via HTTPS.
    Key is never persisted. API requests are paid separately by the provider.
    """
    key = api_key or os.environ.get('OPENAI_API_KEY','')
    if not key.startswith('sk-') or len(key)>1024: raise ValueError('Provide an OpenAI Platform API key. API use may incur charges.')
    frames = sample_frames(state,max_shots=MAX_API_SHOTS)
    content=[{'type':'text','text':PROMPT+'\nUser goal: '+goal[:700]+'\nTimeline:\n'+
              json.dumps(manifest(state),ensure_ascii=False)}]
    for name,blob in frames:
        content.append({'type':'text','text':f'Frame {name} (clip index in name):'})
        content.append({'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+base64.b64encode(blob).decode('ascii'),'detail':'low'}})
    model=os.environ.get('VLOGCRAFT_OPENAI_MODEL','gpt-4.1-mini')
    payload=json.dumps({'model':model,'messages':[{'role':'user','content':content}],
                        'response_format':{'type':'json_object'},'max_tokens':2200}).encode('utf-8')
    req=request.Request('https://api.openai.com/v1/chat/completions',data=payload,method='POST',
                        headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
    try:
        with request.urlopen(req,timeout=120) as resp:
            body=resp.read(2_500_000)
    except error.HTTPError as e:
        raise RuntimeError(f'OpenAI API returned HTTP {e.code}. Verify key, model and billing settings.') from e
    except error.URLError as e:
        raise RuntimeError('Could not reach OpenAI API: '+str(e.reason)) from e
    result=json.loads(body)
    answer=result['choices'][0]['message']['content']
    parsed=json.loads(answer)
    if not isinstance(parsed,dict): raise ValueError('AI response was not a JSON object')
    # Never blindly trust AI: validate before even showing the proposal.
    actions=parsed.get('actions',[])
    try:
        _state, audit=validate_and_apply({'actions':actions},state)
        warning=None
    except ValueError as exc:
        warning='Some proposed edits were invalid and have been dropped: '+str(exc)
        actions=[];audit=[]
    suggestions=parsed.get('suggestions',[])
    if not isinstance(suggestions,list): suggestions=[]
    if warning:suggestions=[warning]+suggestions
    return {'summary':str(parsed.get('summary','')),'suggestions':suggestions[:20],
            'actions':actions,'proposedChanges':audit, 'shotsSent':len(frames),
            'model':model}
