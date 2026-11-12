import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np
import audio_cache
import project_store
import server


class CacheRecoveryTests(unittest.TestCase):
    def test_audio_cache_decodes_matching_samples_and_cleans_interrupted_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source.wav';cached=root/'cache.flac'
            subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','sine=f=710:r=48000:d=0.4','-ac','2',str(source)],check=True,capture_output=True)
            a=dict(path=str(source),hasAudio=True)
            audio_cache.build(a,cached)
            def decode(path):
                return subprocess.check_output(['ffmpeg','-v','error','-i',str(path),'-f','s16le','-'])
            self.assertEqual(decode(source),decode(cached))
            self.assertFalse(list(root.glob('*.partial.flac')))

    def test_first_rational_save_keeps_permanent_previous_format_copy(self):
        import timing
        with tempfile.TemporaryDirectory() as folder:
            project=Path(folder)/'old.vlogcraft'
            old=server.default_state()
            project_store.save(project,old,server.validate_document)
            preserved=project.read_bytes()
            current=timing.encode(old)
            project_store.save(project,current,server.validate_document)
            current['name']='Next edit'
            project_store.save(project,current,server.validate_document)
            self.assertEqual(project.with_name(project.name+'.v3.bak').read_bytes(),preserved)

    def test_actual_process_death_before_replace_retains_valid_primary(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);project=root/'crash.vlogcraft'
            state=server.default_state();state['name']='Before crash'
            project_store.save(project,state,server.validate_document)
            script="""import os,sys,pathlib,project_store
path=pathlib.Path(sys.argv[1])
def crash(src,dest):
 if pathlib.Path(dest)==path:os._exit(73)
 return original(src,dest)
original=project_store.os.replace
project_store.os.replace=crash
project_store.save(path,{'name':'Unpublished'},lambda s:s)
"""
            result=subprocess.run([sys.executable,'-c',script,str(project)],capture_output=True)
            self.assertEqual(result.returncode,73)
            actual,recovered=project_store.load(project,server.validate_document)
            self.assertEqual(actual['name'],'Before crash');self.assertFalse(recovered)
