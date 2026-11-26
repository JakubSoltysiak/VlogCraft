"""Dispatch original HDR render spans to indexed camera or managed picture providers."""
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
import shutil
import time

import numpy as np

from export_raster_options import constant_still
import color_management
import hdr10plus_export
from hdr10plus_bitstream import codec_configuration, length_size, packet_records
import hdr_render
from native_project_plan import Ineligible, LAYER_BUDGET, Program, compile_project, run_capture
import render_engine
import sequences
import timeline_transitions
import timing


MAX_SPANS = 24
MAX_FRAMES = 3600
_AUDIO_KEYS = {"position", "start", "volume", "audioDetached", "bass", "treble", "pan", "compress"}
_CAMERA_NEUTRAL = {
    key: value for key, value in hdr10plus_export.NEUTRAL.items() if key not in _AUDIO_KEYS
}


@dataclass(frozen=True)
class MixedPlan:
    width: int
    height: int
    fps: Fraction
    spans: tuple
    routes: tuple
    camera: Program

    @property
    def frames(self):
        return range(self.spans[-1][1])


def camera_clip(flat, assets, first, last, fps, picture_transitions):
    if any(pair.start < last and pair.end > first for pair in picture_transitions):
        return None
    video, _ = render_engine.active_clips(flat, float(first/fps), float(last/fps))
    if len(video) != 1:
        return None
    _, clip = video[0]
    if (clip["kind"] != "video" or clip.get("crop") or
            set(clip.get("keys", {})) - {"volume"} or
            any(clip.get(key, value) != value for key, value in _CAMERA_NEUTRAL.items()) or
            clip.get("inputColor", {}).get("profile", "source") != "source"):
        return None
    w, h = flat["output"]["width"], flat["output"]["height"]
    asset, size, orientation, interpretation = hdr_render.layer_contract(assets, clip, w, h)
    if (orientation not in ("", "transpose=clock") or interpretation[3] != "limited" or
            Path(asset["path"]).suffix.lower() not in (".mp4", ".mov", ".m4v") or
            (not orientation and size[0]*h != size[1]*w)):
        return None
    if interpretation[:3] == ("bt2020", "smpte2084", "bt2020nc"):
        return clip if (asset.get("codec"), asset.get("pixelFormat")) == ("hevc", "yuv420p10le") else None
    if (interpretation[:3] == ("bt709", "bt709", "bt709") and asset.get("pixelFormat") == "yuv420p" and
            asset.get("codec") in ("h264", "hevc") and
            flat["output"]["color"]["sdrWhiteNits"] == 100):
        return clip
    return None


def compile_mixed(state, work):
    """Keep exact renderer boundaries and compact only the indexed camera instructions."""
    flat = sequences.playback(state)
    output = flat["output"]
    width, height, fps = output["width"], output["height"], timing.rate(output["fps"])
    profile = output.get("preset"), output.get("crf"), output.get("bitrate", 0)
    contract = color_management.validate_output(output["color"])
    if ((width, height, fps) != (3840, 2160, 60) or profile != ("slow", 20, 60) or
            contract["output"] != "hdr10" or output["encoder"] != "libx265" or
            not {"mastering", "maxCLL"}.issubset(contract)):
        raise Ineligible("Mixed qualification requires UHD60 Main10/PQ Slow CRF 20 with saved mastering")
    spans = tuple(render_engine.frame_spans(flat, fps))
    if not spans or spans[0][0] != 0 or not 2 <= spans[-1][1] <= MAX_FRAMES or len(spans) > MAX_SPANS:
        raise Ineligible("Mixed qualification exceeds the picture or original span budget")
    assets = {asset["id"]: asset for asset in flat["assets"]}
    pictures, _ = timeline_transitions.plan(flat)
    routes, selected = [], []
    sources = set()
    for span in spans:
        clip = camera_clip(flat, assets, *span, fps, pictures)
        if clip is None or (len(sources) == LAYER_BUDGET and clip["id"] not in sources):
            routes.append("managed")
        else:
            sources.add(clip["id"])
            selected.append(span)
            routes.append("camera")
    if not selected or len(selected) == len(spans):
        raise Ineligible("Mixed qualification requires both indexed camera and managed picture spans")
    camera = compile_project(flat, work, camera_raster=True, camera_spans=selected)
    return MixedPlan(width, height, fps, spans, tuple(routes), camera)


