"""Bounded local per-thread/core/commit sampling. Never collect command lines or paths."""
import threading,time,psutil

def windows(rows,seconds):
    rates=[]
    for i,a in enumerate(rows):
        for b in rows[i+1:]:
            elapsed=b['wall_seconds']-a['wall_seconds']
            if elapsed>=seconds:
                if elapsed<=seconds+.5:rates.append((b['present_calls']-a['present_calls'])/elapsed)
                break
    return {'window_seconds':seconds,'count':len(rates),'minimum_fps':min(rates) if rates else None,
            'p05_fps':sorted(rates)[max(0,int(len(rates)*.05)-1)] if rates else None,
            'method':'Native status-counter deltas over >=window, <=window+.5 s; not physical scanout.'}

def active_windows(rows,seconds,last_frame):
    """Exclude terminal paused status, keeping historical raw windows separately."""
    active=[r for r in rows if 0<r.get('sequence_frame',0)<last_frame]
    result=windows(active,seconds)
    result['method']+=' Frame-zero preparation and terminal paused status excluded.'
    return result

class RuntimeTrace:
    def __init__(self,pid):
        self.root=psutil.Process(pid);self.rows=[];self.previous={};self.thread_cpu={};self.stop=threading.Event()
        self.started=time.monotonic();self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()
    def run(self):
        psutil.cpu_percent(percpu=True)
        while not self.stop.is_set():
            row={'seconds':round(time.monotonic()-self.started,3),'logical_cpu_percent':psutil.cpu_percent(percpu=True),'groups':{}}
            try:family=[self.root,*self.root.children(recursive=True)]
            except psutil.Error:break
            for p in family:
                try:
                    name=p.name().lower()
                    group='native' if name=='vlogcraftnative.exe' else 'webview' if name=='msedgewebview2.exe' else 'ffmpeg' if name=='ffmpeg.exe' else 'host'
                    values=row['groups'].setdefault(group,{'rss_MiB':0,'private_commit_MiB':0,'thread_count':0})
                    memory=p.memory_info();values['rss_MiB']+=memory.rss/2**20
                    values['private_commit_MiB']+=getattr(memory,'private',memory.vms)/2**20
                    threads=p.threads();values['thread_count']+=len(threads)
                    for t in threads:
                        key=(p.pid,t.id);now=t.user_time+t.system_time;previous=self.previous.get(key,now)
                        self.thread_cpu[(group,*key)]=self.thread_cpu.get((group,*key),0)+max(0,now-previous)
                        self.previous[key]=now
                except psutil.Error:pass
            self.rows.append(row)
            if len(self.rows)>14400:self.rows.pop(0)
            self.stop.wait(.5)
    def finish(self):
        self.stop.set();self.thread.join();elapsed=time.monotonic()-self.started
        ranked=sorted(({'group':k[0],'cpu_seconds':round(v,4),'logical_core_percent':round(100*v/elapsed,2)}
                       for k,v in self.thread_cpu.items()),key=lambda r:r['cpu_seconds'],reverse=True)[:24]
        return {'interval_seconds':.5,'samples':self.rows,'top_threads_anonymous':ranked,
                'thread_core_assignment':'Per-core load and per-thread CPU time; scheduler migration/core placement requires ETW, not inferred.'}
