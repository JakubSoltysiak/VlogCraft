"""Qualify a source-type-aware UHD export against a pinned, independently encoded master."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmarks.phase3a_encoder_matrix import picture_slices
from benchmarks.phase3a_segment_resume import compare_master
from hdr10plus_fast import author_options
from mixed_export import compile_mixed
from native_project_render import export_native
from native_project_verification import source_snapshot
import server


def qualify(project, folder, reference, reference_project, reference_sha256, worker, runtime,
            *, pool=2, fast_raster=False, author_dll=None):
    original = project.read_bytes()
    if original != reference_project.read_bytes():
        raise ValueError("The reference must identify this exact saved edit")
    with reference.open("rb") as f:
        if hashlib.file_digest(f, "sha256").hexdigest() != reference_sha256:
            raise ValueError("The reference master changed")
    state = server.validate_document(json.loads(original))
    sources = source_snapshot(state, include_hidden_audio=True)
    folder = folder.resolve()
    folder.mkdir(parents=True, exist_ok=False)
    control = reference.parent/"control.json"
    if control.is_file():
        spec = json.loads(control.read_bytes())
        if (not spec["passed"] or spec["continuous"] or spec["pool"] != pool or
                spec.get("master_sha256", reference_sha256) != reference_sha256 or
                spec["project_hash"] != hashlib.sha256(original).hexdigest()):
            raise ValueError("Mismatched managed export reference or encoder configuration")
    elif pool != 2:
        raise ValueError("An alternate pool requires its separately measured managed control")
    plan = compile_mixed(state, folder)
    candidate = folder/"candidate.mp4"
    record = dict(passed=False, frames=len(plan.frames), pool=pool, fast_raster=fast_raster)
    start = time.perf_counter()
    try:
        first = record["first_export"] = {}
        try:
            export_native(state, candidate, None, worker, runtime, first_time=True, camera_range=True,
                          qualification=True, camera_raster=True, mixed=True, fast_raster=fast_raster,
                          parallel_x265=pool==8, diagnostics=folder/"diagnostics", record=first,
                          timeout=max(600, len(plan.frames)*5), authoring=author_options(author_dll) if author_dll else {},
                          progress=lambda p, m: print(f"{p}% {m}", flush=True))
        except RuntimeError:
            retained = folder/"diagnostics"/"master.mp4"
            if retained.is_file():
                record["rejected_master_comparison"] = compare_master(reference, retained, plan, folder, lambda:False)
            raise
        t = time.perf_counter()
        comparison = record["independent"] = compare_master(reference, candidate, plan, folder, lambda:False)
        actual = picture_slices(candidate, 0, len(plan.frames))
        expected = picture_slices(reference, 0, len(plan.frames))
        record["equal_coded_pictures"] = sum(x == y for x,y in zip(actual, expected, strict=True))
        record["independent_seconds"] = time.perf_counter()-t
        record["sources_unchanged"] = sources == source_snapshot(state, include_hidden_audio=True) and original == project.read_bytes()
        if (not comparison["passed"] or comparison["exact_decoded_pictures"] != len(plan.frames)
                or record["equal_coded_pictures"] != len(plan.frames) or not record["sources_unchanged"]):
            raise ValueError("The reference-equivalent mixed provider failed its all-picture gate")
        os.link(candidate, folder/"verified.mp4")
        record["passed"] = True
    finally:
        record["wall_seconds"] = time.perf_counter()-start
        (folder/"qualification.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("project","folder","reference","reference_project","worker","runtime"):
        parser.add_argument(field,type=Path)
    parser.add_argument("--reference-sha256",required=True)
    parser.add_argument("--author-dll",type=Path)
    parser.add_argument("--pool",type=int,choices=(2,8),default=2)
    parser.add_argument("--fast-raster",action="store_true")
    args = parser.parse_args()
    result = qualify(**vars(args))
    print(json.dumps({key:result[key] for key in ("frames","passed","wall_seconds")}))
