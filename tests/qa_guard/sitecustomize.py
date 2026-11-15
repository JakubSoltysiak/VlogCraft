"""Explicit QA child-launch policy, composable with the existing offline guard."""
import os
from pathlib import Path
import runpy
import sys
if os.environ.get('VLOGCRAFT_QA_HIDDEN_CHILDREN')=='1':
    root=Path(__file__).resolve().parents[2]
    sys.path.insert(0,str(root))
    from benchmarks.owned_process import hide_console_children
    hide_console_children()
    if os.environ.get('VLOGCRAFT_OFFLINE_TEST')=='1':
        runpy.run_path(str(root/'tests/offline_guard/sitecustomize.py'))
