"""Lossless stereo preview audio avoids fetching full video streams for audio tracks."""
import os
from pathlib import Path
import subprocess
import threading
import uuid

guard=threading.Lock()
processes=set()
stopped=threading.Event()


def build(asset,dest):
    if not asset.get('hasAudio') or dest.exists() or stopped.is_set():return
    dest.parent.mkdir(parents=True,exist_ok=True)
    temp=dest.with_name(dest.stem+'.'+uuid.uuid4().hex+'.partial.flac')
    cmd=['ffmpeg','-nostdin','-v','error','-i',asset['path'],'-map','0:a:0','-vn',
         '-af','aresample=48000:async=1:first_pts=0','-ac','2','-c:a','flac',
         '-sample_fmt','s16','-compression_level','2',str(temp)]
    try:
        with guard:
            if stopped.is_set():return
            process=subprocess.Popen(cmd,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                                     creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            processes.add(process)
        try:
            if process.wait()==0 and not stopped.is_set():os.replace(temp,dest)
        finally:
            with guard:processes.discard(process)
    finally:temp.unlink(missing_ok=True)


def cancel():
    with guard:
        stopped.set()
        for process in processes:
            if process.poll() is None:process.terminate()
