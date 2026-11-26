"""Use the qualified mixed raster for independently restartable, original picture spans."""
from contextlib import contextmanager, suppress
from threading import Event, Thread

import psutil

from export_raster_options import prepare_still_command
from mixed_export import camera_clip
import native_project_plan as plan
from native_project_render import ProjectVideo
from native_project_verification import verify_source_clocks
import render_engine


@contextmanager
def measure_tree(stats):
    root = psutil.Process()
    done = Event()
    def observe():
        while not done.is_set():
            rss = 0
            for child in [root, *root.children(recursive=True)]:
                with suppress(psutil.NoSuchProcess, psutil.AccessDenied):
                    rss += child.memory_info().rss
            stats["sampled_peak_tree_bytes"] = max(stats.get("sampled_peak_tree_bytes",0), rss)
            done.wait(.35)
    thread = Thread(target=observe, daemon=True)
    thread.start()
    try:
        yield
    finally:
        done.set()
        thread.join()


def encode(state, span, command, work, worker, runtime, timeout, cancelled):
    assets = {asset["id"]:asset for asset in state["assets"]}
    bounds = (span.first,span.last)
    if (bounds not in render_engine.frame_spans(state,span.rate)
            or camera_clip(state,assets,*bounds,span.rate,[]) is None):
        prepared = prepare_still_command(command,state,*span.seconds,work)
        _, logs = plan.run_capture(prepared,cwd=work,timeout=timeout,cancelled=cancelled)
        return logs, {"provider":"prepared-still" if prepared!=command else "managed"}
    program = plan.compile_project(state,work,camera_raster=True,camera_spans=[bounds])
    plan.write_plan(work/"plan.bin",program)
    clocks = plan.write_sources(work/"sources.bin",program,cancelled,first_time=True,camera_range=True,
                               keyframe_seek=True,camera_raster=True)
    with ProjectVideo(program,work,worker,runtime,timeout,cancelled,"gpu32-camera-raster",None,
                      direct_pipe=True,fast_raster=True) as owned:
        owned(command,work)
        result = owned.receipt()
        if result.get("adapter") != "AMD Radeon(TM) 890M Graphics":
            raise ValueError("This camera segment was not rendered on the qualified adapter")
    checked = verify_source_clocks(program,clocks,cancelled,camera_raster=True)
    return (work/"encoder-0.log").read_bytes(), {
        "provider":"indexed-camera", "verified_source_pictures":checked,
        "peak_gpu_local_bytes":result["gpu_local_bytes"], "peak_worker_bytes":result["peak_rss_bytes"]}
