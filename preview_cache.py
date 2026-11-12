"""Bounded, cancellable program-preview ranges using the export compositor."""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading

import render_engine
import timing


class PreviewCache:
    def __init__(self,folder):
        self.folder=Path(folder)
        self.guard=threading.RLock()
        self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='program-preview')
        self.jobs=OrderedDict()
        self.revision=None
        self.closed=False

    def prepare(self,state,frame,width=1280,proxy_paths=None):
        rate=timing.rate(state['output']['fps'])
        total=timing.frame_at(render_engine.sequence_duration(state),rate)
        if type(frame) is not int or not 0<=frame<total:raise ValueError('Seek inside the sequence')
        if width not in (640,960,1280,1920):raise ValueError('Choose a supported preview width')
        snapshot=deepcopy(state)
        identity={k:v for k,v in state.items() if k!='updated'}
        files=[]
        for asset in snapshot['assets']:
            path=Path(asset['path'])
            original=path.stat() if path.is_file() else None
            proxy=(proxy_paths or {}).get(asset['id'])
            # HDR sources stay on the original tone-mapped reference path.
            if proxy and not asset.get('hdr'):
                path=Path(proxy)
                asset.update(path=str(path),hdr=False,colorTransfer='bt709')
            stat=path.stat() if path.is_file() else None
            files.append([asset['id'],str(path),stat.st_size if stat else None,
                          stat.st_mtime_ns if stat else None,original.st_mtime_ns if original else None])
        revision=hashlib.sha256(json.dumps(['program-preview/3.4/1',identity,files,width],sort_keys=True).encode()).hexdigest()
        block=round(float(rate)*8)
        first=frame//block*block
        last=min(first+block,total)
        key=hashlib.sha256(f'{revision}/{first}/{last}'.encode()).hexdigest()
        with self.guard:
            if self.closed:raise ValueError('Preview service is closed')
            if revision!=self.revision:
                for job in self.jobs.values():
                    if job['status'] in ('queued','rendering'):self._cancel(job)
                self.revision=revision
            if key in self.jobs:
                job=self.jobs[key]
                if job['status'] not in ('error','cancelled'):
                    self.jobs.move_to_end(key)
                    return self.status(key)
                del self.jobs[key]
            pending=[job for job in self.jobs.values() if job['status'] in ('queued','rendering')]
            if len(pending)>=2:self._cancel(pending[0])
            self._prune()
            self.folder.mkdir(parents=True,exist_ok=True)
            output=snapshot['output']
            scale=min(1,width/output['width'])
            output.update(width=max(2,round(output['width']*scale/2)*2),height=max(2,round(output['height']*scale/2)*2))
            job={'id':key,'status':'queued','percent':0,'firstFrame':first,'lastFrame':last,
                 'start':float(first/rate),'end':float(last/rate),'fps':str(rate),
                 'cancel':threading.Event(),'process':None,'path':self.folder/(key+'.mp4'),'error':None}
            self.jobs[key]=job
            self.pool.submit(self._render,job,snapshot)
            return self.status(key)

    def _cancel(self,job):
        job['cancel'].set()
        if job['process'] and job['process'].poll() is None:job['process'].terminate()
        job['status']='cancelled'

    def _render(self,job,state):
        with self.guard:
            if job['cancel'].is_set():return
            job['status']='rendering'
        try:
            with tempfile.TemporaryDirectory(dir=self.folder,prefix='range-') as directory:
                work=Path(directory);dest=work/'program.mp4'
                command=render_engine.segment_command(state,job['start'],job['end'],dest,work,'preview')
                command=[command[0],'-progress','pipe:1',*command[1:]]
                with tempfile.TemporaryFile() as errors:
                    with self.guard:
                        if job['cancel'].is_set():return
                        process=subprocess.Popen(command,cwd=work,stdout=subprocess.PIPE,stderr=errors,
                                                 creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                        job['process']=process
                    try:
                        for line in process.stdout:
                            if line.startswith(b'out_time_us='):
                                try:seconds=int(line.split(b'=')[1])/1e6
                                except ValueError:continue
                                with self.guard:job['percent']=min(99,round(100*seconds/(job['end']-job['start'])))
                        result=process.wait()
                        if job['cancel'].is_set():return
                        if result:
                            errors.seek(0,2);errors.seek(max(0,errors.tell()-1600))
                            raise RuntimeError(errors.read().decode(errors='replace'))
                    finally:
                        if process.poll() is None:
                            process.kill();process.wait()
                        process.stdout.close()
                        with self.guard:job['process']=None
                with self.guard:
                    if job['cancel'].is_set():return
                    os.replace(dest,job['path']);job.update(status='ready',percent=100)
                    self._prune()
        except Exception as error:
            with self.guard:
                if not job['cancel'].is_set():job.update(status='error',error=str(error))

    def _prune(self):
        # Account for complete cache files left by earlier application sessions.
        managed={job['path'] for job in self.jobs.values()}
        orphaned=[p for p in self.folder.glob('*.mp4') if p not in managed and len(p.stem)==64 and all(c in '0123456789abcdef' for c in p.stem)]
        disk_files=[p for p in self.folder.glob('*.mp4') if len(p.stem)==64 and all(c in '0123456789abcdef' for c in p.stem)]
        total_bytes=sum(p.stat().st_size for p in disk_files)
        for path in sorted(orphaned,key=lambda p:p.stat().st_mtime):
            if len(disk_files)<=12 and total_bytes<=512*1024**2:break
            try:
                size=path.stat().st_size;path.unlink()
            except PermissionError:continue
            disk_files.remove(path);total_bytes-=size
        finished=[j for j in self.jobs.values() if j['status'] not in ('queued','rendering')]
        bytes_total=sum(j['path'].stat().st_size for j in finished if j['path'].is_file())
        for job in finished:
            if len(self.jobs)<=12 and bytes_total<=512*1024**2:break
            try:
                size=job['path'].stat().st_size if job['path'].is_file() else 0
                job['path'].unlink(missing_ok=True)
            except PermissionError:continue
            bytes_total-=size
            del self.jobs[job['id']]

    def status(self,key):
        with self.guard:
            job=self.jobs.get(key)
            if not job:raise ValueError('Preview range expired')
            return {k:v for k,v in job.items() if k not in ('cancel','process','path')}|{'url':'/preview/'+key+'.mp4'}

    def path(self,key):
        with self.guard:
            job=self.jobs.get(key)
            if not job or job['status']!='ready':raise ValueError('Preview range is not ready')
            self.jobs.move_to_end(key)
            return job['path']

    def cancel(self):
        with self.guard:
            for job in self.jobs.values():
                if job['status'] in ('queued','rendering'):self._cancel(job)

    def close(self):
        with self.guard:
            self.closed=True
            for job in self.jobs.values():
                if job['status'] in ('queued','rendering'):self._cancel(job)
        self.pool.shutdown(wait=True,cancel_futures=True)
