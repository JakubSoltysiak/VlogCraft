"""Local QA accounting. No editor imports, frame callbacks or network access."""
from contextlib import contextmanager
from datetime import datetime,timezone
import json,os,tempfile,time,uuid
from pathlib import Path
import psutil

DEFAULT=Path(__file__).resolve().parents[1]/'build/qa/status.json'
TERMINAL={'passed','failed','skipped','cancelled'}

def utc():return datetime.now(timezone.utc).isoformat()

def read_document(path):
    # Windows may briefly deny a new reader while replacing the destination.
    # Retry only that sharing condition; corrupt JSON is preserved and reported.
    deadline=time.monotonic()+1
    while True:
        try:return json.loads(Path(path).read_text('utf8'))
        except PermissionError:
            if time.monotonic()>=deadline:raise
            time.sleep(.01)

@contextmanager
def locked(path):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.with_suffix(path.suffix+'.lock').open('a+b') as handle:
        handle.seek(0,2)
        if not handle.tell():handle.write(b'0');handle.flush()
        deadline=time.monotonic()+5
        while True:
            try:
                handle.seek(0)
                if os.name=='nt':
                    import msvcrt
                    msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic()>=deadline:raise TimeoutError('QA status writer lock unavailable')
                time.sleep(.01)
        try:yield
        finally:
            handle.seek(0)
            if os.name=='nt':msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(handle.fileno(),fcntl.LOCK_UN)

