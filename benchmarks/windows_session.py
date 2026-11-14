"""Own one isolated native project/window for automated Windows measurements."""
from contextlib import contextmanager
import ctypes,os,socket,subprocess,tempfile,time,urllib.request,json,shutil
from pathlib import Path
import psutil
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]

@contextmanager
def session(executable,results,*,offline=False):
    results=results.resolve();results.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='lab-',dir=results,ignore_cleanup_errors=True) as folder:
        project=Path(folder)/'architecture-lab.vlogcraft'
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        env=dict(os.environ,WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=f'--remote-debugging-port={port}')
        if offline:env['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS']+=' --proxy-server=http://127.0.0.1:9 --proxy-bypass-list="127.0.0.1;localhost"'
        cmd=[str(executable.resolve())]
        if executable.stem.lower() in ('python','pythonw'):cmd.append(str(ROOT/'desktop.py'))
        launch_started=time.perf_counter()
        with (results/'host.log').open('w',encoding='utf8') as log:
            process=subprocess.Popen([*cmd,'--project',str(project)],env=env,stdout=log,stderr=log)
            page=None;observations=[];cleanup_started=False;automation_finished=False;observer_state=None
            def observe(event):
                observations.append({'event':event,'since_launch_seconds':round(time.perf_counter()-launch_started,6),
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
                    browser=pw.chromium.connect_over_cdp(f'http://127.0.0.1:{port}')
                    browser.on('disconnected',lambda:observe('cdp_disconnected'))
                    context=browser.contexts[0]
                    context.on('close',lambda:observe('context_closed'))
                    page=next(p for p in context.pages if p.url.startswith('http://127.0.0.1:'))
                    page._vlogcraft_cdp_endpoint=f'http://127.0.0.1:{port}'
                    page._vlogcraft_intentional_detach=False
                    page.on('close',lambda:observe('page_closed'))
                    page.on('crash',lambda:observe('page_crashed'))
                    page.set_default_timeout(120000)
                    page.wait_for_function("state?.desktop && document.documentElement.classList.contains('native-ready')")
                    page._vlogcraft_launch_seconds=time.perf_counter()-launch_started
                    page.set_viewport_size({'width':1440,'height':850})
                    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                    try:
                        yield page,process,project,errors
                        if not page._vlogcraft_intentional_detach:page.evaluate('flushSave()')
                    finally:
                        observer_state={'page_closed_before_observer_stop':page.is_closed(),'host_returncode_before_observer_stop':process.poll()}
                        automation_finished=True
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
                try:process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    for child in psutil.Process(process.pid).children(recursive=True):
                        try:child.terminate()
                        except psutil.Error:pass
                    process.terminate();process.wait();raise RuntimeError('Native benchmark host failed to close normally')
                cleanup_state['final_returncode']=process.returncode
                cleanup_state['observer_events']=observations
                cleanup_state['observer_state']=observer_state
                (results/'session-lifecycle.json').write_text(json.dumps(cleanup_state,indent=2),encoding='utf8')
                cache=project.parent/(project.name+'.data')
                for source,name in ((cache/'studio.log','application.log'),(cache/'native-preview/native-errors.log','native-process.log')):
                    if source.is_file():shutil.copy2(source,results/name)
                if process.returncode:raise RuntimeError('Native benchmark host exit '+str(process.returncode))