def decoder_configuration(video):
    """Read hvcC configuration and its VPS/SPS/PPS, alongside the NAL length size."""
    width = length_size(video)
    data = codec_configuration(video)
    offset = 23
    parameter_sets = {}
    for _ in range(data[22]):
        if offset+3 > len(data):
            raise Ineligible("Truncated HEVC parameter sets in a mixed span")
        nal_type = data[offset] & 63
        count = int.from_bytes(data[offset+1:offset+3], "big")
        offset += 3
        for _ in range(count):
            size = int.from_bytes(data[offset:offset+2], "big")
            offset += 2
            if size < 2 or offset+size > len(data):
                raise Ineligible("Invalid HEVC parameter set in a mixed span")
            if nal_type in (32, 33, 34):
                parameter_sets.setdefault(nal_type, []).append(data[offset:offset+size])
            offset += size
    if offset != len(data) or set(parameter_sets) != {32, 33, 34}:
        raise Ineligible("Missing HEVC parameter sets in a mixed span")
    return width, data[:22], parameter_sets


def first_picture_is_idr(file, packet, width):
    end = int(packet[b"pos"])+int(packet[b"size"])
    file.seek(int(packet[b"pos"]))
    while file.tell()+width+2 <= end:
        prefix = file.read(width+2)
        if len(prefix) != width+2:
            return False
        size = int.from_bytes(prefix[:width], "big")
        next_nal = file.tell()+size-2
        if size < 2 or next_nal > end:
            return False
        kind = (prefix[width] >> 1) & 63
        if kind < 32:
            return kind in (19, 20)
        file.seek(next_nal)
    return False


def verify_video_span(path, count, cancelled):
    """Verify that an original managed encoder boundary is independently decodable."""
    video, = hdr10plus_export.media(path)
    if ((video.get("time_base"), video.get("start_pts"), video.get("duration_ts")) != ("1/120000", 0, count*2000)
            or video.get("chroma_location") != "left"):
        raise Ineligible("A mixed span has incompatible picture declarations or local clocks")
    width, header, parameter_sets = decoder_configuration(video)
    seen = bytearray(count)
    first_dts = None
    with path.open("rb") as file, packet_records(path, "v:0") as packets:
        for index, packet in enumerate(packets):
            if cancelled():
                raise RuntimeError("Export cancelled")
            picture, remainder = divmod(int(packet.get(b"pts", b"")), 2000)
            dts = int(packet.get(b"dts", b""))
            if first_dts is None:
                first_dts = dts
            if (remainder or not 0 <= picture < count or seen[picture] or
                    int(packet.get(b"duration", b"")) != 2000 or dts != first_dts+index*2000):
                raise Ineligible("A mixed span has a missing or duplicate local picture")
            seen[picture] = 1
            if index == 0 and (picture != 0 or b"K" not in packet.get(b"flags", b"") or
                               not first_picture_is_idr(file, packet, width)):
                raise Ineligible("A mixed span does not start with an independent IDR picture")
    if not all(seen):
        raise Ineligible("A mixed span has an incomplete local picture clock")
    fields = (*hdr10plus_export.VIDEO_FIELDS, "codec_tag_string", "time_base", "chroma_location")
    return tuple(video.get(key) for key in fields), width, header, parameter_sets


