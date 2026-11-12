"""Sample only the launched editor and its descendants during the Windows test."""
import threading
import time
from gpu_metrics import GPU
import psutil


class Resources:
    def __init__(self,pid,gpu=False):
        self.root=psutil.Process(pid)
        self.gpu=GPU() if gpu else None
        self.started=time.monotonic()
        self.initial={}
        for p in [self.root,*self.root.children(recursive=True)]:
            try:
                cpu=p.cpu_times();io=p.io_counters()
                self.initial[(p.pid,p.create_time())]=(cpu.user+cpu.system,io.read_bytes,io.write_bytes)
            except psutil.Error:pass
        self.stop=threading.Event()
        self.peak=0
        self.totals={}
        self.thread=threading.Thread(target=self.sample,daemon=True)
        self.thread.start()

    def sample(self):
        while not self.stop.is_set():
            rss=0
            try:procs=[self.root,*self.root.children(recursive=True)]
            except psutil.Error:break
            for process in procs:
                try:
                    with process.oneshot():
                        rss+=process.memory_info().rss
                        cpu=process.cpu_times();io=process.io_counters()
                        self.totals[(process.pid,process.create_time())]=(cpu.user+cpu.system,io.read_bytes,io.write_bytes)
                except psutil.Error:continue
            if self.gpu:self.gpu.sample({p.pid for p in procs})
            self.peak=max(self.peak,rss)
            self.stop.wait(.1)

    def finish(self):
        self.stop.set();self.thread.join()
        rows=[tuple(v-b for v,b in zip(values,self.initial.get(key,(0,0,0)))) for key,values in self.totals.items()]
        cpu=sum(r[0] for r in rows);elapsed=time.monotonic()-self.started
        gpu=self.gpu.finish() if self.gpu else None
        return {'duration_seconds':round(elapsed,3),'gpu':gpu,
                'average_cpu_machine_percent':round(100*cpu/elapsed/(psutil.cpu_count() or 1),2),
                'peak_summed_working_set_MiB':round(self.peak/2**20,1),
                'sampled_cpu_seconds':round(sum(r[0] for r in rows),2),
                'process_read_MiB':round(sum(r[1] for r in rows)/2**20,1),
                'process_write_MiB':round(sum(r[2] for r in rows)/2**20,1)}
