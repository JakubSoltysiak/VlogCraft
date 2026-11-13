"""Bounded, cancellable preview ranges with dependency-aware persistent caching."""
from collections import OrderedDict
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading

import preview_dependencies
import project_store
import render_engine
import timing


class PreviewCache:
    def __init__(self,folder,*,max_files=12,max_bytes=512*1024**2):
        self.folder=Path(folder)
        self.guard=threading.RLock()
        self.condition=threading.Condition(self.guard)
        self.jobs=OrderedDict()
        self.closed=False
        self.max_files=max_files;self.max_bytes=max_bytes
        self.protected=set()
        self.counters={'hits':0,'misses':0,'diskHits':0,'invalidated':0,'evicted':0}
        self.worker=threading.Thread(target=self._work,name='program-preview',daemon=True)
        self.worker.start()

    @staticmethod
    def _stat(path):
        try:
            s=path.stat()
            return (s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_ino)
        except FileNotFoundError:return None

    @staticmethod
    def _digest(path):
        h=hashlib.sha256()
        with path.open('rb') as file:
            while block:=file.read(1024*1024):h.update(block)
        return h.hexdigest()

    @staticmethod
    def _owned(path):
        return len(path.stem)==64 and all(c in '0123456789abcdef' for c in path.stem)

    def prepare(self,state,frame,width=1280,proxy_paths=None):
        rate=timing.rate(state['output']['fps'])
        total=timing.frame_at(render_engine.sequence_duration(state),rate)
        if type(frame) is not int or not 0<=frame<total:raise ValueError('Seek inside the sequence')
        if width not in (640,960,1280,1920):raise ValueError('Choose a supported preview width')
        block=round(float(rate)*8)
        first=frame//block*block;last=min(first+block,total)
        key,snapshot=preview_dependencies.project(state,first,last,width,proxy_paths)
        with self.guard:
            if self.closed:raise ValueError('Preview service is closed')
            # Never evict a derivative that the user has explicitly linked as source.
            self.protected={os.path.normcase(os.path.abspath(a['path'])) for a in state['assets']}
            for job in list(self.jobs.values()):
                if job['status'] not in ('queued','rendering'):continue
                if job['lastFrame']>total:
                    changed=True
                else:
                    expected,_=preview_dependencies.project(state,job['firstFrame'],job['lastFrame'],job['_width'],proxy_paths)
                    changed=expected!=job['id']
                if changed:
                    self._cancel(job);self.counters['invalidated']+=1
            if key in self.jobs:
                job=self.jobs[key]
                if job['status']=='ready' and self._stat(job['path'])!=job.get('_fingerprint'):
                    job['status']='error';self.counters['invalidated']+=1
                if job['status'] not in ('error','cancelled'):
                    self.jobs.move_to_end(key);self.counters['hits']+=1
                    return self.status(key)|{'cacheHit':True}
                del self.jobs[key]
            self.folder.mkdir(parents=True,exist_ok=True)
            job={'id':key,'status':'queued','percent':0,'firstFrame':first,'lastFrame':last,
                 'start':float(first/rate),'end':float(last/rate),'fps':str(rate),
                 'cancel':threading.Event(),'process':None,'path':self.folder/(key+'.mp4'),
                 'error':None,'_width':width}
            self.jobs[key]=job
            if self._restore(job):
                self.counters['hits']+=1;self.counters['diskHits']+=1;self._prune()
                return self.status(key)|{'cacheHit':True}
            self.counters['misses']+=1
            pending=[j for j in self.jobs.values() if j['status'] in ('queued','rendering') and j is not job]
            if len(pending)>=2:self._cancel(pending[0])
            self._prune()
            job['_snapshot']=snapshot;self.condition.notify()
            return self.status(key)|{'cacheHit':False}

    def _restore(self,job):
        path=job['path'];manifest=path.with_suffix('.json')
        try:
            stat=self._stat(path)
            if not stat or stat[0]>self.max_bytes or manifest.stat().st_size>16384:return False
            data=json.loads(manifest.read_bytes())
            if data['format']!=preview_dependencies.FORMAT or data['id']!=job['id']:return False
            if data['bytes']!=stat[0] or data['sha256']!=self._digest(path):return False
            job.update(status='ready',percent=100,_fingerprint=stat)
            return True
        except (OSError,ValueError,KeyError,TypeError):return False

    def _cancel(self,job):
        job['cancel'].set();job.pop('_snapshot',None)
        process=job['process']
        if process and process.poll() is None:
            try:process.terminate()
            except OSError:pass
        job['status']='cancelled'

    def _work(self):
        while True:
            with self.condition:
                while not self.closed and not any(j['status']=='queued' for j in self.jobs.values()):self.condition.wait()
                if self.closed:return
                job=next(j for j in self.jobs.values() if j['status']=='queued')
                snapshot=job.pop('_snapshot');job['status']='rendering'
            self._render(job,snapshot)

    def _render(self,job,state):
        with self.guard:
            if job['cancel'].is_set():return
            job['status']='rendering'
        try:
            with tempfile.TemporaryDirectory(dir=self.folder,prefix='range-') as directory:
                work=Path(directory);dest=work/'program.mp4'
                render_engine.render_range(state,job['start'],job['end'],dest,work,'preview',
                                           lambda command,cwd:self._execute(job,command,cwd))
                if dest.stat().st_size>self.max_bytes:raise ValueError('Preview cache budget exceeded; choose a lower monitor resolution')
                digest=self._digest(dest)
                with self.guard:
                    if job['cancel'].is_set():return
                    os.replace(dest,job['path'])
                    metadata={'format':preview_dependencies.FORMAT,'id':job['id'],
                              'bytes':job['path'].stat().st_size,'sha256':digest}
                    project_store.atomic_write(job['path'].with_suffix('.json'),json.dumps(metadata).encode())
                    job.update(status='ready',percent=100,_fingerprint=self._stat(job['path']))
                    self._prune()
        except Exception as error:
            with self.guard:
                if not job['cancel'].is_set():job.update(status='error',error=str(error))

    def _execute(self,job,command,cwd):
        stage=job.get('_stage',0)
        offsets=(0,85,95);weights=(85,10,4)
        command=[command[0],'-progress','pipe:1',*command[1:]]
        with tempfile.TemporaryFile() as errors:
            with self.guard:
                if job['cancel'].is_set():raise RuntimeError('Preview cancelled')
                process=subprocess.Popen(command,cwd=cwd,stdout=subprocess.PIPE,stderr=errors,
                                         creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                job['process']=process
            try:
                for line in process.stdout:
                    if line.startswith(b'out_time_us='):
                        try:seconds=int(line.split(b'=')[1])/1e6
                        except ValueError:continue
                        percent=offsets[stage]+weights[stage]*seconds/(job['end']-job['start'])
                        with self.guard:job['percent']=min(99,round(percent))
                result=process.wait()
                if job['cancel'].is_set():raise RuntimeError('Preview cancelled')
                if result:
                    errors.seek(0,2);errors.seek(max(0,errors.tell()-1600))
                    raise RuntimeError(errors.read().decode(errors='replace'))
                job['_stage']=stage+1
            finally:
                if process.poll() is None:process.kill();process.wait()
                process.stdout.close()
                with self.guard:job['process']=None

    def _prune(self):
        files=[p for p in self.folder.glob('*.mp4') if self._owned(p) and os.path.normcase(os.path.abspath(p)) not in self.protected]
        sizes={p:p.stat().st_size for p in files};total=sum(sizes.values())
        order={j['path']:n for n,j in enumerate(self.jobs.values())}
        # Previous-session files precede the current in-memory LRU.
        files.sort(key=lambda p:(p in order,order.get(p,0),p.stat().st_mtime_ns))
        for path in files:
            if len(sizes)<=self.max_files and total<=self.max_bytes:break
            try:
                path.unlink();path.with_suffix('.json').unlink(missing_ok=True)
            except PermissionError:continue
            total-=sizes.pop(path)
            old=self.jobs.get(path.stem)
            if old and old['status'] not in ('queued','rendering'):self.jobs.pop(path.stem,None)
            self.counters['evicted']+=1
        for path in self.folder.glob('*.json'):
            if self._owned(path) and not path.with_suffix('.mp4').exists() and os.path.normcase(os.path.abspath(path)) not in self.protected:
                path.unlink(missing_ok=True)
        for key,job in list(self.jobs.items()):
            if len(self.jobs)<=self.max_files+4:break
            if job['status'] not in ('queued','rendering','ready'):del self.jobs[key]

    def status(self,key):
        with self.guard:
            job=self.jobs.get(key)
            if not job:raise ValueError('Preview range expired')
            return {k:v for k,v in job.items() if k not in ('cancel','process','path') and not k.startswith('_')}|{'url':'/preview/'+key+'.mp4'}

    def metrics(self):
        with self.guard:return dict(self.counters)

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
            self.condition.notify_all()
        self.worker.join()
