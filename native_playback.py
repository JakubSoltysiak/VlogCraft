"""Local experimental child process, native panel and cancellable bounded PCM streams."""
from copy import deepcopy
from pathlib import Path
import json,logging,os,subprocess,tempfile,threading,time
import native_plan,render_engine,timing,sequences


class CompletionTrace:
 """Keep one worker's endpoint milestones in memory until desktop teardown."""
 def __init__(self,path):
  self.path=Path(path);self.worker=None;self.owner=None

 def start(self,process,plan,started_ns):
  self.owner=process
  self.worker={'launch_requested_ns':started_ns,'end_frame':plan['endFrame']-1,
               'end_microseconds':round(plan['endFrame']/timing.rate(plan['rate'])*1000000),'events':{}}

 def status(self,status,received_ns,published_ns):
  events=self.worker['events'];generation=status.get('generation')
  terminal=status.get('completed_sequence_frame')==self.worker['end_frame'] and status.get('completed_generation')==generation
  names=['first_status'] if 'first_status' not in events else []
  if generation is not None and generation==self.worker.get('playing_generation'):
   if terminal and 'first_final_picture_status' not in events:names.append('first_final_picture_status')
   if status.get('eos') and 'first_eos_status' not in events:names.append('first_eos_status')
   if terminal and status.get('eos') and 'first_terminal_status' not in events:names.append('first_terminal_status')
  if names:
   row={'received_ns':received_ns,'published_ns':published_ns,
        **{k:status.get(k) for k in ('event','wall_seconds','generation','sequence_frame','completed_sequence_frame','completed_generation','eos','completion_stamps_us')}}
   for name in names:events[name]=row

 def teardown(self,process,status,received_ns):
  if process is self.owner and status.get('event')=='completion_diagnostic':
   self.worker['events']['producer_teardown']={'received_ns':received_ns,'generation':status.get('generation'),
                                             'completion_stamps_us':status.get('completion_stamps_us')}

 def clock(self,microseconds,playing,generation):
  if self.worker is None:return
  events=self.worker['events']
  if playing and generation!=self.worker.get('playing_generation'):
   self.worker['playing_generation']=generation
   for name in ('first_playing_clock','first_endpoint_clock','first_final_picture_status','first_eos_status','first_terminal_status'):
    events.pop(name,None)
   events['first_playing_clock']={'sent_ns':time.perf_counter_ns(),'microseconds':microseconds}
  if generation==self.worker.get('playing_generation') and microseconds>=self.worker['end_microseconds'] and 'first_endpoint_clock' not in events:
   events['first_endpoint_clock']={'sent_ns':time.perf_counter_ns(),'microseconds':microseconds,'playing':bool(playing)}

 def save(self):
  try:
   self.path.write_text(json.dumps({'clock':'Windows QPC via perf_counter_ns','worker':self.worker},indent=2)+'\n',encoding='utf8')
  except OSError:
   logging.exception('Could not retain native completion timing')


