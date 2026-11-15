"""Own one isolated native project/window for automated Windows measurements."""
from contextlib import contextmanager
import ctypes,os,socket,subprocess,tempfile,time,urllib.request,json,shutil
from pathlib import Path
import psutil
from datetime import datetime,timezone
from playwright.sync_api import sync_playwright
from owned_process import ProcessScope
from graphics_diagnostics import graphics_diagnostics
ROOT=Path(__file__).resolve().parents[1]

@contextmanager
def session(executable,results,*,offline=False,project_path=None,entrypoint=None,legacy_viewport=False,legacy_focus_emulation=False):
    results=results.resolve();results.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='lab-',dir=results,ignore_cleanup_errors=True) as folder:
        project=Path(project_path).resolve() if project_path else Path(folder)/'architecture-lab.vlogcraft'
        if project_path:assert project.is_relative_to(results.parent),'Persistent test project must remain inside the owned results tree'
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        env=dict(os.environ,WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=f'--remote-debugging-port={port}')
        if offline:env['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS']+=' --proxy-server=http://127.0.0.1:9 --proxy-bypass-list="127.0.0.1;localhost"'
        cmd=[str(executable.resolve())]
        if executable.stem.lower() in ('python','pythonw'):cmd.append(str(entrypoint or ROOT/'desktop.py'))
        launch_started=time.perf_counter()
        with (results/'host.log').open('w',encoding='utf8') as log,ProcessScope() as ownership:
            process=ownership.launch([*cmd,'--project',str(project)],env=env,stdout=log,stderr=log)
            page=None;observations=[];cleanup_started=False;automation_finished=False;observer_state=None;test_failure=None
            def observe(event):
                present=[]
                try:family={process.pid,*[p.pid for p in psutil.Process(process.pid).children(recursive=True)]}
                except psutil.Error:family={process.pid}
                def visible(hwnd,_):
                    pid=ctypes.c_ulong();ctypes.windll.user32.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
                    if pid.value in family and ctypes.windll.user32.IsWindowVisible(hwnd):present.append(True)
                    return True
                callback=ctypes.WINFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)(visible);ctypes.windll.user32.EnumWindows(callback,0)
                observations.append({'event':event,'utc':datetime.now(timezone.utc).isoformat(),'owned_window_present':bool(present),'since_launch_seconds':round(time.perf_counter()-launch_started,6),
                                     'during_cleanup':cleanup_started,'automation_finished':automation_finished,'intentional_detach':getattr(page,'_vlogcraft_intentional_detach',False),'host_returncode':process.poll()})
            try:
                deadline=time.monotonic()+50
                while time.monotonic()<deadline:
                    try:
                        with urllib.request.urlopen(f'http://127.0.0.1:{port}/json/list',timeout=1) as r:
                            if any(x['url'].startswith('http://127.0.0.1:') for x in json.load(r)):break
                    except OSError:pass
                    if process.poll() is not None:raise RuntimeError('Native app exited during launch')
                    time.sleep(.1)
                with sync_playwright() as pw:
                    browser=pw.chromium.connect_over_cdp(f'http://127.0.0.1:{port}',no_defaults=not legacy_focus_emulation)
                    browser.on('disconnected',lambda:observe('cdp_disconnected'))
                    context=browser.contexts[0]
                    context.on('close',lambda:observe('context_closed'))
                    # The HTTP target list may lead Playwright's target-attached event.
                    deadline=time.monotonic()+40
                    observer=browser.new_browser_cdp_session()
                    while time.monotonic()<deadline:
                        page=next((p for p in context.pages if p.url.startswith('http://127.0.0.1:')),None)
                        if page is not None:break
                        observer.send('Target.getTargets');time.sleep(.05)
                    observer.detach()
                    if page is None:raise RuntimeError('Editor page was not enumerated')
                    page._vlogcraft_cdp_endpoint=f'http://127.0.0.1:{port}'
                    page._vlogcraft_intentional_detach=False
                    page.on('close',lambda:observe('page_closed'))
                    page.on('crash',lambda:observe('page_crashed'))
                    page.on('domcontentloaded',lambda:observe('document_loaded'))
                    page.set_default_timeout(120000)
                    page.wait_for_function("typeof state !== 'undefined' && state?.desktop && document.documentElement.classList.contains('native-ready')")
                    (results/'webview-graphics.json').write_text(json.dumps(graphics_diagnostics(browser),indent=2),encoding='utf8')
                    page._vlogcraft_launch_seconds=time.perf_counter()-launch_started
                    if legacy_viewport:page.set_viewport_size({'width':1440,'height':850})
                    else:
                        geometry=page.context.new_cdp_session(page)
                        geometry.send('Emulation.clearDeviceMetricsOverride');geometry.detach()
                    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                    if page.evaluate("typeof recoveryInitialize==='function'"):
                        page.wait_for_function('recoveryAckSequence>=0&&recoveryFlight===null',timeout=45000)
                    visible_token=None
                    if os.environ.get('VLOGCRAFT_QA_KEEP_VISIBLE')=='1':
                        from window_visibility import keep_visible
                        visible_token=keep_visible(process)
                    try:
                        yield page,process,project,errors
                        if not page._vlogcraft_intentional_detach:page.evaluate('flushSave()')
                    except BaseException as exc:
                        test_failure=type(exc).__name__
                        # A failed owned fixture must not strand a close-confirmation dialog.
                        try:
                            origin=page.url.split('/api/')[0].rstrip('/')
                            with urllib.request.urlopen(origin+'/api/jobs',timeout=2) as response:jobs=json.load(response)
                            (results/'jobs-at-failure.json').write_text(json.dumps(jobs,indent=2),encoding='utf8')
                            for kind,job in jobs.items():
                                if isinstance(job,dict) and job.get('status')=='rendering':
                                    request=urllib.request.Request(origin+'/api/job/cancel',data=json.dumps({'job':kind}).encode(),headers={'Content-Type':'application/json'})
                                    urllib.request.urlopen(request,timeout=2).close()
                        except Exception:pass
                        raise
                    finally:
                        if visible_token:
                            from window_visibility import restore_window
                            restore_window(visible_token)
                        observer_state={'page_closed_before_observer_stop':page.is_closed(),'host_returncode_before_observer_stop':process.poll()}
                        automation_finished=True
            except BaseException as exc:
                test_failure=type(exc).__name__
                raise
            finally:
                cleanup_started=True
                cleanup_state={'app_alive_before_cleanup':process.poll() is None,'returncode_before_cleanup':process.poll(),
                               'page_closed_before_cleanup':page.is_closed() if page is not None else None}
                try:family={process.pid,*[p.pid for p in psutil.Process(process.pid).children(recursive=True)]}
                except psutil.Error:family={process.pid}
                def close(hwnd,_):
                    pid=ctypes.c_ulong();ctypes.windll.user32.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
                    title=ctypes.create_unicode_buffer(256);ctypes.windll.user32.GetWindowTextW(hwnd,title,256)
                    if pid.value in family and title.value=='VlogCraft Studio • '+project.stem:ctypes.windll.user32.PostMessageW(hwnd,0x10,0,0)
                    return True
                callback=ctypes.WINFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)(close);ctypes.windll.user32.EnumWindows(callback,0)
                cache=project.parent/(project.name+'.data')
                def retain():
                    for source,name in ((cache/'studio.log','application.log'),(cache/'lifecycle.jsonl','lifecycle.jsonl'),
                                        (cache/'native-preview/native-errors.log','native-process.log'),(cache/'recovery-checkpoint.json','recovery-checkpoint-local.json'),(project,'project-local.json')):
                        if source.is_file():shutil.copy2(source,results/name)
                retain();close_error=None
                try:process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    ownership.close();process.wait(timeout=5);close_error=RuntimeError('Native benchmark host failed to close normally')
                cleanup_state['final_returncode']=process.returncode
                cleanup_state['observer_events']=observations
                cleanup_state['observer_state']=observer_state
                (results/'session-lifecycle.json').write_text(json.dumps(cleanup_state,indent=2),encoding='utf8')
                cleanup_state['test_failure']=test_failure;cleanup_state['forced_cleanup']=close_error is not None
                (results/'session-lifecycle.json').write_text(json.dumps(cleanup_state,indent=2),encoding='utf8')
                retain()
                deadline=time.monotonic()+3
                while not ownership.closed and ownership.members() and time.monotonic()<deadline:time.sleep(.05)
                release=ownership.close()
                (results/'process-ownership.json').write_text(json.dumps(release,indent=2),encoding='utf8')
                if release['job_members_at_cleanup'] and test_failure is None and close_error is None:
                    raise RuntimeError('Application descendants required forced job cleanup; retained as a failed release test')
                if close_error is not None and test_failure is None:raise close_error
                if process.returncode and test_failure is None:raise RuntimeError('Native benchmark host exit '+str(process.returncode))
