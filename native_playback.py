"""Local experimental child process, native panel and cancellable bounded PCM streams."""
from copy import deepcopy
from pathlib import Path
import json,os,subprocess,tempfile,threading,time
import native_plan,render_engine,timing,sequences
class Controller:
 def __init__(self,window,cache,bundle):
  self.window=window;self.cache=Path(cache)/'native-preview';self.cache.mkdir(exist_ok=True)
  self.bundle=Path(bundle);self.guard=threading.RLock();self.process=None;self.panel=None;self.latest={};self.generation=0;self.snapshot=None
  self.audio_processes=set();self.closed=False
 def runtime(self):
  override=os.environ.get('VLOGCRAFT_NATIVE_BINARY')
  if override:
   exe=Path(override).resolve();return exe,Path(__file__).resolve().parent/'build/tools/architecture/ffmpeg-shared/ffmpeg-9.0.2-full_build-shared/bin'
  packaged=self.bundle/'engine/native/VlogCraftNative.exe'
  source=Path(__file__).resolve().parent/'build/tools/architecture/VlogCraftNative.exe'
  exe=packaged if packaged.is_file() else source
  dll=exe.parent if exe==packaged else source.parent/'ffmpeg-shared/ffmpeg-9.0.2-full_build-shared/bin'
  return exe,dll
 def capabilities(self):
  exe,_=self.runtime();return {'available':os.name=='nt' and exe.is_file(),'experimental':True,'videoLayers':3,'audio':'48k stereo PCM','default':False}
 def bounds(self,rect,visible=True):
  if self.panel is None:return
  from System import Action
  from System.Drawing import Rectangle
  def update():
   factor=float(rect.get('dpr',1))
   self.panel.Bounds=Rectangle(*[round(float(rect[k])*factor) for k in ('x','y','width','height')]);self.panel.Visible=visible;self.panel.BringToFront()
  self.window.native.Invoke(Action(update))
 def _panel(self,rect):
  if self.panel is None:
   from System import Action
   from System.Windows.Forms import Panel
   from System.Drawing import Color
   def create():
    self.panel=Panel();self.panel.BackColor=Color.Black;self.window.native.Controls.Add(self.panel)
   self.window.native.Invoke(Action(create))
  self.bounds(rect);return int(self.panel.Handle.ToInt64())
 def _read(self,process):
  try:
   for line in process.stdout:
    try:status=json.loads(line)
    except (ValueError,TypeError):continue
    with self.guard:
     if process is self.process:self.latest=status
  finally:
   with self.guard:
    if process is self.process and self.latest.get('event')!='error':self.latest={'event':'error','reason':'Native renderer exited; use reference fallback'}
 def start(self,state,data):
  with self.guard:
   if self.closed:raise ValueError('Native service is closed')
  self.stop()
  working=deepcopy(state);used={c.get('assetId') for c in sequences.clips(working['tracks'])}
  for a in working['assets']:
   if a['id'] in used and ('rotation' not in a or 'colorTransfer' not in a or (a.get('hasAudio') and not a.get('audioChannels'))):
    from server import probe
    fresh=probe(Path(a['path']))
    for key in ('rotation','colorTransfer','colorPrimaries','colorSpace','colorRange','pixelFormat','audioChannels','audioChannelLayout','audioSampleRate','hdr'):a[key]=fresh.get(key)
  plan=native_plan.compile_plan(working,data.get('width',960))
  with self.guard:
   if self.closed:raise ValueError('Native service is closed')
   exe,dll=self.runtime()
   if not exe.is_file():raise native_plan.Unsupported('Native runtime is not installed; the reference renderer remains available')
   parent=self._panel(data['rect']);self.snapshot=working;self.generation+=1;generation=self.generation
   target=self.cache/'sequence.plan';target.write_text(plan['text'],encoding='utf8')
   log=(self.cache/'native-errors.log').open('w',encoding='utf8')
   env=dict(os.environ,PATH=str(dll)+os.pathsep+os.environ['PATH'])
   process=subprocess.Popen([str(exe),'--plan',str(target),'--parent',str(parent)],env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=log,text=True,encoding='utf8',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
   log.close();self.process=process;self.latest={'event':'starting'}
   threading.Thread(target=self._read,args=(process,),daemon=True).start()
  self.clock(data.get('microseconds',0),False,generation)
  return {k:v for k,v in plan.items() if k!='text'}|{'generation':generation}
 def clock(self,microseconds,playing,generation):
  with self.guard:
   if generation!=self.generation:return {'stale':True}
   if self.process and self.process.poll() is None:
    try:self.process.stdin.write(f'CLOCK {int(microseconds)} {int(bool(playing))} {generation}\n');self.process.stdin.flush()
    except (BrokenPipeError,OSError):self.latest={'event':'error','reason':'Native renderer stopped; reference fallback is available'}
   return dict(self.latest)
 def seek(self,frame,generation=None):
  with self.guard:
   if generation is not None and generation!=self.generation:return {'stale':True,'generation':self.generation}
   if self.snapshot is None:raise ValueError('Native preview is not prepared')
   fps=timing.rate(self.snapshot['output']['fps']);self.generation+=1;generation=self.generation;audio=list(self.audio_processes)
  for p in audio:self._terminate(p)
  self.clock(round(int(frame)/fps*1000000),False,generation)
  return {'generation':generation}
 def status(self):
  with self.guard:return dict(self.latest)|{'generation':self.generation,'running':bool(self.process and self.process.poll() is None)}
 def _terminate(self,process):
  if process.poll() is None:
   process.terminate()
   try:process.wait(timeout=2)
   except subprocess.TimeoutExpired:process.kill();process.wait(timeout=2)
 def stop(self):
  with self.guard:
   process=self.process;self.process=None;self.generation+=1
   audio=list(self.audio_processes)
   if process and process.poll() is None:
    try:process.stdin.write('CLOSE\n');process.stdin.flush()
    except (BrokenPipeError,OSError):pass
  if self.panel is not None and not self.closed:self.bounds({'x':0,'y':0,'width':2,'height':2,'dpr':1},False)
  for p in audio:self._terminate(p)
  if process:
   try:process.wait(timeout=3)
   except subprocess.TimeoutExpired:self._terminate(process)
   for pipe in (process.stdin,process.stdout):
    if pipe:pipe.close()
 def close(self):
  with self.guard:self.closed=True
  self.stop()
 def audio(self,generation,frame):
  with self.guard:
   if generation!=self.generation or self.snapshot is None:raise ValueError('Obsolete native audio request')
   state=deepcopy(self.snapshot);fps=timing.rate(state['output']['fps']);total=timing.frame_at(render_engine.sequence_duration(state),fps)
   frame=int(frame)
   if frame<0 or frame>=total:raise ValueError('Native audio frame outside sequence')
   end=min(total,frame+timing.nearest(8*fps));samples=timing.sample_at(end,fps)-timing.sample_at(frame,fps)
   if sum(p.poll() is None for p in self.audio_processes)>=2:raise ValueError('Native PCM stream budget is busy')
   folder=tempfile.TemporaryDirectory(prefix='pcm-',dir=self.cache)
   root=Path(folder.name);cmd=render_engine.segment_command(state,float(frame/fps),float(end/fps),root/'audio.wav',root,'preview','audio')
   cmd=cmd[:-1]+['-f','s16le','pipe:1']
   error=(root/'error.log').open('wb');p=subprocess.Popen(cmd,cwd=root,stdout=subprocess.PIPE,stderr=error,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0));error.close();self.audio_processes.add(p)
  def chunks():
   count=0
   try:
    while count<samples*4:
     with self.guard:
      if self.generation!=generation:raise ValueError('Native audio superseded')
     data=p.stdout.read(min(32768,samples*4-count))
     if not data:break
     count+=len(data);yield data
    code=p.wait(timeout=10)
    if code or count!=samples*4:raise ValueError('Native PCM stream did not complete its sample budget')
   finally:
    self._terminate(p);p.stdout.close()
    with self.guard:self.audio_processes.discard(p)
    folder.cleanup()
  return samples,end,chunks()
