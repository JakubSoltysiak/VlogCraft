"""Derive a straight-cut saved project from the private Phase 2D timing fixture."""
import argparse
from pathlib import Path
import sys

if not __package__:
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

import project_store
import server
import timing


def create(source,destination,count):
    state,recovered=project_store.load(source,server.validate_document)
    if state is None or recovered:
        raise ValueError("Use the original intact Phase 2D project")
    body,= (track for track in state["tracks"] if sum(c["kind"]=="video" for c in track["clips"])==2)
    first,second=(clip for clip in body["clips"] if clip["kind"]=="video")
    span=count/120
    first.update(position=0.,end=span)
    second.update(position=span,end=second["start"]+span)
    second.pop("transitionIn",None)
    body["clips"]=[first,second]
    state["tracks"]=[body,*[track for track in state["tracks"] if track["type"]=="audio"]]
    for track in state["tracks"][1:]:
        for clip in track["clips"]:
            clip["end"]=clip["start"]+count/60
    destination.parent.mkdir(parents=True,exist_ok=True)
    if destination.exists():
        raise FileExistsError("Choose a new fixture path")
    project_store.save(destination,timing.encode(state),server.validate_document)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source",type=Path)
    parser.add_argument("destination",type=Path)
    parser.add_argument("--frames",type=int,required=True)
    args=parser.parse_args()
    if not 4<=args.frames<=120 or args.frames%2:
        parser.error("Choose an even frame count between 4 and 120")
    create(args.source,args.destination,args.frames)
