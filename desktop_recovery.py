"""Event-driven Windows view recovery. Project state stays owned by the local backend."""
from copy import deepcopy
from datetime import datetime,timezone
from pathlib import Path
import base64,gzip,hashlib,json,logging,threading,time,shutil
import project_store


class Journal:
    """One coalescing writer; acknowledgements follow atomic publication, never precede it."""
    def __init__(self,path,ack=lambda epoch,sequence:None):
        self.path=Path(path);self.ack=ack;self.guard=threading.RLock();self.pending=None;self.thread=None
        self.latest=None;self.error=None;self.warning=None
        if self.path.is_file():
            try:self.latest=json.loads(self.path.read_text('utf8'))
            except (ValueError,OSError):
                self.warning='An unreadable recovery checkpoint was retained; the published project was opened.'
                shutil.copy2(self.path,self.path.with_name(self.path.stem+'-unreadable-'+str(time.time_ns())+'.json'))
                logging.exception('Reading recovery checkpoint')

    def submit(self,record):
        with self.guard:
            self.latest=record;self.pending=record
            if self.thread is None or not self.thread.is_alive():
                self.thread=threading.Thread(target=self._write,daemon=True);self.thread.start()

    def _write(self):
        while True:
            with self.guard:
                record=self.pending;self.pending=None
                if record is None:self.thread=None;return
            try:
                project_store.atomic_write(self.path,json.dumps(record,ensure_ascii=False,allow_nan=False).encode('utf8'))
                with self.guard:self.error=None
                self.ack(record['epoch'],record['sequence'])
            except Exception as exc:
                with self.guard:self.error=exc
                logging.exception('Publishing recovery checkpoint')

    def flush(self):
        with self.guard:worker=self.thread
        if worker and worker is not threading.current_thread():worker.join(timeout=8)
        with self.guard:
            if self.thread and self.thread.is_alive():raise TimeoutError('Recovery checkpoint is still being written')
            if self.error:raise OSError('Recovery checkpoint publication failed') from self.error


