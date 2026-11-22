"""Qualify the optional GPU export from the installed Windows editor, offline."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT),str(ROOT/"benchmarks"),str(ROOT/"tests")]

from native_project_render import compare_project
from native_project_plan import compile_project
import project_store
import server
from windows_session import session


def digest(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file,"sha256").digest()


def wait_until_done(page,timeout=180):
    deadline = time.monotonic()+timeout
    while time.monotonic()<deadline:
        job = page.evaluate("request('jobs')")["export"]
        if job["status"] in ("done","cancelled","error"):
            return job
        time.sleep(.15)
    raise TimeoutError("Installed GPU export did not reach a terminal state")


def qualify(executable,project,reference,results):
    results=results.resolve()
    results.mkdir(parents=True,exist_ok=False)
    local=results/"qualification.vlogcraft"
    shutil.copyfile(project,local)
    state,recovered=project_store.load(local,server.validate_document)
    assert not recovered
    protected = [local,reference,*[Path(asset["path"]) for asset in state["assets"]]]
    before = {path:digest(path) for path in protected}
    delivered = results/"Projekt próbny.mp4"
    cancelled = results/"Anulowany.mp4"
    program = compile_project(state,results)
    with session(executable,results/"installed",offline=True,project_path=local) as (page,proc,_,errors):
        assert page.evaluate("request('export/native-project')")["available"]
        page.click("#exportBtn")
        page.wait_for_function("!$('startRender').disabled")
        assert page.locator("#exportWorkflow").input_value()=="render"
        page.select_option("#exportWorkflow","hdr10plus-master")
        assert page.locator("#nativeProjectExport").is_visible()
        assert not page.locator("#useNativeProjectExport").is_checked()
        page.check("#useNativeProjectExport")
        page.evaluate("value=>$('comparisonMaster').value=value",str(reference))
        page.fill("#exportPath",str(delivered))
        with page.expect_response(lambda p:p.url.endswith("/api/export")) as submitted:
            page.click("#startRender")
        assert submitted.value.ok, submitted.value.json()
        job = wait_until_done(page)
        assert job["status"]=="done" and not job.get("fallback"),job
        assert delivered.is_file()
        page.wait_for_function("!$('startRender').disabled")
        page.fill("#exportPath",str(cancelled))
        with page.expect_response(lambda p:p.url.endswith("/api/export")) as submitted:
            page.click("#startRender")
        assert submitted.value.ok,submitted.value.json()
        page.click("#cancelRender")
        assert wait_until_done(page)["status"]=="cancelled"
        assert not cancelled.exists() and proc.poll() is None
        assert not errors,errors
    values=compare_project(reference,delivered,program,results)
    assert values["passed"],values
    assert all(digest(path)==expected for path,expected in before.items())
    assert not list(results.glob(".vlogcraft_*"))
    receipt=json.loads((results/"installed/process-ownership.json").read_text())
    assert receipt["job_members_at_cleanup"]==0
    report={"offline_installed_gpu_export":True,"default_reference":True,"native_opt_in":True,
            "cancelled_without_publication":True,"originals_and_project_unchanged":True,
            "owned_survivors":0,"comparison":values}
    (results/"qualification.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf8")
    print(json.dumps(report))


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable",type=Path)
    parser.add_argument("project",type=Path)
    parser.add_argument("reference",type=Path)
    parser.add_argument("results",type=Path)
    args=parser.parse_args()
    qualify(args.executable,args.project.resolve(),args.reference.resolve(),args.results)
