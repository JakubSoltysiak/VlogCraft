"""Qualify the optional GPU export from the installed Windows editor, offline."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT),str(ROOT/"benchmarks"),str(ROOT/"tests")]

from native_project_render import compare_project
from native_project_plan import compile_project
import project_store
import sequences
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


def qualify(executable,project,reference,results,*,mixed=False):
    results=results.resolve()
    results.mkdir(parents=True,exist_ok=False)
    local=results/"qualification.vlogcraft"
    shutil.copyfile(project,local)
    state,recovered=project_store.load(local,server.validate_document)
    assert not recovered
    linked = {clip.get(key) for track in sequences.playback(state)["tracks"] for clip in track["clips"]
              for key in ("assetId", "lutId")}
    library = {Path(asset["path"]) for asset in state["assets"]}
    missing = {path for path in library if not path.exists()}
    assert not any(asset["id"] in linked and Path(asset["path"]) in missing for asset in state["assets"]), (
        "A required timeline source is missing")
    protected = [local, reference, *(library-missing)]
    before = {path:digest(path) for path in protected}
    delivered = results/"Projekt próbny.mp4"
    cancelled = results/"Anulowany.mp4"
    if mixed:
        from mixed_export import compile_mixed
        from mixed_project_delivery import verify_master

        program = compile_mixed(state,results)
    else:
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
        if mixed:
            page.select_option("#nativeProjectPolicy","mixed")
            assert page.locator("#nativeProjectMixedNote").is_visible()
        page.evaluate("value=>$('comparisonMaster').value=value",str(reference))
        page.fill("#exportPath",str(delivered))
        with page.expect_response(lambda p:p.url.endswith("/api/export")) as submitted:
            page.click("#startRender")
        assert submitted.value.ok, submitted.value.json()
        if mixed:
            request = submitted.value.request.post_data_json
            assert request.get("experimentalMixedExport") is True
            assert request.get("comparisonMaster") == str(reference) and "experimentalFirstExport" not in request
        job = wait_until_done(page,timeout=max(180,5*len(program.frames)) if mixed else 180)
        assert job["status"]=="done" and not job.get("fallback"),job
        if mixed:
            assert job["verificationPolicy"]=="mixed-exact-master",job
            assert job["deliveredBackend"]=="mixed-d3d11-zimg-managed",job
            assert job["verifiedFrames"]==len(program.frames) and job["x265PoolWorkers"]==2,job
        assert delivered.is_file()
        page.wait_for_function("!$('startRender').disabled")
        page.fill("#exportPath",str(cancelled))
        with page.expect_response(lambda p:p.url.endswith("/api/export")) as submitted:
            page.click("#startRender")
        assert submitted.value.ok,submitted.value.json()
        deadline=time.monotonic()+45
        while time.monotonic()<deadline:
            try:
                if any(child.name().casefold()=="vlogcraftproject.exe" for child in
                       psutil.Process(proc.pid).children(recursive=True)):
                    break
            except psutil.NoSuchProcess:
                pass
            time.sleep(.05)
        else:
            raise TimeoutError("The owned D3D11 worker did not start")
        page.click("#cancelRender")
        assert wait_until_done(page)["status"]=="cancelled"
        assert not cancelled.exists() and proc.poll() is None
        assert not errors,errors
    if mixed:
        values=verify_master(reference,delivered,state,len(program.frames),results,lambda:False)
    else:
        values=compare_project(reference,delivered,program,results)
        assert values["passed"],values
    assert all(digest(path)==expected for path,expected in before.items())
    assert all(not path.exists() for path in missing)
    assert not list(results.glob(".vlogcraft_*"))
    receipt=json.loads((results/"installed/process-ownership.json").read_text())
    assert receipt["job_members_at_cleanup"]==0
    report={"offline_msi_image_gpu_export":True,"default_reference":True,"native_opt_in":True,
            "active_native_worker_cancelled_without_publication":True,"originals_and_project_unchanged":True,
            "owned_survivors":0,"comparison":values}
    if mixed:
        report["mixed_exact_master_editor"]=True
    (results/"qualification.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf8")
    print(json.dumps(report))


def qualify_fallback(executable,results):
    """Exercise reference enforcement and a complete fallback on managed contrast."""
    from PIL import Image
    from hdr10plus_master import author
    from benchmarks.render_phase2_export import decoded
    import render_engine
    from test_hdr_color import project
    import timing

    results=results.resolve()
    results.mkdir(parents=True,exist_ok=False)
    source,target,reference,static,local=(results/name for name in
                                         ("still.png","delivery.mp4","reference.mp4","static.mp4","qualification.vlogcraft"))
    Image.new("RGB",(128,72),"#838383").save(source)
    asset={"id":"still","path":str(source),"kind":"image","name":"Still","duration":5,**server.probe(source)}
    state=project([asset])
    clip=state["tracks"][0]["clips"][0]
    clip.update(contrast=1.15)
    project_store.save(local,timing.encode(state),server.validate_document)
    state,_=project_store.load(local,server.validate_document)
    render_engine.render(state,static,results/"reference-render")
    author(static,reference,results,24,12,render_engine._run,lambda *_:None,lambda:False)
    identity={item:digest(item) for item in (source,local,reference)}
    with session(executable,results/"installed",offline=True,project_path=local) as (page,_,__,errors):
        page.click("#exportBtn")
        page.wait_for_function("!$('startRender').disabled")
        page.select_option("#exportWorkflow","hdr10plus-master")
        page.check("#useNativeProjectExport")
        page.fill("#exportPath",str(target))
        page.click("#startRender")
        page.wait_for_function("document.getElementById('toast').textContent.includes('Choose a verified comparison master')")
        assert not target.exists()
        page.evaluate("path=>$('comparisonMaster').value=path",str(reference))
        with page.expect_response(lambda response:response.url.endswith("/api/export")) as submitted:
            page.click("#startRender")
        assert submitted.value.ok,submitted.value.json()
        job=wait_until_done(page)
        assert job["status"]=="done" and "Reference fallback" in job.get("fallback",""),job
        assert not errors,errors
    assert decoded(reference,"0:v:0","framemd5")==decoded(target,"0:v:0","framemd5")
    assert decoded(reference,"0:a:0","s16le")==decoded(target,"0:a:0","s16le")
    assert all(digest(item)==expected for item,expected in identity.items())
    evidence={"reference_required_before_launch":True,"unsupported_managed_contrast_fallback":True,
              "exact_reference_pictures_and_pcm":True,"project_inputs_unchanged":True}
    (results/"qualification.json").write_text(json.dumps(evidence,indent=2)+"\n",encoding="utf8")
    print(json.dumps(evidence))


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable",type=Path)
    parser.add_argument("project",type=Path)
    parser.add_argument("reference",type=Path)
    parser.add_argument("results",type=Path)
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument("--fallback-only",action="store_true")
    mode.add_argument("--mixed",action="store_true")
    args=parser.parse_args()
    if args.fallback_only:
        qualify_fallback(args.executable,args.results)
    else:
        qualify(args.executable,args.project.resolve(),args.reference.resolve(),args.results,mixed=args.mixed)