class Controller:
 def __init__(self,window,cache,bundle):
  self.window=window;self.cache=Path(cache)/'native-preview';self.cache.mkdir(exist_ok=True)
  self.bundle=Path(bundle);self.guard=threading.RLock();self.process=None;self.panel=None;self.latest={};self.generation=0;self.snapshot=None
  self.audio_processes=set();self.closed=False;self.reader_thread=None;self.clock_position=0
  completion_path=os.environ.get('VLOGCRAFT_COMPLETION_TRACE')
  self.completion_trace=CompletionTrace(completion_path) if completion_path else None
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
    received_ns=time.perf_counter_ns() if self.completion_trace else None
    try:status=json.loads(line)
    except (ValueError,TypeError):continue
    with self.guard:
     if process is self.process:
      self.latest=status
      if self.completion_trace:self.completion_trace.status(status,received_ns,time.perf_counter_ns())
     elif self.completion_trace:self.completion_trace.teardown(process,status,received_ns)
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
   started_ns=time.perf_counter_ns() if self.completion_trace else None
   process=subprocess.Popen([str(exe),'--plan',str(target),'--parent',str(parent)],env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=log,text=True,encoding='utf8',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
   log.close();self.process=process;self.latest={'event':'starting'}
   if self.completion_trace:self.completion_trace.start(process,plan,started_ns)
   self.reader_thread=threading.Thread(target=self._read,args=(process,),daemon=True);self.reader_thread.start()
  self.clock(data.get('microseconds',0),False,generation)
  return {k:v for k,v in plan.items() if k!='text'}|{'generation':generation}
 def clock(self,microseconds,playing,generation):
  with self.guard:
   if generation!=self.generation:return {'stale':True}
   self.clock_position=int(microseconds)
   if self.process and self.process.poll() is None:
    try:
     self.process.stdin.write(f'CLOCK {int(microseconds)} {int(bool(playing))} {generation}\n');self.process.stdin.flush()
     if self.completion_trace:self.completion_trace.clock(self.clock_position,playing,generation)
    except (BrokenPipeError,OSError):self.latest={'event':'error','reason':'Native renderer stopped; reference fallback is available'}
   return dict(self.latest)
 def seek(self,frame,generation=None):
  with self.guard:
   if generation is not None and generation!=self.generation:return {'stale':True,'generation':self.generation}
   if self.snapshot is None:raise ValueError('Native preview is not prepared')
   fps=timing.rate(self.snapshot['output']['fps']);self.generation+=1;generation=self.generation;audio=list(self.audio_processes)
  self.clock(round(int(frame)/fps*1000000),False,generation)
  for p in audio:self._terminate(p)
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
   process=self.process;self.process=None;self.snapshot=None;self.generation+=1;reader=self.reader_thread;self.reader_thread=None
   audio=list(self.audio_processes)
   if process and process.poll() is None:
    try:process.stdin.write('CLOSE\n');process.stdin.flush()
    except (BrokenPipeError,OSError):pass
  if self.panel is not None and not self.closed:self.bounds({'x':0,'y':0,'width':2,'height':2,'dpr':1},False)
  for p in audio:self._terminate(p)
  if process:
   try:process.wait(timeout=3)
   except subprocess.TimeoutExpired:self._terminate(process)
   if reader is not None and reader is not threading.current_thread():reader.join(timeout=2)
   for pipe in (process.stdin,process.stdout):
    if pipe:pipe.close()
 def close(self):
  with self.guard:self.closed=True
  self.stop()
  if self.completion_trace:self.completion_trace.save()
 def audio(self,generation,frame):
  with self.guard:
   if self.closed or generation!=self.generation or self.snapshot is None:raise ValueError('Obsolete native audio request')
   if sum(p.poll() is None for p in self.audio_processes)>=2:raise ValueError('Native PCM stream budget is busy')
   # Published snapshots are immutable: seek changes generation, start replaces
   # the snapshot, and Stop releases it. Retain the old reference only while
   # preparing, without blocking clock delivery or native status ingestion.
   snapshot=self.snapshot
  state=deepcopy(snapshot);fps=timing.rate(state['output']['fps']);total=timing.frame_at(render_engine.sequence_duration(state),fps)
  frame=int(frame)
  if frame<0 or frame>=total:raise ValueError('Native audio frame outside sequence')
  end=min(total,frame+timing.nearest(8*fps));samples=timing.sample_at(end,fps)-timing.sample_at(frame,fps)
  folder=tempfile.TemporaryDirectory(prefix='pcm-',dir=self.cache)
  try:
   root=Path(folder.name);cmd=render_engine.segment_command(state,float(frame/fps),float(end/fps),root/'audio.wav',root,'preview','audio')
   cmd=cmd[:-1]+['-f','s16le','pipe:1']
   with self.guard:
    if self.closed or generation!=self.generation or self.snapshot is not snapshot:raise ValueError('Obsolete native audio preparation')
    if sum(p.poll() is None for p in self.audio_processes)>=2:raise ValueError('Native PCM stream budget is busy')
    with (root/'error.log').open('wb') as error:
     p=subprocess.Popen(cmd,cwd=root,stdout=subprocess.PIPE,stderr=error,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    self.audio_processes.add(p)
  except BaseException:
   folder.cleanup();raise
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
