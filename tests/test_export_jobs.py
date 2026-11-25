import hashlib
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import psutil

import export_jobs
import server


class ExportJobRecoveryTests(unittest.TestCase):
    def setUp(self):
        work = tempfile.TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.work = Path(work.name)
        self.status = dict(status='rendering', percent=0, frames=0, path=None, error=None,
                           stage='preparing', message='Preparing export')
        self.snapshot = {'assets': [{'path': 'original.mp4'}], 'output': {'fps': 60}}

    def start(self):
        return export_jobs.start(self.work, self.snapshot, self.work / 'film.mp4', {}, self.status)

    def folder(self, record):
        return self.work / 'export-jobs' / record['job_id']

    def test_abrupt_exit_restores_progress_and_preserves_every_related_file(self):
        original = self.work / 'original.mp4'
        original.write_bytes(b'original')
        destination = self.work / 'film.mp4'
        destination.write_bytes(b'existing master')
        script = '''
import json, os, sys
from pathlib import Path
import export_jobs, export_scratch
work = Path(sys.argv[1])
record = export_jobs.start(work, json.loads(sys.argv[2]), work / 'film.mp4', {}, json.loads(sys.argv[3]))
owner = export_scratch.create(work, work / 'film.mp4')
scratch = owner.__enter__()
(scratch / 'segment_00001.mp4').write_bytes(b'completed segment')
(scratch / 'delivery.partial.mp4').write_bytes(b'incomplete mux')
export_jobs.write(work, record, dict(record['status'], percent=4, frames=3489, stage='video'))
print(json.dumps([record, str(scratch)]), flush=True)
os._exit(30)
'''
        child = subprocess.run([sys.executable, '-c', script, str(self.work), json.dumps(self.snapshot),
                                json.dumps(self.status)], capture_output=True, text=True, timeout=15,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.assertEqual(child.returncode, 30, child.stderr)
        record, scratch = json.loads(child.stdout)
        folder = self.folder(record)
        project = folder / 'project.json'
        snapshot = project.read_bytes()
        self.assertEqual(json.loads(snapshot), self.snapshot)
        self.assertEqual(hashlib.sha256(snapshot).hexdigest(), record['snapshot_sha256'])
        idle = dict(status='idle', percent=0, message='', path=None, error=None)
        with patch.object(server, 'WORK', self.work), patch.dict(server.JOBS, export=idle):
            server.reconcile_export_jobs()
            status = server.JOBS['export']
            self.assertEqual((status['status'], status['frames'], status['percent'], status['stage']),
                             ('interrupted', 3489, 4, 'video'))
            self.assertIsNone(status['path'])
            self.assertIsNone(status['error'])
        receipt = folder / 'status.json'
        reconciled = receipt.read_bytes()
        self.assertEqual(json.loads(reconciled)['status'], status)
        self.assertEqual(export_jobs.reconcile(self.work), status)
        self.assertEqual(receipt.read_bytes(), reconciled)
        for path, expected in ((original, b'original'), (destination, b'existing master'), (project, snapshot),
                               (Path(scratch) / 'segment_00001.mp4', b'completed segment'),
                               (Path(scratch) / 'delivery.partial.mp4', b'incomplete mux')):
            self.assertEqual(path.read_bytes(), expected)

    def test_live_owner_and_inaccessible_owner_stay_running(self):
        record = self.start()
        receipt = self.folder(record) / 'status.json'
        before = receipt.read_bytes()
        self.assertIs(export_jobs._owner_exited(record['owner']), False)
        self.assertEqual(export_jobs.reconcile(self.work), self.status)
        with patch.object(export_jobs.psutil, 'Process', side_effect=psutil.AccessDenied(os.getpid())):
            self.assertIsNone(export_jobs._owner_exited(record['owner']))
            self.assertEqual(export_jobs.reconcile(self.work), self.status)
        self.assertEqual(receipt.read_bytes(), before)

    def test_reused_pid_interrupts_only_the_running_job(self):
        completed = self.start()
        terminal = dict(self.status, status='done', percent=100, path='film.mp4')
        export_jobs.write(self.work, completed, terminal)
        active = self.start()
        with patch.object(export_jobs.psutil, 'Process') as process:
            process.return_value.create_time.return_value = active['owner']['created'] + 1
            export_jobs.reconcile(self.work)
        self.assertEqual(json.loads((self.folder(completed) / 'status.json').read_bytes())['status'], terminal)
        status = json.loads((self.folder(active) / 'status.json').read_bytes())['status']
        self.assertEqual(status['status'], 'interrupted')

    def test_terminal_publish_between_first_read_and_owner_exit_survives_reconciliation(self):
        record = self.start()
        receipt = self.folder(record) / 'status.json'
        terminal = dict(self.status, status='done', percent=100, path='film.mp4')

        def exit_after_publish(pid):
            export_jobs.write(self.work, record, terminal)
            raise psutil.NoSuchProcess(pid)

        with patch.object(export_jobs.psutil, 'Process', side_effect=exit_after_publish):
            self.assertEqual(export_jobs.reconcile(self.work), terminal)
        self.assertEqual(json.loads(receipt.read_bytes())['status'], terminal)

    def test_invalid_receipt_bytes_are_preserved(self):
        record = self.start()
        receipt = self.folder(record) / 'status.json'
        receipt.write_bytes(b'{"unreadable":')
        with self.assertLogs(level='ERROR'):
            self.assertIsNone(export_jobs.reconcile(self.work))
        self.assertEqual(receipt.read_bytes(), b'{"unreadable":')

    def test_progress_writes_are_throttled_and_terminal_status_is_flushed(self):
        record = self.start()
        job = dict(self.status, _started=100, _last_receipt=100, _receipt=record)
        receipt = self.folder(record) / 'status.json'
        with patch.object(server, 'WORK', self.work), patch.dict(server.JOBS, export=job):
            with patch.object(server.time, 'monotonic', return_value=101):
                server.job_status('export', frames=20)
            self.assertEqual(json.loads(receipt.read_bytes())['status']['frames'], 0)
            with patch.object(server.time, 'monotonic', return_value=106):
                server.job_status('export', frames=50)
            self.assertEqual(json.loads(receipt.read_bytes())['status']['frames'], 50)
            with patch.object(server.time, 'monotonic', return_value=107):
                server.job_status('export', status='cancelled', _finished=107)
        status = json.loads(receipt.read_bytes())['status']
        self.assertEqual((status['status'], status['elapsedSeconds']), ('cancelled', 7))
        self.assertTrue(all(not key.startswith('_') for key in status))

    def test_http_export_publishes_frozen_snapshot_before_launching_worker(self):
        state = server.default_state()
        state['tracks'][0]['clips'].append(server.default_title(0))
        received = []
        finished = threading.Event()

        def worker(snapshot, *_args):
            folder, = (self.work / 'export-jobs').iterdir()
            received.append((snapshot, json.loads((folder / 'project.json').read_bytes()),
                             json.loads((folder / 'status.json').read_bytes())))
            server.job_status('export', status='cancelled')
            finished.set()

        destination = self.work / 'film.mp4'
        with (patch.object(server, 'WORK', self.work), patch.object(server, 'STATE', state),
              patch.object(server, 'EXPORT_PREFERENCES', self.work / 'export-location.json'),
              patch.object(server, 'run_export', worker), patch.dict(server.JOBS, export={'status': 'idle'}),
              ThreadingHTTPServer(('127.0.0.1', 0), server.Handler) as http):
            thread = threading.Thread(target=http.serve_forever, daemon=True)
            thread.start()
            client = HTTPConnection('127.0.0.1', http.server_port, timeout=5)
            try:
                client.request('POST', '/api/export', json.dumps({'path': str(destination)}))
                response = client.getresponse()
                body = json.loads(response.read())
                self.assertEqual(response.status, 200, body)
                self.assertTrue(body['started'])
                self.assertTrue(finished.wait(5))
            finally:
                client.close()
                http.shutdown()
                thread.join()
        snapshot, frozen, receipt = received[0]
        self.assertEqual(snapshot, frozen)
        self.assertEqual(frozen, state)
        self.assertEqual(receipt['destination'], str(destination.resolve()))
        self.assertEqual(receipt['status']['status'], 'rendering')
        self.assertFalse(destination.exists())

    def test_worker_launch_failure_flushes_a_terminal_receipt(self):
        state = server.default_state()
        state['tracks'][0]['clips'].append(server.default_title(0))
        handler = server.Handler.__new__(server.Handler)
        handler.path = '/api/export'
        handler.check_origin = lambda: True
        handler.read_json = lambda: {'path': str(self.work / 'film.mp4')}
        handler.json_response = Mock()
        worker = SimpleNamespace(start=Mock(side_effect=RuntimeError('injected launch failure')))
        with (patch.object(server, 'WORK', self.work), patch.object(server, 'STATE', state),
              patch.object(server, 'threading', SimpleNamespace(Thread=Mock(return_value=worker))),
              patch.dict(server.JOBS, export={'status': 'idle'})):
            handler.do_POST()
            self.assertEqual(server.JOBS['export']['status'], 'error')
        handler.json_response.assert_called_once_with({'error': 'injected launch failure'}, 400)
        folder, = (self.work / 'export-jobs').iterdir()
        status = json.loads((folder / 'status.json').read_bytes())['status']
        self.assertEqual(status['status'], 'error')
        self.assertEqual(status['message'], 'Could not start the export worker')
