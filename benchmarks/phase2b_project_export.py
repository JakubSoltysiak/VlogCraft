"""Opt-in saved-project HDR10+ export using bounded CPU conversion workers."""
import argparse
from contextlib import suppress
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


if __package__:
    from .phase2b_conversion import PQ_TAGS, relay
else:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from phase2b_conversion import PQ_TAGS, relay

import hdr10plus_master
import project_store
import render_engine
import timing


FROZEN_CONVERSION = (
    "zscale=threads=1:agamma=0:pin=2020:tin=linear:min=gbr:rin=full:"
    "p=2020:t=smpte2084:m=2020_ncl:r=limited:npl=100:dither=error_diffusion,format=yuv420p10le"
)
GRAPH_TAIL = f",{FROZEN_CONVERSION}[finished]\n"
CREATE_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def raw_input(pixel_format, width, height, rate):
    return ["ffmpeg","-nostdin","-v","error","-y","-f","rawvideo","-pixel_format",pixel_format,
            "-video_size",f"{width}x{height}","-framerate",rate,"-i","pipe:0"]


def run_segment(composite, converter, encoder, folder, frames, width, height, workers, timeout):
    started = time.monotonic()
    children = []
    with (folder/"composite.log").open("wb") as compose_log, (folder/"encode.log").open("wb") as encode_log:
        try:
            producer = subprocess.Popen(composite, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                        stderr=compose_log, creationflags=CREATE_FLAGS)
            children.append(producer)
            consumer = subprocess.Popen(encoder, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                        stderr=encode_log, creationflags=CREATE_FLAGS)
            children.append(consumer)
            relay(producer,consumer,converter,folder,frames,width,height,workers,timeout)
            for child in reversed(children):
                if child.wait(timeout=max(.01,timeout-(time.monotonic()-started))):
                    raise RuntimeError("The project conversion pipeline exited before completion")
        finally:
            for child in reversed(children):
                if child.poll() is None:
                    child.kill()
            for child in reversed(children):
                child.wait(timeout=10)
                if child.stdin:
                    with suppress(BrokenPipeError):
                        child.stdin.close()
                if child.stdout:
                    child.stdout.close()


class ProjectConverter:
    def __init__(self, width, height, workers, timeout, progress):
        self.width, self.height = width, height
        self.workers, self.timeout = workers, timeout
        self.progress = progress
        self.completed = 0
        self.fallbacks = 0

    def __call__(self, command, cwd):
        if "-/filter_complex" not in command or "libx265" not in command or "[finished]" not in command:
            return render_engine._run(command,cwd)
        script_index = command.index("-/filter_complex")+1
        script = Path(command[script_index])
        if not script.name.startswith("hdr_graph_"):
            return render_engine._run(command,cwd)
        graph = script.read_text(encoding="utf-8")
        frames = int(command[command.index("-frames:v")+1])
        if frames < 2 or graph.count(GRAPH_TAIL) != 1:
            return render_engine._run(command,cwd)
        rate = command[command.index("-r")+1]
        target = Path(command[-1])
        with tempfile.TemporaryDirectory(prefix="project-color-",dir=cwd) as temp:
            stage = Path(temp)
            altered = stage/"linear.txt"
            altered.write_text(graph.replace(GRAPH_TAIL,",format=gbrpf32le[finished]\n"),encoding="utf-8")
            compose = command[:command.index("-c:v")]
            compose[script_index] = str(altered)
            compose += ["-c:v","rawvideo","-threads:v","1","-flush_packets","1","-f","rawvideo","pipe:1"]
            converter = raw_input("gbrpf32le",self.width,self.height,rate)+["-vf",FROZEN_CONVERSION]
            encoder = raw_input("yuv420p10le",self.width,self.height,rate)
            output_start = command.index("-an",script_index+1)
            encoder += ["-map","0:v:0","-vf","setsar=1,"+PQ_TAGS,*command[output_start:]]
            try:
                run_segment(compose,converter,encoder,stage,frames,self.width,self.height,self.workers,self.timeout)
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, TimeoutError) as error:
                target.unlink(missing_ok=True)
                self.fallbacks += 1
                self.progress(f"Reference fallback for this segment ({type(error).__name__})")
                return render_engine._run(command,cwd)
        self.completed += 1


def export_project(state, destination, *, backend="reference", workers=3, timeout=180, progress=print):
    """Render a saved document via the normal timeline, audio, authoring and clock machinery."""
    destination = destination.resolve()
    if destination.exists():
        raise FileExistsError("Choose a new output path")
    count = hdr10plus_master.preflight(state)
    output = state["output"]
    fps = timing.rate(output["fps"])
    converter = ProjectConverter(output["width"],output["height"],workers,timeout,progress)
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="vlogcraft-hdr-",dir=destination.parent) as temp:
        work = Path(temp)
        static = work/"static.mp4"
        master = work/"verified.mp4"
        def report(value,message):
            progress(f"{min(90,round(value*.9))}% {message}" if value<100 else "90% Base video and audio rendered")

        render_engine.render(state,static,work/"render",popen=converter if backend=="parallel" else None,
                             on_progress=report)
        hdr10plus_master.author(static,master,work,fps,count,render_engine._run,
                                lambda message,value:progress(f"{value}% {message}"),lambda:False)
        os.link(master,destination)
        progress("100% Verified HDR10+ master published")
    return {"frames":count,"parallel_segments":converter.completed,"fallback_segments":converter.fallbacks}


if __name__ == "__main__":
    import server

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project",type=Path)
    parser.add_argument("destination",type=Path)
    parser.add_argument("--backend",choices=("reference","parallel"),default="reference")
    parser.add_argument("--workers",type=int,choices=range(2,5),default=3)
    args = parser.parse_args()
    state,recovered = project_store.load(args.project,server.validate_document)
    if state is None or recovered:
        raise SystemExit("A valid primary saved project is required")
    print(export_project(state,args.destination,backend=args.backend,workers=args.workers))