class Recovery:
    UI_KEYS=('playhead','zoom','selectedId','selectedAssetId','insTab','snap','useProxies','engine','resolution','source','undo','redo','history')
    def __init__(self,server,cache,event=lambda name,**data:None,ack=lambda epoch,sequence:None):
        self.server=server;self.event=event;self.guard=threading.RLock();self.phase='loading';self.closing=False
        self.journal=Journal(Path(cache)/'recovery-checkpoint.json',ack);old=self.journal.latest
        self.epoch=int(old.get('epoch',-1))+1 if old else 0;self.sequence=-1;self.saved={};self.restore=None
        self.disk_digest=self.digest();self.document=None;self.ui={};self.revision=0
        if old:
            if old.get('disk_digest')==self.disk_digest:
                try:
                    with server.LOCK:
                        if old.get('document') and old.get('revision',0)>old.get('saved_revision',-1):
                            server.save_state(server.validate_state(old['document']))
                            self.disk_digest=self.digest();self.event('startup_draft_restored')
                    self.restore=self.restore_ui(old.get('ui',{}));self.ui=deepcopy(self.restore)
                except (ValueError,TypeError,KeyError):
                    shutil.copy2(self.journal.path,self.journal.path.with_name('recovery-checkpoint-rejected-'+str(time.time_ns())+'.json'))
                    self.journal.warning='An invalid recovery draft was retained; the published project was opened.'
                    self.event('startup_draft_invalid')
            else:self.event('startup_checkpoint_stale')

    def digest(self):
        return hashlib.sha256(self.server.PROJECT.read_bytes()).hexdigest() if self.server.PROJECT.exists() else None

    def restore_ui(self,ui):
        result=deepcopy(ui);history=result.get('history')
        if history is not None:
            try:
                if history['encoding']=='gzip-base64':raw=gzip.decompress(base64.b64decode(history['data'],validate=True))
                elif history['encoding']=='json':raw=history['data']
                else:raise ValueError('Unsupported history encoding')
                parsed=json.loads(raw)
                if not isinstance(parsed,dict) or not all(isinstance(parsed.get(k),list) for k in ('undo','redo')):raise ValueError('Invalid history stacks')
            except Exception:
                shutil.copy2(self.journal.path,self.journal.path.with_name('recovery-history-invalid-'+str(time.time_ns())+'.json'))
                self.journal.warning='Invalid recovery history was retained; the project was restored without that history.'
                result.pop('history',None);self.event('recovery_history_invalid')
        return result

    def check_epoch(self,epoch):
        with self.guard:
            if int(epoch)!=self.epoch:raise ValueError('This editor view was replaced; an obsolete save was rejected')

    def checkpoint(self,data):
        with self.guard:
            if self.closing or int(data.get('epoch',-1))!=self.epoch:return False
            sequence=int(data.get('sequence',-1))
            if sequence<=self.sequence:return False
            ui=data.get('ui',{})
            if not isinstance(ui,dict):raise ValueError('Invalid recovery view')
            history=ui.get('history')
            if history is not None and (not isinstance(history,dict) or history.get('encoding') not in ('json','gzip-base64') or not isinstance(history.get('data'),str)):
                raise ValueError('Invalid recovery history encoding')
            document=data.get('document')
            if document is not None:
                if not isinstance(document,dict):raise ValueError('Invalid recovery draft')
                self.document={k:document[k] for k in ('name','tracks','output') if k in document}
                self.revision=int(data.get('revision',0))
            if 'history' in ui:
                self.ui.pop('undo',None);self.ui.pop('redo',None)
            elif 'undo' in ui or 'redo' in ui:self.ui.pop('history',None)
            selected={k:ui[k] for k in self.UI_KEYS if k in ui}
            if history is not None:selected['history']={k:history[k] for k in ('encoding','data')}
            self.ui.update(selected);self.sequence=sequence
            record={'epoch':self.epoch,'sequence':sequence,'revision':self.revision,'saved_revision':self.saved.get(self.epoch,-1),
                    'document':self.document,'ui':deepcopy(self.ui),'disk_digest':self.disk_digest}
            self.journal.submit(record)
            return True

    def note_saved(self,epoch,revision):
        with self.guard:
            self.saved[epoch]=max(int(revision),self.saved.get(epoch,-1));self.disk_digest=self.digest()
            if epoch==self.epoch and self.journal.latest and self.journal.latest['epoch']==epoch:
                record=dict(self.journal.latest,saved_revision=self.saved[epoch],disk_digest=self.disk_digest)
                self.journal.submit(record)

    def begin(self):
        with self.guard:
            if self.closing or self.phase in ('recovering','failed'):return None
            old=self.epoch;self.epoch+=1;self.phase='recovering';return old

    def preserve(self,old_epoch):
        self.journal.flush()
        with self.server.LOCK:
            with self.guard:
                record=self.journal.latest
                if record and record['epoch']==old_epoch:
                    saved=self.saved.get(old_epoch,record.get('saved_revision',-1))
                    if record.get('document') and record['revision']>saved:
                        self.server.save_state(self.server.validate_state(record['document']))
                        self.event('draft_restored',revision=record['revision'],saved_revision=saved)
                    self.restore=self.restore_ui(record.get('ui',{}))
                else:self.restore=self.restore_ui(self.ui)
                if self.restore.get('engine')=='native':self.restore['playhead']=max(0,self.server.NATIVE_PLAYBACK.clock_position/1e6)
                self.disk_digest=self.digest();self.sequence=-1;self.document=None;self.revision=0
                self.saved={k:v for k,v in self.saved.items() if k>=old_epoch};self.saved[self.epoch]=0

    def status(self):
        with self.guard:return {'epoch':self.epoch,'phase':self.phase,'restore':deepcopy(self.restore),'warning':self.journal.warning}

    def ready(self,epoch):
        self.check_epoch(epoch)
        with self.guard:self.phase='ready';self.restore=None
        self.event('view_ready',epoch=self.epoch)


