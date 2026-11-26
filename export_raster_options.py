"""Opt-in reuse of the final Main10 raster for an unchanging HDR still."""
from pathlib import Path

import hdr_layers
import render_engine
import sequences
import timeline_transitions
import timing


def prepare_still_command(command, state, start, end, work):
    flat = sequences.playback(state)
    if "libx265" not in command or "-/filter_complex" not in command:
        return command
    rate = timing.rate(flat["output"]["fps"])
    first, last = timing.frame_at(start, rate), timing.frame_at(end, rate)
    count = last - first
    if count < 2 or not constant_still(flat, first, last, rate):
        return command
    index = command.index("-/filter_complex") + 1
    graph = Path(command[index])
    output = graph.read_text(encoding="utf-8").rstrip()
    if not output.endswith("[finished]") or int(command[command.index("-frames:v") + 1]) != count:
        raise ValueError("Unexpected HDR still output clock or filter graph")
    # Keep the complete managed picture, including EXIF, alpha, masks and
    # the final error-diffusion quantizer. Repeat exactly one quantized frame.
    prepared = Path(work) / (graph.stem + "_held.txt")
    prepared.write_text(output.removesuffix("[finished]")
                        + f",trim=end_frame=1,loop=loop={count-1}:size=1:start=0,"
                        + f"setpts=N/(({rate})*TB)[finished]\n", encoding="utf-8")
    return [*command[:index], str(prepared), *command[index + 1:]]


def constant_still(flat, first, last, fps):
    active, _ = render_engine.active_clips(flat, float(first/fps), float(last/fps))
    if len(active) != 1 or timeline_transitions.present(flat):
        return False
    _, clip = active[0]
    return (clip["kind"] == "image" and not hdr_layers.still_needs_frame_clock(clip)
            and all(key=="volume" or not keys for key,keys in clip.get("keys",{}).items())
            and timing.frame_at(clip["position"],fps) <= first
            and timing.frame_at(render_engine.clip_finish(clip),fps) >= last)
