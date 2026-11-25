"""Windows desktop host. Each project window owns a distinct service and file lock."""
import argparse
import ctypes
import json
import logging
import msvcrt
import os
import subprocess
import sys
import threading
from copy import deepcopy
from http.server import ThreadingHTTPServer
from pathlib import Path

import webview
from webview.dom import DOMEventHandler

APP_DATA = Path(os.getenv('LOCALAPPDATA', Path.home())) / 'VlogCraft Studio'
BUNDLE = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))


def run(project):
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('VlogCraft.Studio')
    project = project.resolve()
    cache = project.parent / (project.name + '.data')
    cache.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=cache / 'studio.log', encoding='utf8', level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    lock_file = (cache / 'editor.lock').open('a+b')
    lock_file.seek(0)
    try:
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError as exc:
        raise RuntimeError('This project is already open in another window.') from exc

    os.environ['VLOGCRAFT_WORK'] = str(cache)
    os.environ['VLOGCRAFT_PROJECT'] = str(project)
    os.environ['PATH'] = str(BUNDLE / 'engine') + os.pathsep + os.environ['PATH']
    import server

    for folder in (server.MEDIA, server.THUMBS, server.PROXIES, server.REVIEWS, server.EXPORTS):
        folder.mkdir(parents=True, exist_ok=True)
    server.reconcile_export_jobs()
    # A window owns this cache exclusively. These are interrupted transfers.
    for part in server.MEDIA.glob('*.part'):
        if len(part.stem) == 32 and all(c in '0123456789abcdef' for c in part.stem):
            part.unlink(missing_ok=True)
    if not project.exists() and not server.RECOVERED:
        document=deepcopy(server.STATE)
        document['name']=project.stem
        server.save_state(document)
    http = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
    http.daemon_threads = True
    url = f'http://127.0.0.1:{http.server_port}/'
    from desktop_recovery import RecoveryBridge,WindowsRecovery
    recovery_bridge=RecoveryBridge()
    window = webview.create_window('VlogCraft Studio • ' + project.stem, url, width=1480,
                                   height=900, min_size=(960, 640), background_color='#111924',js_api=recovery_bridge)
    webview.settings['ALLOW_DOWNLOADS'] = True
    webview.settings['ALLOW_FILE_URLS'] = False

    def select_media():
        return window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=True,
                                         file_types=('Media (' + ';'.join('*' + x for x in sorted(server.SUPPORTED)) + ')',
                                                     'All files (*.*)')) or []

    def choose_export(suggested=''):
        folder, name = server.export_dialog_defaults(suggested)
        files = window.create_file_dialog(webview.FileDialog.SAVE, directory=str(folder),
                                          save_filename=name, file_types=('MP4 video (*.mp4)',))
        return files[0] if files else None

    server.EXPORT_PREFERENCES = APP_DATA / 'export-location.json'

    def project_action(action):
        if action == 'media':
            return {'paths': list(select_media())}
        if action not in ('new', 'open', 'save-as'):
            raise ValueError('Unknown project command')
        choosing = action == 'open'
        files = window.create_file_dialog(webview.FileDialog.OPEN if choosing else webview.FileDialog.SAVE,
                                          directory=str(project.parent), save_filename='' if choosing else 'Untitled.vlogcraft',
                                          file_types=('VlogCraft project (*.vlogcraft)', 'Studio 3 project (*.json)') if choosing
                                          else ('VlogCraft project (*.vlogcraft)',))
        if not files:
            return {'cancelled': True}
        destination = Path(files[0]).resolve()
        if destination == project:
            return {'current': True}
        if not choosing:
            if destination.suffix.lower() != '.vlogcraft':
                destination = destination.with_suffix('.vlogcraft')
            if destination.exists():
                raise ValueError('Choose a new project name to keep both revisions.')
            with server.LOCK:
                document = deepcopy(server.STATE) if action == 'save-as' else server.default_state()
            document['name'] = destination.stem
            with destination.open('xb') as handle:
                try:
                    handle.write(json.dumps(server.timing.encode(document), ensure_ascii=False).encode('utf8'))
                    handle.flush()
                    os.fsync(handle.fileno())
                except Exception:
                    handle.close()
                    destination.unlink(missing_ok=True)
                    raise
        cmd = [sys.executable]
        if not getattr(sys, 'frozen', False):
            cmd.append(str(Path(__file__).resolve()))
        subprocess.Popen([*cmd, '--project', str(destination)], creationflags=subprocess.CREATE_NO_WINDOW)
        return {'opened': str(destination)}

    server.choose_files = select_media
    server.choose_save_path = choose_export
    runtime = BUNDLE / 'engine/native'
    if all((runtime/name).is_file() for name in ('VlogCraftProject.exe','hdr-statistics.dll')):
        server.NATIVE_PROJECT_RUNTIME = runtime
        def choose_comparison_master():
            files=window.create_file_dialog(webview.FileDialog.OPEN,allow_multiple=False,
                                            file_types=('MP4 video (*.mp4)',))
            return files[0] if files else None
        server.CHOOSE_COMPARISON_MASTER = choose_comparison_master
    server.DESKTOP_ACTION = project_action
    import native_playback
    server.NATIVE_PLAYBACK=native_playback.Controller(window,cache,BUNDLE)
    import performance_profile
    server.PERFORMANCE_DIAGNOSTICS=performance_profile.Diagnostics(BUNDLE,cache)
    recovery=WindowsRecovery(window,server,cache,url);recovery_bridge._host=recovery;server.DESKTOP_RECOVERY=recovery

    def on_drop(event):
        files = event.get('dataTransfer', {}).get('files', [])
        if not files:
            return
        paths = [f.get('pywebviewFullPath') for f in files]
        if not all(paths):
            window.run_js("toast('Windows could not resolve this drop. Use Link files.',true)")
            return
        window.run_js('void importNative(' + json.dumps(paths) + ')')

    def on_loaded():
        if recovery.model.closing:return
        from System import Action
        try:
            window.native.Invoke(Action(recovery.attach))
            if recovery.model.closing:return
            window.dom.document.events.drop += DOMEventHandler(on_drop, prevent_default=True)
            if not recovery.model.closing:window.run_js("document.documentElement.classList.add('native-ready')")
        except Exception:
            if not recovery.model.closing:raise

    closing=threading.Lock()
    allow_close=threading.Event()

    def finish_close():
        try:
            # Do not finalize Python/.NET while pywebview is still creating its
            # DOM bridge and delivering startup callbacks. This wait is owned
            # by the close worker, never the Windows message thread.
            if recovery.model.phase=='loading' and not recovery.initial_ready.wait(20):
                logging.error('Editor initialization did not settle before close')
                recovery.dispatch(recovery.timeout)
                return
            if recovery.model.phase not in ('ready','loading'):
                recovery.model.preserve(recovery.model.epoch-1);pending=False
            else:pending = window.evaluate_js('typeof state !== "undefined" && !!state && modified > persisted')
            if pending:
                done = threading.Event()
                result = []
                def saved(value):
                    result.append(value)
                    done.set()
                window.evaluate_js('flushSave().then(()=>true,()=>false)', saved)
                if not done.wait(8) or result != [True]:
                    if not window.create_confirmation_dialog('Save failed', 'Close and discard unsaved changes?'):
                        return
            with server.JOB_LOCK:
                busy = any(job['status'] == 'rendering' for job in server.JOBS.values())
            if busy and not window.create_confirmation_dialog('Background work', 'Stop active jobs and close this project?'):
                return
            allow_close.set();recovery.model.closing=True
            window.destroy()
        except Exception:
            logging.exception('Closing project')
            if window.create_confirmation_dialog('Close project', 'The editor could not confirm its save. Close anyway?'):
                allow_close.set();recovery.model.closing=True
                window.destroy()
        finally:
            closing.release()

    def on_closing():
        recovery.event('window_close',accepted=allow_close.is_set())
        if allow_close.is_set():return True
        if closing.acquire(blocking=False):
            threading.Thread(target=finish_close,daemon=True).start()
        return False

    window.events.loaded += on_loaded
    window.events.closing += on_closing
    threading.Thread(target=http.serve_forever, daemon=True).start()
    try:
        webview.start(gui='edgechromium', private_mode=False, storage_path=str(cache / 'webview'),
                      icon=str(BUNDLE / 'web/branding/vlogcraft-approved.ico'))
    finally:
        import audio_cache
        recovery.close()
        def close_step(owner,action):
            recovery.event('cleanup_begin',owner=owner)
            try:action()
            except Exception as error:
                recovery.event('cleanup_failed',owner=owner,exception_type=type(error).__name__);raise
            recovery.event('cleanup_end',owner=owner)
        close_step('native',server.NATIVE_PLAYBACK.close)
        close_step('diagnostics',server.PERFORMANCE_DIAGNOSTICS.close)
        close_step('audio_cache',audio_cache.cancel)
        close_step('frame_index',server.FRAME_INDEX.close)
        close_step('hdr10plus_index',server.HDR10PLUS_INDEX.close)
        close_step('program_preview',server.PROGRAM_PREVIEW.close)
        with server.JOB_LOCK:
            server.PROXY_QUEUE.clear()
            for key, process in server.CURRENT_PROCESS.items():
                server.CANCEL[key].set()
                if process and process.poll() is None:
                    process.terminate()
        if server.NATIVE_EXPORT_THREAD:
            close_step('native_project_export',lambda:server.NATIVE_EXPORT_THREAD.join(timeout=10))
        close_step('http_listener',http.shutdown)
        close_step('http_connections',http.server_close)
        close_step('cache_workers',lambda:server.CACHE_WORKERS.shutdown(wait=True,cancel_futures=True))
        close_step('project_lock',lock_file.close)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', type=Path, default=APP_DATA / 'Projects' / 'My film.vlogcraft')
    try:
        run(parser.parse_args().project)
    except Exception as error:
        logging.exception('Studio startup')
        ctypes.windll.user32.MessageBoxW(0, str(error), 'VlogCraft Studio', 0x10)
        sys.exit(1)
