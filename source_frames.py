"""Disk-backed presentation timestamp index for the original video stream."""
import base64
import hashlib
import mmap
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import threading

import timing

TICK=struct.Struct('<q')
CREATE_FLAGS=getattr(subprocess,'CREATE_NO_WINDOW',0)


class FrameIndex:
    def __init__(self,folder):
        self.folder=folder
        self.guard=threading.Lock()
        self.running={}

    def path(self,asset):
        path=Path(asset['path'])
        stat=path.stat()
        identity=f"{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}"
        return self.folder/(hashlib.sha256(identity.encode()).hexdigest()+'.pts')

    def cancel(self,aid):
        with self.guard:
            task=self.running.get(aid)
            if task:
                task['cancel'].set()
                p=task['process']
                if p and p.poll() is None:p.terminate()

    def status(self,aid):
        with self.guard:
            task=self.running.get(aid)
            return {'indexing':bool(task),'frames':task['count'] if task else 0}

    def build(self,asset,dest):
        aid=asset['id']
        with self.guard:
            if dest.is_file():return
            if aid in self.running:raise ValueError('The frame index is already being generated')
            task={'process':None,'cancel':threading.Event(),'count':0}
            self.running[aid]=task
        temp=None
        try:
            self.folder.mkdir(exist_ok=True,parents=True)
            with tempfile.NamedTemporaryFile(dir=self.folder,delete=False) as file:
                temp=Path(file.name)
                cmd=['ffprobe','-v','error','-select_streams','v:0','-show_frames',
                     '-show_entries','frame=best_effort_timestamp','-of','compact=p=0:nk=0',asset['path']]
                with subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,creationflags=CREATE_FLAGS) as p:
                    try:
                        with self.guard:
                            task['process']=p
                            if task['cancel'].is_set():p.terminate()
                        last=None
                        for line in p.stdout:
                            for field in line.split(b'|'):
                                if not field.startswith(b'best_effort_timestamp='):continue
                                try:pts=int(field.split(b'=',1)[1])
                                except ValueError:continue
                                if last is not None and pts<last:raise ValueError('Non-monotonic presentation timestamps')
                                if pts!=last:
                                    file.write(TICK.pack(pts));last=pts;task['count']+=1
                        if task['cancel'].is_set():raise ValueError('Frame indexing cancelled')
                        if p.wait() or not task['count']:raise ValueError('The video has no usable presentation timestamps')
                    finally:
                        if p.poll() is None:p.kill()
            if self.path(asset)!=dest:raise ValueError('The original changed while indexing')
            os.replace(temp,dest)
        finally:
            if temp:temp.unlink(missing_ok=True)
            with self.guard:self.running.pop(aid,None)

    def locate(self,asset,seconds,step):
        dest=self.path(asset)
        self.build(asset,dest)
        base=timing.base_for(asset)
        origin=timing.rational(asset.get('formatStart') or 0)
        pts=(timing.rational(seconds)+origin)/base
        # A double representing an exact PTS can be a fraction of a tick below it.
        near=timing.nearest(pts)
        if abs(near-pts)<timing.Fraction(1,1000000):pts=near
        with dest.open('rb') as file,mmap.mmap(file.fileno(),0,access=mmap.ACCESS_READ) as data:
            count=len(data)//TICK.size
            def tick(i):return TICK.unpack_from(data,i*TICK.size)[0]
            lo,hi=0,count
            while lo<hi:
                mid=(lo+hi)//2
                if tick(mid)<=pts:lo=mid+1
                else:hi=mid
            idx=max(0,min(count-1,max(0,lo-1)+step))
            start=max(0,float(tick(idx)*base-origin))
            finish=float(tick(idx+1)*base-origin) if idx+1<count else asset.get('videoEnd',asset['duration'])
            return {'index':idx,'count':count,'pts':str(tick(idx)),'timeBase':str(base),'start':start,'end':finish}


def preview(asset,frame):
    # The in-point was obtained from the original presentation timestamp table.
    seek=max(0,int(frame['start']*1e6)/1e6)
    cmd=['ffmpeg','-v','error','-nostdin','-ss',f'{seek:.6f}','-i',asset['path'],'-map','0:v:0',
         '-frames:v','1','-vf','scale=640:-2','-c:v','mjpeg','-f','image2pipe','pipe:1']
    r=subprocess.run(cmd,capture_output=True,timeout=60,creationflags=CREATE_FLAGS)
    if r.returncode or not r.stdout:raise ValueError('Unable to decode the requested original frame')
    return 'data:image/jpeg;base64,'+base64.b64encode(r.stdout).decode('ascii')
