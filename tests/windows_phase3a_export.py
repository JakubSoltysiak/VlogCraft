"""Qualify packaged first export, cancellation and shutdown on the Radeon workload."""
import argparse
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import shutil
import sys
import time

import psutil

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/"benchmarks"),str(ROOT/"tests")]
from native_project_plan import compile_project
from native_project_render import compare_project
from hdr10plus_bitstream import conformance_issues,length_size,packet_records,sample_metadata
from hdr10plus_export import media
import project_store
import server
from windows_native_project_export import digest,wait_until_done
from windows_session import session


def wait_worker(process):
    deadline=time.monotonic()+40
    while time.monotonic()<deadline:
        for child in psutil.Process(process.pid).children(recursive=True):
            try:
                if child.name().lower()=="vlogcraftproject.exe":
                    return child.pid
            except psutil.NoSuchProcess:
                continue
        time.sleep(.05)
    raise TimeoutError("The project GPU worker did not start")


def close_with_confirmation(process):
    user=ctypes.WinDLL("user32")
    callback=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
    user.PostMessageW.argtypes=(wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM)
    user.GetWindowThreadProcessId.argtypes=(wintypes.HWND,ctypes.POINTER(wintypes.DWORD))
    user.GetWindowTextW.argtypes=(wintypes.HWND,wintypes.LPWSTR,ctypes.c_int)
    user.IsWindowVisible.argtypes=(wintypes.HWND,)
    family={process.pid,*[p.pid for p in psutil.Process(process.pid).children(recursive=True)]}

    def window(title):
        handles=[]
        @callback
        def capture(hwnd,_):
            owner=wintypes.DWORD()
            user.GetWindowThreadProcessId(hwnd,ctypes.byref(owner))
            if owner.value in family and user.IsWindowVisible(hwnd):
                name=ctypes.create_unicode_buffer(256)
                user.GetWindowTextW(hwnd,name,256)
                if name.value.startswith(title):
                    handles.append(hwnd)
            return True
        user.EnumWindows(capture,0)
        return handles[0] if len(handles)==1 else None

    host=window("VlogCraft Studio")
    if not host or not user.PostMessageW(host,0x0010,0,0):
        raise RuntimeError("The owned editor window is unavailable for the shutdown check")
    deadline=time.monotonic()+12
    while time.monotonic()<deadline:
        dialog=window("Background work")
        if dialog and user.PostMessageW(dialog,0x0111,1,0):  # WM_COMMAND / IDOK
            return
        time.sleep(.05)
    raise TimeoutError("The owned editor did not show its stop-active-jobs confirmation")


def qualify(executable,project,reference,results):
    results=results.resolve()
    results.mkdir(parents=True,exist_ok=False)
    local=results/"first-export.vlogcraft"
    shutil.copyfile(project,local)
    state,recovered=project_store.load(local,server.validate_document)
    assert state and not recovered
    originals={path:digest(path) for path in (local,*[Path(a["path"]) for a in state["assets"]])}
    delivered,cancelled,closed=(results/name for name in ("Pierwszy eksport.mp4","Cancelled.mp4","Closing.mp4"))
    timings={}
    with session(executable,results/"installed",offline=True,project_path=local) as (page,process,_,errors):
        page.click("#exportBtn")
        page.wait_for_function("!$('startRender').disabled")
        assert page.locator("#exportWorkflow").input_value()=="render"
        page.select_option("#exportWorkflow","hdr10plus-master")
        assert not page.locator("#useNativeProjectExport").is_checked()
        page.check("#useNativeProjectExport")
        page.select_option("#nativeProjectPolicy","first")
        assert page.locator("#nativeProjectComparison").is_hidden()
        assert page.locator("#nativeProjectFirstNote").is_visible()
        def start(path):
            page.wait_for_function("!$('startRender').disabled")
            page.fill("#exportPath",str(path))
            with page.expect_response(lambda response:response.url.endswith("/api/export")) as submitted:
                page.click("#startRender")
            assert submitted.value.ok,submitted.value.json()
            payload=submitted.value.request.post_data_json
            assert payload.get("experimentalFirstExport") is True and "comparisonMaster" not in payload
        began=time.perf_counter()
        start(delivered)
        status=wait_until_done(page)
        timings["first_export_to_terminal_job_seconds"]=time.perf_counter()-began
        assert status["status"]=="done" and status["deliveredBackend"]=="d3d11",status
        assert status["verificationPolicy"]=="first-export-sampled"
        start(cancelled)
        cancelled_worker=wait_worker(process)
        page.click("#cancelRender")
        assert wait_until_done(page)["status"]=="cancelled"
        assert not cancelled.exists() and not psutil.pid_exists(cancelled_worker)
        assert not errors,errors
        start(closed)
        shutdown_worker=wait_worker(process)
        page._vlogcraft_intentional_detach=True
        close_with_confirmation(process)
        process.wait(timeout=20)
        assert process.returncode==0 and not psutil.pid_exists(shutdown_worker)
    assert not closed.exists() and not list(results.glob(".vlogcraft_*"))
    program=compile_project(state,results)
    checks=compare_project(reference,delivered,program,results)
    assert checks["passed"],checks
    verified=set()
    width=length_size(media(delivered)[0])
    with packet_records(delivered,"v:0") as packets,delivered.open("rb") as stream:
        for packet in packets:
            pts=int(packet[b"pts"])
            assert pts not in verified
            block=sample_metadata(stream,int(packet[b"pos"]),int(packet[b"size"]),width)
            assert block is not None and not conformance_issues(block)
            verified.add(pts)
    assert sorted(verified)==[index*2000 for index in range(len(program.frames))]
    assert all(digest(path)==expected for path,expected in originals.items())
    receipt=json.loads((results/"installed/process-ownership.json").read_text("utf8"))
    assert receipt["job_members_at_cleanup"]==0 and receipt["new_visible_terminal_windows_after"]==0
    report=dict(offline_first_export=True,active_cancellation=True,active_confirmed_shutdown=True,
                exact_source_hashes=True,owned_survivors=0,new_terminal_windows=0,
                timings=timings,independent_full_comparison=checks,conforming_hdr10plus_blocks=len(verified))
    (results/"qualification.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf8")
    return report


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    for field in ("executable","project","reference","results"):
        parser.add_argument(field,type=Path)
    args=parser.parse_args()
    print(json.dumps(qualify(args.executable,args.project.resolve(),args.reference.resolve(),args.results)))
