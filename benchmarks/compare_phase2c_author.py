"""Measure exact authoring alternatives on one frozen Phase 2C intermediate."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from time import perf_counter

from conditions import Conditions
from render_phase2 import ROOT, call, power

sys.path[:0] = [str(ROOT), str(ROOT/"tests")]
from hdr10plus_master import author
from phase2c_author import author_options
from performance import Resources


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def benchmark(source, result, library, modes, repeat):
    if not power():
        raise RuntimeError("Connect AC for the primary timing arms")
    result.mkdir(parents=True, exist_ok=False)
    info = json.loads((source/"profile.json").read_text(encoding="utf-8"))
    expected = digest(source/"reference.mp4")
    outcomes = []
    conditions = Conditions()
    try:
        for iteration in range(repeat):
            for mode in modes:
                work = result/f"{mode}-{iteration+1}"
                work.mkdir()
                output = work/"master.mp4"
                if mode=="frozen":
                    options = {}
                else:
                    settings = int(mode[-1]) if mode.startswith("native") else 1
                    options = author_options(library if mode.startswith("native") else None,settings)
                monitor = Resources(os.getpid(),gpu=False)
                started = perf_counter()
                phases = {}

                def stage(label, fraction):
                    phases.setdefault(fraction,perf_counter()-started)

                try:
                    count = author(source/"static.mp4",output,work,60,info["pictures"],
                                   lambda command,_:call(command,240),stage,lambda:False,**options)
                    duration = perf_counter()-started
                finally:
                    resources = monitor.finish()
                exact = digest(output)==expected
                outcomes.append(dict(mode=mode,repeat=iteration+1,wall_seconds=duration,frames=count,
                                     exact_file=exact,stage_start_seconds=phases,resources=resources))
                if not exact:
                    raise ValueError("The candidate changed bytes relative to the frozen authored master")
    finally:
        report = dict(pictures=info["pictures"],arms=outcomes,power=conditions.finish())
        (result/"report.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source",type=Path)
    parser.add_argument("result",type=Path)
    parser.add_argument("--library",type=Path)
    parser.add_argument("--mode",choices=("frozen","pipe","native1","native3"),action="append",required=True)
    parser.add_argument("--repeat",type=int,default=1)
    args=parser.parse_args()
    if not 1<=args.repeat<=5 or (any(m.startswith("native") for m in args.mode) and not args.library):
        parser.error("Native modes require the analysis DLL and one to five repeats")
    answer=benchmark(args.source.resolve(),args.result.resolve(),args.library,args.mode,args.repeat)
    print(json.dumps(answer["arms"],indent=2))
