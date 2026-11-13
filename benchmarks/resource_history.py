"""Bounded sampled process-family working-set history; shared pages may be counted twice."""
import threading,time,psutil
class History:
 def __init__(self,pid,interval=10):
  self.root=psutil.Process(pid);self.started=time.monotonic();self.rows=[];self.stop=threading.Event();self.interval=interval
  self.thread=threading.Thread(target=self._sample,daemon=True);self.thread.start()
 def _sample(self):
  while not self.stop.is_set():
   try:family=[self.root,*self.root.children(recursive=True)]
   except psutil.Error:break
   rss=0
   for process in family:
    try:rss+=process.memory_info().rss
    except psutil.Error:pass
   self.rows.append({'seconds':round(time.monotonic()-self.started,3),'summed_working_set_MiB':round(rss/2**20,2)})
   self.stop.wait(self.interval)
 def finish(self):
  self.stop.set();self.thread.join();return self.rows
