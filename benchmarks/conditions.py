"""Local, identifier-free workstation conditions during a benchmark."""
import threading,time,psutil
class Conditions:
 def __init__(self):
  self.stop=threading.Event();self.rows=[];self.started=time.monotonic()
  self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()
 def run(self):
  while not self.stop.is_set():
   b=psutil.sensors_battery();m=psutil.virtual_memory()
   self.rows.append({'seconds':round(time.monotonic()-self.started,3),'ac_power':None if b is None else b.power_plugged,
    'battery_percent':None if b is None else b.percent,'available_memory_MiB':round(m.available/2**20),'system_cpu_percent':psutil.cpu_percent()})
   if len(self.rows)>7200:self.rows.pop(0)
   self.stop.wait(1)
 def finish(self):
  self.stop.set();self.thread.join();return {'samples':self.rows,'mixed_power':len({r['ac_power'] for r in self.rows})>1,
   'thermal_throttling':'not observable with available public sensors'}
