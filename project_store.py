"""Publish validated project revisions only after their bytes reach disk."""
import json
import os
import tempfile
from pathlib import Path


def backup_path(path):
    return path.with_name(path.name + '.bak')


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def load(path, validate):
    errors = []
    for candidate in (path, backup_path(path)):
        if not candidate.exists():
            continue
        try:
            state = validate(json.loads(candidate.read_bytes()))
            return state, candidate != path
        except (ValueError, KeyError, TypeError, OSError) as exc:
            errors.append(f'{candidate}: {exc}')
    if errors:
        raise ValueError('Unable to recover project. ' + ' | '.join(errors))
    return None, False


def save(path, state, validate):
    data = json.dumps(state, ensure_ascii=False, allow_nan=False, indent=2).encode('utf8')
    if path.exists():
        previous = path.read_bytes()
        try:
            previous_state=json.loads(previous)
            validate(previous_state)
        except (ValueError, KeyError, TypeError):
            # Preserve the last valid backup when repairing a damaged primary.
            pass
        else:
            if state.get('version')==4 and previous_state.get('version',0)<4:
                migration=path.with_name(path.name+'.v3.bak')
                if not migration.exists():atomic_write(migration,previous)
            atomic_write(backup_path(path), previous)
    atomic_write(path, data)
