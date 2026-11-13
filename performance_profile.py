"""Opt-in, local-only hardware diagnostics. Only explicit technical fields leave this module."""
import ctypes,importlib.util,json,os,subprocess,tempfile,threading,time
from pathlib import Path
import psutil
FIELDS={
 'cpu':('Name','NumberOfCores','NumberOfLogicalProcessors','L2CacheSize','L3CacheSize'),
 'memory':('Capacity','ConfiguredClockSpeed','SMBIOSMemoryType','DataWidth'),
 'os':('Caption','Version','BuildNumber','TotalVisibleMemorySize'),
 'gpu':('Name','DriverVersion','DriverDate','CurrentHorizontalResolution','CurrentVerticalResolution','CurrentRefreshRate'),
 'storage':('FriendlyName','MediaType','BusType','Size','HealthStatus'),
 'volume':('FileSystem','Size','SizeRemaining'),
 'npu':('DeviceName','DriverVersion','Manufacturer')}
def sanitize(data):
 result={}
 for category,fields in FIELDS.items():
  value=data.get(category,[]);rows=value if isinstance(value,list) else [value]
  result[category]=[{k:row[k] for k in fields if k in row} for row in rows if isinstance(row,dict)]
 return result
def inventory(bundle,cache=None,runner=None):
 if os.name!='nt':return {'available':False,'reason':'Windows hardware APIs unavailable'}
 script=r"""
$ErrorActionPreference='Stop'
@{
 cpu=Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors,L2CacheSize,L3CacheSize
 memory=Get-CimInstance Win32_PhysicalMemory | Select-Object Capacity,ConfiguredClockSpeed,SMBIOSMemoryType,DataWidth
 os=Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,BuildNumber,TotalVisibleMemorySize
 gpu=Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion,DriverDate,CurrentHorizontalResolution,CurrentVerticalResolution,CurrentRefreshRate
 storage=Get-PhysicalDisk | Select-Object FriendlyName,MediaType,BusType,Size,HealthStatus
 volume=Get-Volume -DriveLetter C | Select-Object FileSystem,Size,SizeRemaining
 npu=Get-CimInstance Win32_PnPSignedDriver | Where-Object {$_.DeviceClass -eq 'COMPUTEACCELERATOR'} | Select-Object DeviceName,DriverVersion,Manufacturer
} | ConvertTo-Json -Depth 5 -Compress
"""
 drive=Path(cache or tempfile.gettempdir()).resolve().drive
 letter=drive[0].upper() if len(drive)==2 and drive[1]==':' and drive[0].isalpha() else None
 if letter:script=script.replace('Get-Volume -DriveLetter C','Get-Volume -DriveLetter '+letter)
 else:script=script.replace('Get-Volume -DriveLetter C','@()')
 p=(runner or subprocess.run)(['powershell','-NoProfile','-NonInteractive','-Command',script],capture_output=True,text=True,encoding='utf8',errors='replace',timeout=35,creationflags=subprocess.CREATE_NO_WINDOW)
 if p.returncode:raise RuntimeError('Local hardware inventory failed')
 result=sanitize(json.loads(p.stdout));b=psutil.sensors_battery()
 result.update(available=True,ac_power=None if b is None else b.power_plugged,available_memory_MiB=psutil.virtual_memory().available//2**20,
  thermal_throttling='Unavailable from the current public sensors',npu_python_runtime=bool(importlib.util.find_spec('onnxruntime')))
 probe=find_tool(bundle,'VlogCraftProbe.exe')
 if probe:
  result['native']=run_probe(probe,[],bundle,runner)
 return result
def find_tool(bundle,name):
 paths=[Path(bundle)/'engine/native'/name,Path(__file__).resolve().parent/'build/tools/architecture'/name]
 return next((p for p in paths if p.is_file()),None)