def atomic(path,data):
    fd,name=tempfile.mkstemp(prefix='.qa-status-',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf8') as output:
            json.dump(data,output,ensure_ascii=False,indent=2);output.write('\n');output.flush();os.fsync(output.fileno())
        deadline=time.monotonic()+1
        while True:
            try:os.replace(name,path);break
            except PermissionError:
                if time.monotonic()>=deadline:raise
                time.sleep(.01)
    finally:
        if os.path.exists(name):os.unlink(name)

class Tracker:
    def __init__(self,path=DEFAULT,run_id=None,title='Local QA'):
        self.path=Path(path);self.run_id=run_id or uuid.uuid4().hex;self.title=title

    def edit(self,change):
        with locked(self.path):
            data=read_document(self.path) if self.path.exists() else {'schema_version':1,'runs':{}}
            if data.get('schema_version')!=1:raise ValueError('Unsupported QA status schema')
            run=data['runs'].setdefault(self.run_id,{'title':self.title,'started':utc(),'phase':'setup','plan_complete':False,'cases':{}})
            change(run);run['updated']=data['updated']=utc();data['current_run']=self.run_id
            atomic(self.path,data)

    def plan(self,names,complete=False):
        def change(run):
            for name in names:run['cases'].setdefault(name,{'name':name,'status':'pending','attempts':[]})
            run['plan_complete']=complete
        self.edit(change)

    def start(self,key,name=None,phase='verification',expected_seconds=None,pid=None):
        token=uuid.uuid4().hex
        def change(run):
            case=run['cases'].setdefault(key,{'name':name or key,'status':'pending','attempts':[]})
            if case['status']=='running':raise ValueError('QA case already running; use a distinct case ID for parallel work')
            record={'token':token,'status':'running','started':utc(),'started_epoch':time.time(),'heartbeat':utc(),'elapsed_seconds':0,
                    'expected_seconds':expected_seconds,'last_activity_epoch':time.time(),'progress_scope':'Supervisor elapsed wall time; duration is the declared workload, not measured frame progress.'}
            if pid:
                record['controller']={'pid':pid,'created':psutil.Process(pid).create_time()}
            case['attempts'].append(record);case['status']='running';run['phase']=phase
        self.edit(change);return token

    def heartbeat(self,key,token,elapsed,activity=False,progress=None):
        def change(run):
            record=run['cases'][key]['attempts'][-1]
            if record['token']!=token or record['status']!='running':return
            record.update(heartbeat=utc(),elapsed_seconds=elapsed)
            if activity:record['last_activity_epoch']=time.time()
            if progress is not None:record['reported_progress']=progress
        self.edit(change)

    def finish(self,key,token,status,exit_code=None,reason=None):
        if status not in TERMINAL:raise ValueError('Invalid terminal QA status')
        def change(run):
            case=run['cases'][key];record=case['attempts'][-1]
            if record['token']!=token:raise ValueError('Obsolete QA attempt cannot complete a retry')
            if record['status']!='running':raise ValueError('Completed QA attempt is immutable')
            record.update(status=status,ended=utc(),exit_code=exit_code,reason=reason,
                          elapsed_seconds=time.time()-record['started_epoch'])
            case['status']=status
        self.edit(change)

    def import_legacy(self,rows):
        def change(run):
            if run['cases']:raise ValueError('Legacy import requires a new run; never overwrite existing history')
            for row in rows:
                key=row['name'];case=run['cases'].setdefault(key,{'name':key,'attempts':[]})
                status='passed' if row['exit_code']==0 else 'failed'
                case['attempts'].append({'status':status,'exit_code':row['exit_code'],'elapsed_seconds':row.get('seconds'),
                                        'scope':'Imported completed command record; legacy timestamps/heartbeat unavailable.'})
                case['status']=status
            run.update(plan_complete=True,phase='historical results',historical_import=True)
        self.edit(change)

def snapshot(path=DEFAULT,run_id=None,now=None):
    data=read_document(path);run_id=run_id or data['current_run'];run=data['runs'][run_id];now=time.time() if now is None else now
    counts={k:sum(c['status']==k for c in run['cases'].values()) for k in ('pending','running',*sorted(TERMINAL))}
    discovered=len(run['cases']);completed=sum(counts[k] for k in TERMINAL);current=[]
    for key,case in run['cases'].items():
        if case['status']!='running':continue
        r=case['attempts'][-1];controller=r.get('controller');alive=None
        if controller:
            try:alive=psutil.Process(controller['pid']).create_time()==controller['created']
            except psutil.Error:alive=False
        heartbeat_age=max(0,now-datetime.fromisoformat(r['heartbeat']).timestamp())
        activity_age=max(0,now-r['last_activity_epoch'])
        current.append({'id':key,'name':case['name'],**r,'controller_alive':alive,'heartbeat_age_seconds':heartbeat_age,
                        'activity_age_seconds':activity_age,'observation_status':'controller exited without a result' if alive is False else ('heartbeat stale' if heartbeat_age>10 else ('no recent CPU/I/O activity; idle or stalled' if activity_age>30 else 'heartbeat and process activity observed'))})
    return {'run_id':run_id,'title':run['title'],'phase':run['phase'],'last_update':run['updated'],'counts':counts,'completed':completed,
            'total':discovered if run['plan_complete'] else None,'discovered':discovered,
            'completion_percent':100*completed/discovered if run['plan_complete'] and discovered else None,
            'discovered_completion_percent':100*completed/discovered if discovered else 0,
            'remaining':counts['pending'],'running':current,
            'attempts':sum(len(c['attempts']) for c in run['cases'].values()),
            'historical_failed_attempts':sum(a['status']=='failed' for c in run['cases'].values() for a in c['attempts']),
            'counting_scope':'Unique QA case IDs; retries append attempts without increasing the total. Command cases may contain many unit tests. Unknown final totals stay unknown.',
            'run_ids':list(data['runs'])}

def duration(command):
    try:
        flag='--measure-seconds' if '--measure-seconds' in command else '--seconds'
        seconds=float(command[command.index(flag)+1])
        if '--repeat' in command:seconds*=int(command[command.index('--repeat')+1])
        return seconds if seconds>0 else None
    except (ValueError,IndexError):return None

class Activity:
    """Two-second supervisor sampling; process counters only, never GPU/PDH."""
    def __init__(self,pid):self.pid=pid;self.previous=None
    def sample(self):
        values=[]
        try:family=[psutil.Process(self.pid),*psutil.Process(self.pid).children(recursive=True)]
        except psutil.Error:return False
        for p in family:
            try:
                cpu=p.cpu_times();io=p.io_counters();values.append((p.pid,p.create_time(),cpu.user+cpu.system,io.read_bytes+io.write_bytes))
            except psutil.Error:pass
        value=sorted(values);changed=self.previous is not None and value!=self.previous;self.previous=value
        return changed