class WindowsRecovery:
    """UI-thread hooks plus bounded recovery workers. No heartbeat/polling thread."""
    def __init__(self,window,server,cache,url):
        self.window=window;self.server=server;self.cache=Path(cache);self.url=url;self.started=time.perf_counter()
        self.log_guard=threading.Lock();self.control=None;self.handlers=[];self.token=0;self.allowed_navigation=0
        self.timer=None;self.worker=None;self.attempts=[];self.overlay=None;self.last_failure_browser=False
        self.initial_ready=threading.Event()
        self.model=Recovery(server,cache,self.event);self.model.phase='loading'

    def event(self,name,**data):
        # Whitelist event values at call sites: never URLs, project/source names or arbitrary messages.
        row={'utc':datetime.now(timezone.utc).isoformat(),'monotonic_seconds':round(time.perf_counter()-self.started,6),'event':name,**data}
        with self.log_guard:
            try:
                with (self.cache/'lifecycle.jsonl').open('a',encoding='utf8') as f:f.write(json.dumps(row)+'\n')
            except OSError:
                logging.exception('Writing local recovery diagnostics')

    def dispatch(self,callback):
        if self.model.closing:return
        from System import Action
        form=self.window.native
        def guarded():
            if not self.model.closing and not form.IsDisposed:callback()
        try:
            if not form.IsDisposed and not form.Disposing and form.IsHandleCreated:form.BeginInvoke(Action(guarded))
        except Exception:
            if not self.model.closing:raise

    def attach(self):
        if self.model.closing:return
        control=self.window.native.webview
        if self.control is not None and self.control.Equals(control):return
        self.detach();self.control=control;self.token+=1;token=self.token;core=control.CoreWebView2
        def bind(target,name,handler):
            getattr(target,name).__iadd__(handler);self.handlers.append((target,name,handler))
        def failed(sender,args):
            if token!=self.token:return
            kind=str(args.ProcessFailedKind)
            self.event('process_failed',kind=kind,reason=str(getattr(args,'Reason','unavailable')),exit_code=int(getattr(args,'ExitCode',0)))
            if kind in ('RenderProcessExited','BrowserProcessExited'):self.recover(kind=='BrowserProcessExited')
        def browser_exited(sender,args):
            if token!=self.token:return
            kind=str(args.BrowserProcessExitKind);self.event('browser_exited',kind=kind,closing=self.model.closing)
            if not self.model.closing and kind!='Normal':self.recover(True)
        def navigating(sender,args):
            if token!=self.token:return
            authorized=self.allowed_navigation>0
            if authorized:self.allowed_navigation-=1
            else:args.Cancel=True
            self.event('navigation_start',authorized=authorized,blocked=not authorized,navigation_id=int(args.NavigationId))
        def navigated(sender,args):
            self.event('navigation_completed',success=bool(args.IsSuccess),navigation_id=int(args.NavigationId),status=str(args.WebErrorStatus))
        bind(core,'ProcessFailed',failed);bind(core.Environment,'BrowserProcessExited',browser_exited)
        bind(core,'NavigationStarting',navigating);bind(core,'NavigationCompleted',navigated)
        self.event('controller_attached',token=token,runtime_version=str(core.Environment.BrowserVersionString))

    def detach(self):
        for target,name,handler in self.handlers:
            try:getattr(target,name).__isub__(handler)
            except Exception:pass
        self.handlers=[]

    def show(self,text,retry=False):
        from System.Windows.Forms import Panel,Label,Button,DockStyle
        from System.Drawing import Color,Point,Size
        if self.overlay is None:
            panel=Panel();panel.Dock=DockStyle.Fill;panel.BackColor=Color.FromArgb(17,25,36)
            label=Label();label.Location=Point(40,80);label.Size=Size(800,110);label.ForeColor=Color.White
            button=Button();button.Location=Point(40,210);button.Size=Size(220,44);button.Text='Retry editor';button.Click+=lambda s,e:self.recover(self.last_failure_browser,manual=True)
            panel.Controls.Add(label);panel.Controls.Add(button);self.window.native.Controls.Add(panel);self.overlay=(panel,label,button)
        panel,label,button=self.overlay;label.Text=text;button.Enabled=retry;panel.Visible=True;panel.BringToFront()

    def recover(self,browser=False,manual=False):
        if self.model.closing:return
        if manual and self.model.phase=='failed':self.model.phase='ready'
        old=self.model.begin()
        if old is None:return
        now=time.monotonic();self.attempts=[t for t in self.attempts if now-t<60];self.attempts.append(now)
        self.last_failure_browser=browser
        self.show('The editor view stopped. Local project and recovery checkpoints are retained. Recovering the view…')
        self.event('recovery_begin',browser=browser,old_epoch=old,epoch=self.model.epoch)
        def work():
            try:
                self.server.NATIVE_PLAYBACK.stop();self.server.PROGRAM_PREVIEW.cancel();self.model.preserve(old)
                if len(self.attempts)>3 and not manual:raise RuntimeError('Recovery attempt budget reached')
                def reload_view():
                    if self.model.closing:return
                    try:
                        self.allowed_navigation+=1
                        if browser:
                            from webview.platforms.edgechromium import EdgeChrome
                            self.detach();self.token+=1;old_control=self.control;self.control=None
                            self.window.native.Controls.Remove(old_control);old_control.Dispose();self.event('controller_disposed')
                            form=self.window.native;form.browser=EdgeChrome(form,self.window,str(self.cache/'webview'));form.webview=form.browser.webview
                            def initialized(sender,args):
                                if args.IsSuccess:self.attach()
                            form.webview.CoreWebView2InitializationCompleted+=initialized
                        else:self.control.CoreWebView2.Reload()
                        self.timer=threading.Timer(20,lambda:self.dispatch(self.timeout));self.timer.daemon=True;self.timer.start()
                    except Exception:self.timeout()
                self.dispatch(reload_view)
            except Exception:
                logging.exception('Recovering local editor view');self.dispatch(self.timeout)
        self.worker=threading.Thread(target=work,daemon=True);self.worker.start()

    def timeout(self):
        if self.model.closing or self.model.phase=='ready':return
        self.model.phase='failed';self.event('recovery_paused')
        self.show('The editor view could not recover. The project and recovery checkpoint are retained. Retry the view or close this window safely.',True)

    def ready(self,epoch):
        if self.model.closing:return
        self.model.ready(epoch)
        if self.timer:self.timer.cancel();self.timer=None
        self.dispatch(lambda:self.hide())
        self.initial_ready.set()

    def hide(self):
        if self.overlay:self.overlay[0].Visible=False

    def close(self):
        self.model.closing=True
        if self.timer:self.timer.cancel()
        try:self.journal_flush()
        except Exception:
            # A storage failure must not prevent the host's remaining worker cleanup.
            logging.exception('Draining recovery checkpoint during close')
            self.event('checkpoint_close_failed')
        finally:
            self.detach();self.event('host_close')

    def journal_flush(self):self.model.journal.flush()


class RecoveryBridge:
    def __init__(self):self._host=None
    def checkpoint(self,payload):
        if self._host is None:raise RuntimeError('Editor recovery is not initialized')
        data=json.loads(payload)
        if not isinstance(data,dict):raise ValueError('Invalid recovery checkpoint')
        accepted=self._host.model.checkpoint(data)
        if accepted:self._host.journal_flush()
        return {'epoch':data.get('epoch'),'sequence':data.get('sequence'),'durable':accepted}