def run_probe(exe,args,bundle,runner=None):
 sdk=Path(__file__).resolve().parent/'build/tools/architecture/ffmpeg-shared/ffmpeg-9.0.2-full_build-shared/bin'
 env=dict(os.environ,PATH=str(exe.parent)+os.pathsep+str(sdk)+os.pathsep+os.environ['PATH'])
 p=(runner or subprocess.run)([str(exe),*map(str,args)],env=env,capture_output=True,text=True,timeout=45,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
 if p.returncode:return {'available':False,'reason':'Local probe unavailable'}
 return json.loads(p.stdout)
def storage_test(bundle,cache,runner=None):
 exe=find_tool(bundle,'VlogCraftStorageProbe.exe')
 if not exe:return {'available':False,'reason':'Optional bounded storage probe is not installed'}
 with tempfile.TemporaryDirectory(prefix='performance-',dir=cache) as folder:
  return run_probe(exe,[Path(folder)/'scratch.bin'],bundle,runner)
def recommend(report):
 # No engine switch or export setting is inferred from inventory alone.
 free=report['hardware'].get('available_memory_MiB',0)
 native=report['hardware'].get('native',{});outputs=[o for a in native.get('adapters',[]) for o in a.get('outputs',[])]
 display_width=max([o.get('width',0) for o in outputs] or [1920])
 width=960 if free<3072 else min(1920,display_width)
 width=max(x for x in (640,960,1280,1920) if x<=max(640,width))
 return {'preview_width':width,'reason':'Conservative display/memory recommendation; sustained multitrack timing still determines usable quality',
         'native_experimental':True,'export_settings_changed':False,'source_queue_frames':4,'max_active_video_decoders':3,'gpu_slots':3}
class Diagnostics:
 def __init__(self,bundle,cache):
  self.bundle=Path(bundle);self.cache=Path(cache);self.lock=threading.Lock();self.latest={'status':'idle'};self.thread=None;self.closed=False;self.processes=set()
 def start(self,storage=False):
  with self.lock:
   if self.closed:raise ValueError('Diagnostics closed')
   if self.thread and self.thread.is_alive():return dict(self.latest)
   self.latest={'status':'running'}
   self.thread=threading.Thread(target=self._run,args=(storage,),daemon=True);self.thread.start();return dict(self.latest)
 def _execute(self,command,**kwargs):
  timeout=kwargs.pop('timeout',None)
  if kwargs.pop('capture_output',False):kwargs.update(stdout=subprocess.PIPE,stderr=subprocess.PIPE)
  with self.lock:
   if self.closed:raise ValueError('Diagnostics closed before process launch')
   child=subprocess.Popen(command,**kwargs);self.processes.add(child)
  try:
   stdout,stderr=child.communicate(timeout=timeout)
   return subprocess.CompletedProcess(command,child.returncode,stdout,stderr)
  finally:
   self._terminate(child)
   with self.lock:self.processes.discard(child)
 def _terminate(self,child):
  if child.poll() is None:
   child.terminate()
   try:child.wait(timeout=3)
   except subprocess.TimeoutExpired:child.kill();child.wait(timeout=2)
 def _run(self,storage):
  try:
   report={'hardware':inventory(self.bundle,self.cache,self._execute)}
   if storage:report['storage_test']=storage_test(self.bundle,self.cache,self._execute)
   report['recommendation']=recommend(report);report['status']='complete'
   # Machine-local, sanitized, replace-only result. No project or media identity.
   if self.closed:raise ValueError('Diagnostics closed')
   target=self.cache/'performance-profile.json';temp=target.with_suffix('.tmp')
   temp.write_text(json.dumps(report,indent=2),encoding='utf8');temp.replace(target)
  except Exception:report={'status':'cancelled' if self.closed else 'error','reason':'Local diagnostic failed; ordinary editing remains available'}
  with self.lock:self.latest=report
 def status(self):
  with self.lock:return dict(self.latest)
 def close(self):
  with self.lock:self.closed=True;children=list(self.processes)
  for child in children:self._terminate(child)
  if self.thread:self.thread.join(timeout=3)
