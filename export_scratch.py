"""Catalog and lease only scratch folders created by this editor."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import uuid

import psutil

REPARSE=getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0x400)
TOKEN=re.compile('[0-9a-f]{32}')
ARTIFACT=re.compile(
    r'(segment_\d{5,}(?:_video|_audio)?\.(?:mp4|mov|wav)|'
    r'(?:hdr_)?graph_segment_\d{5,}_video\.txt|graph_segment_\d{5,}_audio\.txt|'
    r'title_\d+\.txt|hdr-title-[0-9a-f]{64}\.png|alpha_\d+\.cmd|'
    r'grade_[0-9a-f]{24}\.cube|segoeui\.ttf|arial\.ttf|georgia\.ttf|concat\.txt|pictures\.bin|'
    r'fragments\.mp4|authored\.mp4|delivery\.partial\.mp4|master\.partial\.mp4|preserved\.mp4)')


def plain(path):
    info=path.lstat()
    return not path.is_symlink() and not getattr(info,'st_file_attributes',0)&REPARSE


@contextmanager
def lease(path):
    with path.open('a+b') as handle:
        if handle.tell()==0:
            handle.write(b'0')
            handle.flush()
        handle.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            yield False
            return
        try:
            yield True
        finally:
            handle.seek(0)
            if os.name=='nt':
                msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else:
                fcntl.flock(handle,fcntl.LOCK_UN)


def catalog(work):
    root=Path(work).resolve()/'export-ownership'
    root.mkdir(parents=True,exist_ok=True)
    if not plain(root):
        raise ValueError('The export scratch catalog must be a local VlogCraft folder')
    return root


def read_entry(entry):
    token=entry.stem
    if not TOKEN.fullmatch(token) or not plain(entry) or entry.stat().st_size>16384:
        return None
    record=json.loads(entry.read_bytes())
    parent=Path(record['parent'])
    path=parent/('.vlogcraft_'+token)
    if (not parent.is_absolute() or path.resolve()!=path or not plain(path) or
        path.resolve().parent!=parent or not path.is_dir()):
        return None
    marker=path/'.vlogcraft-owner'
    if not plain(marker) or marker.stat().st_size!=len(token) or marker.read_text('ascii')!=token:
        return None
    identity=path.stat()
    if [identity.st_dev,identity.st_ino]!=record['identity']:
        return None
    return path


@contextmanager
def create(work, destination):
    root=catalog(work)
    token=uuid.uuid4().hex
    parent=Path(destination).parent.resolve(strict=True)
    scratch=parent/('.vlogcraft_'+token)
    entry=root/(token+'.json')
    lock=root/(token+'.lock')
    scratch.mkdir()
    try:
        with lease(lock) as owned:
            if not owned:raise RuntimeError('Could not lease export scratch')
            (scratch/'.vlogcraft-owner').write_text(token,encoding='ascii')
            info=scratch.stat()
            with tempfile.NamedTemporaryFile(dir=root,delete=False) as pending:
                pending.write(json.dumps({'parent':str(parent),'identity':[info.st_dev,info.st_ino]}).encode())
            Path(pending.name).replace(entry)
            try:
                yield scratch
            finally:
                # Use the same recorded identity for normal shutdown, including
                # cancellation. Files inserted or linked into scratch are retained.
                try:
                    if read_entry(entry)==scratch and owned_files(scratch):
                        shutil.rmtree(scratch)
                except OSError:
                    # A file held by a process can be reviewed from Storage later.
                    pass
                finally:
                    if not scratch.exists():entry.unlink(missing_ok=True)
    finally:
        if not entry.exists():lock.unlink(missing_ok=True)


def owned_files(folder):
    return all(p.is_file() and plain(p) and p.stat().st_nlink==1 and
               (p.name=='.vlogcraft-owner' or ARTIFACT.fullmatch(p.name))
               for p in folder.iterdir())


def media_worker_uses(folder):
    for process in psutil.process_iter(['name']):
        if (process.info['name'] or '').lower() not in ('ffmpeg','ffmpeg.exe','ffprobe','ffprobe.exe'):
            continue
        try:
            cwd=Path(process.cwd()).resolve()
            command=process.cmdline()
            if cwd.is_relative_to(folder) or any(str(folder).casefold() in part.casefold() for part in command):
                return True
        except (psutil.NoSuchProcess,psutil.ZombieProcess):
            continue
        except psutil.AccessDenied:
            return True
    return False


def usage(work):
    total=0
    for entry in catalog(work).glob('*.json'):
        try:
            folder=read_entry(entry)
            if folder:total+=sum(p.stat().st_size for p in folder.iterdir() if p.is_file() and plain(p))
        except (OSError,ValueError,KeyError,TypeError):
            continue
    return total


def clear(work, required):
    protected=[Path(path).resolve() for path in required]
    count=0
    for entry in catalog(work).glob('*.json'):
        try:
            folder=read_entry(entry)
            lock=entry.with_suffix('.lock')
            if not folder or not lock.is_file() or not plain(lock):
                continue
            with lease(lock) as owned:
                if (not owned or read_entry(entry)!=folder or not owned_files(folder)
                    or any(path.is_relative_to(folder) for path in protected) or media_worker_uses(folder)):
                    continue
                shutil.rmtree(folder)
                entry.unlink()
                count+=1
            lock.unlink(missing_ok=True)
        except (OSError,ValueError,KeyError,TypeError):
            continue
    return count
