"""Durable local export receipts. Recovery updates status metadata only."""
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import uuid

import psutil

from export_scratch import TOKEN, lease, plain
from project_store import atomic_write


def _utc():
    return datetime.now(timezone.utc).isoformat()


def _json_bytes(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf8')


def _catalog(work):
    root = Path(work) / 'export-jobs'
    try:
        if not plain(root) or not root.is_dir():
            raise ValueError('The export job catalog must be a local VlogCraft folder')
    except FileNotFoundError:
        return None
    return root


def start(work, snapshot, destination, options, status):
    root = Path(work) / 'export-jobs'
    root.mkdir(parents=True, exist_ok=True)
    root = _catalog(work)
    job_id = uuid.uuid4().hex
    folder = root / job_id
    folder.mkdir()
    owner = psutil.Process(os.getpid())
    started = _utc()
    frozen = _json_bytes(snapshot)
    record = {
        'schema_version': 1,
        'job_id': job_id,
        'owner': {'pid': owner.pid, 'created': owner.create_time()},
        'started_utc': started,
        'updated_utc': started,
        'snapshot_sha256': hashlib.sha256(frozen).hexdigest(),
        'destination': str(destination),
        'options': options,
        'status': status,
    }
    atomic_write(folder / 'project.json', frozen)
    atomic_write(folder / 'status.json', _json_bytes(record))
    return record


def write(work, record, status):
    updated = dict(record, status=status, updated_utc=_utc())
    atomic_write(Path(work) / 'export-jobs' / record['job_id'] / 'status.json', _json_bytes(updated))


def _owner_exited(owner):
    pid, created = owner['pid'], owner['created']
    if type(pid) is not int or pid < 1 or type(created) not in (int, float) or not created > 0:
        raise ValueError('Invalid export owner identity')
    try:
        process = psutil.Process(pid)
        return process.create_time() != created or process.status() == psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return True
    except psutil.Error:
        return None


def _read_record(path, job_id):
    if not plain(path) or not path.is_file() or path.stat().st_size > 65536:
        return None
    record = json.loads(path.read_bytes())
    if record['schema_version'] != 1 or record['job_id'] != job_id:
        return None
    return record


def reconcile(work):
    """Record proven owner exits and return the most recent job status, if any."""
    root = _catalog(work)
    if root is None:
        return None
    lock = root / '.reconcile.lock'
    try:
        if not plain(lock) or not lock.is_file() or lock.stat().st_nlink != 1:
            raise ValueError('The export reconciliation lock must be a regular file')
    except FileNotFoundError:
        pass
    latest = None
    with lease(lock) as owned:
        if not owned:
            return None
        for folder in root.iterdir():
            try:
                if not TOKEN.fullmatch(folder.name) or not plain(folder) or not folder.is_dir():
                    continue
                path = folder / 'status.json'
                record = _read_record(path, folder.name)
                if record is None:
                    continue
                started = datetime.fromisoformat(record['started_utc'])
                if started.tzinfo is None:
                    continue
                status = record['status']
                if status['status'] == 'rendering' and _owner_exited(record['owner']) is True:
                    # The owner could publish its terminal state immediately before exit.
                    final = _read_record(path, folder.name)
                    if final is None or final['owner'] != record['owner']:
                        continue
                    status = final['status']
                    if status['status'] == 'rendering':
                        status = dict(status, status='interrupted', path=None, error=None,
                                      message='The previous export was interrupted. Last recorded progress is shown below.')
                        try:
                            write(work, final, status)
                        except OSError:
                            logging.exception('Saving an interrupted export receipt')
                if latest is None or started > latest[0]:
                    latest = (started, status)
            except FileNotFoundError:
                continue
            except (OSError, ValueError, KeyError, TypeError):
                logging.exception('Reading or reconciling a local export receipt')
    return latest[1] if latest else None
