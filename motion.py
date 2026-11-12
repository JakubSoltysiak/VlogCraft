"""Analyze original footage at reduced resolution; return source-time translations."""
import math
import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np


def sample_frames(asset, clip, fps, cancelled):
    width=384
    height=max(16,round(width*asset['height']/asset['width']))
    cmd=['ffmpeg','-nostdin','-v','error','-ss',str(clip['start']),'-i',asset['path'],
         '-t',str(clip['end']-clip['start']),'-an','-vf',f'fps={fps},scale={width}:{height},format=gray',
         '-f','rawvideo','-pix_fmt','gray','pipe:1']
    with tempfile.TemporaryFile() as errors:
        with subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=errors,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)) as proc:
            try:
                while not cancelled():
                    data=proc.stdout.read(width*height)
                    if not data:break
                    if len(data)!=width*height:raise ValueError('Incomplete analysis frame')
                    yield np.frombuffer(data,dtype=np.uint8).reshape(height,width)
                if cancelled():raise ValueError('Analysis cancelled')
                if proc.wait():
                    errors.seek(0)
                    raise ValueError(errors.read()[-500:].decode(errors='replace'))
            finally:
                if proc.poll() is None:proc.kill()


def translations(frames, point, on_frame=lambda n:None, rotation=False):
    """Track one selected feature or estimate global translation with median optical flow."""
    previous=None
    points=None
    trajectory=[]
    pos=np.zeros(2,dtype=float)
    transform=np.eye(3);last_angle=0.0
    for index,frame in enumerate(frames):
        h,w=frame.shape
        if previous is None and point is not None:
            x,y=np.array(point)*[w-1,h-1]
            mask=np.zeros_like(frame)
            cv2.circle(mask,(int(x),int(y)),16,255,-1)
            points=cv2.goodFeaturesToTrack(frame,16,.008,3,mask=mask)
            if points is None:raise ValueError('Pick a textured corner or a high-contrast detail.')
        elif previous is not None:
            if point is None:
                points=cv2.goodFeaturesToTrack(previous,150,.01,6)
            if points is None:raise ValueError(f'Insufficient detail in analysis frame {index}')
            next_points,status,_=cv2.calcOpticalFlowPyrLK(previous,frame,points,None)
            if next_points is None:raise ValueError(f'Tracking lost at frame {index}')
            reverse,back_status,_=cv2.calcOpticalFlowPyrLK(frame,previous,next_points,None)
            if reverse is None or back_status is None:raise ValueError(f'Tracking lost at frame {index}')
            good=(status.ravel()>0)&(back_status.ravel()>0)&(np.linalg.norm(reverse-points,axis=2).ravel()<1.5)
            if good.sum()<(1 if point is not None else 4):
                raise ValueError(f'Tracking lost at frame {index}. Shorten the shot or select another detail.')
            delta=np.median((next_points[good]-points[good]).reshape(-1,2),axis=0)
            if rotation:
                before=points[good].reshape(-1,2);after=next_points[good].reshape(-1,2)
                affine,inliers=cv2.estimateAffinePartial2D(before,after,method=cv2.RANSAC,ransacReprojThreshold=1.5)
                if affine is None or inliers is None or int(inliers.sum())<4:
                    raise ValueError(f'Insufficient consistent camera motion at frame {index}')
                transform=np.vstack((affine,[0,0,1]))@transform
                center=np.array([(w-1)/2,(h-1)/2,1])
                pos=((transform@center)-center)[:2]/[w,h]
                angle=math.atan2(transform[1,0],transform[0,0])
                last_angle+=math.atan2(math.sin(angle-last_angle),math.cos(angle-last_angle))
            else:pos+=delta/[w,h]
            points=next_points[good]
        trajectory.append(np.r_[pos,math.degrees(last_angle)] if rotation else pos.copy())
        previous=frame
        on_frame(index+1)
    if len(trajectory)<2:raise ValueError('At least two analysis frames are required')
    return np.asarray(trajectory)


def smooth_correction(path, strength, radius):
    padded=np.pad(path,((radius,radius),(0,0)),mode='edge')
    smooth=np.stack([np.convolve(padded[:,i],np.ones(2*radius+1)/(2*radius+1),mode='valid') for i in range(path.shape[1])],axis=1)
    return (smooth-path)*strength


def analyze(asset,clip,settings,cancelled,on_progress):
    fps=min(30,max(1,round(asset.get('fps') or 30)))
    mode=settings.get('mode')
    point=settings.get('point') if mode=='track' else None
    if mode not in ('track','stabilize','stabilizeRotation'):raise ValueError('Unknown analysis mode')
    if mode=='track' and (not isinstance(point,list) or len(point)!=2 or
                          not all(isinstance(v,(float,int)) and 0<=v<=1 for v in point)):
        raise ValueError('Select a point inside the source frame')
    strength=float(settings.get('strength',.8))
    if not math.isfinite(strength) or not 0<=strength<=1:raise ValueError('Strength must be 0–1')
    count=max(1,(clip['end']-clip['start'])*fps)
    frames=sample_frames(asset,clip,fps,cancelled)
    try:
        path=translations(frames,point,lambda n:on_progress(min(99,int(100*n/count))),rotation=mode=='stabilizeRotation')
    finally:
        frames.close()
    if mode in ('stabilize','stabilizeRotation'):
        path=smooth_correction(path,strength,max(2,fps//3))
    # Simplify only when the interpolated path stays within ~0.25 analysis pixels.
    curve=np.column_stack((np.arange(len(path)),path*(np.array([384,384,math.pi*192/180]) if path.shape[1]==3 else 384))).astype('float32')
    keep={0,len(path)-1}
    stack=[(0,len(path)-1)]
    while stack:
        a,b=stack.pop()
        if b-a<2:continue
        u=np.arange(1,b-a)[:,None]/(b-a)
        errors=np.linalg.norm(curve[a+1:b,1:]-(curve[a,1:]+(curve[b,1:]-curve[a,1:])*u),axis=1)
        j=int(errors.argmax())
        if errors[j]>.25:
            k=a+j+1;keep.add(k);stack.extend(((a,k),(k,b)))
    return {'samples':len(path),'fps':fps,'points':[[clip['start']+i/fps,*map(float,path[i])] for i in sorted(keep)]}