class MixedVideo:
    """Run each original picture command once. The normal renderer owns audio and muxing."""

    def __init__(self, flat, plan, native, *, fast_raster=False, parallel_x265=False):
        self.flat = flat
        self.plan = plan
        self.native = native
        self.fast_raster = fast_raster
        self.parallel_x265 = parallel_x265
        self.step = 0
        self.configuration = None
        self.managed_seconds = 0.
        self.boundary_verification_seconds = 0.
        self.prepared_still_spans = 0

    def __call__(self, command, cwd, first, last):
        self.native.check()
        if self.step >= len(self.plan.spans) or self.plan.spans[self.step] != (first, last):
            raise Ineligible("The managed picture command changed an original mixed span")
        if self.plan.routes[self.step] == "camera":
            self.native(command, cwd)
        else:
            began = time.perf_counter()
            if self.fast_raster:
                from export_raster_options import prepare_still_command

                start, end = float(first/self.plan.fps), float(last/self.plan.fps)
                video, _ = render_engine.active_clips(self.flat, start, end)
                if any(clip["kind"] in ("image", "title") for _, clip in video):
                    prepared = prepare_still_command(command, self.flat, start, end, Path(cwd))
                    self.prepared_still_spans += prepared != command
                    command = prepared
            if self.parallel_x265:
                from native_project_render import parallel_camera_x265

                command = parallel_camera_x265(command)
            self.native.run(command, cwd)
            self.managed_seconds += time.perf_counter()-began
        began = time.perf_counter()
        configuration = verify_video_span(Path(command[-1]), last-first, self.native.cancelled)
        self.boundary_verification_seconds += time.perf_counter()-began
        if self.configuration is None:
            self.configuration = configuration
        elif self.configuration != configuration:
            raise Ineligible("Mixed spans disagree on the HEVC decoder configuration")
        self.step += 1

    def receipt(self):
        if self.step != len(self.plan.spans):
            raise Ineligible("The renderer did not complete every mixed picture span")
        return {
            "spans": [
                {"first": first, "last": last, "provider": route}
                for (first, last), route in zip(self.plan.spans, self.plan.routes, strict=True)
            ],
            "camera_pictures": len(self.plan.camera.frames),
            "managed_pictures": len(self.plan.frames)-len(self.plan.camera.frames),
            "managed_picture_encode_seconds": self.managed_seconds,
            "boundary_verification_seconds": self.boundary_verification_seconds,
            "prepared_still_spans": self.prepared_still_spans,
            "original_span_clock_and_decoder_configuration_verified": True,
        }


def compare_mixed_samples(flat, candidate, plan, work, cancelled, clocks, *, sample_static_stills=False):
    """Check source quality on both sides of each original cut with bounded RAM."""
    from native_project_verification import camera_sample_reference, sample_reference, sample_score

    def selection(pictures):
        return "select='"+"+".join(f"eq(n,{frame})" for frame in pictures)+"'"

    spans = [[first, (first+last-1)//2, last-1] for first, last in plan.spans]
    samples = [sorted(set(pictures)) for pictures in spans]
    frame_bytes = plan.width*plan.height*3
    expected_bytes = sum(map(len, samples))*frame_bytes
    if shutil.disk_usage(work).free < expected_bytes:
        raise Ineligible("Insufficient scratch space for the bounded mixed picture verification")
    actual_path = work/"mixed-audit.yuv"
    run_capture(["ffmpeg", "-v", "error", "-nostdin", "-y", "-threads", "2", "-i", candidate,
                 "-an", "-vf", selection(frame for pictures in samples for frame in pictures),
                 "-fps_mode", "passthrough", "-c:v", "rawvideo", "-threads:v", "1",
                 "-f", "rawvideo", actual_path],
                timeout=max(90, len(plan.frames)//4), cancelled=cancelled)
    if actual_path.stat().st_size != expected_bytes:
        raise Ineligible("The mixed decode did not return the requested verification pictures")

    camera_spans = iter(plan.camera.spans)
    scores = []
    with actual_path.open("rb") as actual:
        for (first, last), route, pictures in zip(plan.spans, plan.routes, samples, strict=True):
            if route == "camera":
                camera_first, _ = next(camera_spans)
                references = (
                    camera_sample_reference(flat, frame, camera_first+frame-first,
                                            plan.camera, work, cancelled, clocks)
                    for frame in pictures
                )
            elif sample_static_stills and constant_still(flat, first, last, plan.fps):
                # Re-render each requested instant independently with the original
                # full managed graph. Do not share the optimized still's cache.
                references = (sample_reference(hdr_render.command(
                    flat, float(frame/plan.fps), float((frame+1)/plan.fps),
                    work/f"still-audit-{frame}.mov", work), cancelled) for frame in pictures)
            else:
                command = hdr_render.command(flat, float(first/plan.fps), float(last/plan.fps),
                                             work/f"mixed-audit-{first}.mov", work)
                raw = sample_reference(command, cancelled, frames=[frame-first for frame in pictures],
                                       timeout=max(90, (last-first)*3))
                if len(raw) != len(pictures)*frame_bytes:
                    raise Ineligible("The full managed span did not return its requested raw pictures")
                view = memoryview(raw)
                references = (view[offset:offset+frame_bytes] for offset in range(0, len(view), frame_bytes))
            for frame, expected in zip(pictures, references, strict=True):
                scores.append(sample_score(frame, np.frombuffer(actual.read(frame_bytes), "<u2"),
                                           np.frombuffer(expected, "<u2")))
    actual_path.unlink()
    return scores
