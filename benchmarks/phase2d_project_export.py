"""Opt-in D3D11 export of validated saved HDR10+ projects with reference fallback."""
import argparse
from contextlib import suppress
import json
import os
from pathlib import Path
import sys

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmarks.phase2b_project_export import export_project
from hdr10plus_fast import author_options
from native_project_render import export_native
import project_store


def main():
    import server

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project",type=Path)
    parser.add_argument("destination",type=Path)
    parser.add_argument("--backend",choices=("reference","d3d11"),default="reference")
    parser.add_argument("--worker",type=Path)
    parser.add_argument("--runtime",type=Path)
    parser.add_argument("--author-dll",type=Path)
    parser.add_argument("--compare-master",type=Path)
    parser.add_argument("--report",type=Path)
    parser.add_argument("--resources",action="store_true",help="Sample owned processes and Windows GPU counters")
    parser.add_argument("--diagnostics",type=Path,help="Private qualification output directory")
    parser.add_argument("--diagnostic-no-fallback",action="store_true")
    args = parser.parse_args()
    state,recovered = project_store.load(args.project,server.validate_document)
    if state is None or recovered:
        parser.error("A valid primary saved project is required")
    options = author_options(args.author_dll) if args.author_dll else None
    result = {}
    resources = None
    if args.resources:
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"tests"))
        from performance import Resources
        resources = Resources(os.getpid(),gpu=True)
    try:
        if args.backend=="d3d11":
            if args.worker is None or args.compare_master is None:
                parser.error("D3D11 qualification requires a native worker and an independent reference master")
            def fallback():
                print("Native export rejected. Rendering the complete project with the reference backend.",flush=True)
                export_project(state,args.destination,authoring=options)
            export_native(state,args.destination,args.compare_master,args.worker,args.runtime,authoring=options,
                          progress=lambda value,message:print(f"{value}% {message}",flush=True),
                          fallback=None if args.diagnostic_no_fallback else fallback,
                          diagnostics=args.diagnostics,record=result)
        else:
            result.update(export_project(state,args.destination,authoring=options),delivered_backend="reference")
    finally:
        if resources:
            result["resources"] = resources.finish()
        if args.report:
            args.report.write_text(json.dumps(result,indent=2)+"\n",encoding="utf8")
    print(json.dumps(result))


if __name__=="__main__":
    main()
