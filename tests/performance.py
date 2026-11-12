"""Sample only the launched editor and its descendants during the Windows test."""
import threading
import psutil


class Resources:
    def __init__(self,pid):
        self.root=psutil.Process(pid)
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
            self.peak=max(self.peak,rss)
            self.stop.wait(.1)

    def finish(self):
        self.stop.set();self.thread.join()
        rows=list(self.totals.values())
        return {'peak_summed_working_set_MiB':round(self.peak/2**20,1),
                'sampled_cpu_seconds':round(sum(r[0] for r in rows),2),
                'process_read_MiB':round(sum(r[1] for r in rows)/2**20,1),
                'process_write_MiB':round(sum(r[2] for r in rows)/2**20,1)}
