"""Opt-in editor delivery of a mixed HDR10+ project against a matched master."""
from fractions import Fraction
from hashlib import sha256
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace

from hdr10plus_bitstream import conformance_issues, length_size, packet_records, sample_metadata
from hdr10plus_fast import author_options
from mixed_export import MAX_FRAMES
from native_project_render import NativeFailure, compare_project, export_native
from native_project_verification import source_snapshot
import hdr10plus_export
import hdr10plus_master
import sequences
import timing


VERIFICATION_POLICY = "mixed-exact-master"


def check_cancelled(cancelled):
    if cancelled():
        raise RuntimeError("Export cancelled")


def protect_comparison_master(destination, reference):
    destination, reference = Path(destination), Path(reference).resolve()
    if destination.resolve() == reference or (destination.exists() and reference.exists() and
                                               destination.samefile(reference)):
        raise ValueError("Choose a destination different from the comparison master")


def master_identity(path, cancelled):
    def signature(stat):
        return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns

    digest = sha256()
    original = signature(path.stat())
    with path.open("rb") as source:
        # Windows stat and fstat can report different ctime values for the
        # same file. Use the handle to check identity and the path for times.
        if signature(os.fstat(source.fileno()))[:3] != original[:3]:
            raise NativeFailure("The selected comparison master changed")
        while block := source.read(1024*1024):
            check_cancelled(cancelled)
            digest.update(block)
    if signature(path.stat()) != original:
        raise NativeFailure("The selected comparison master changed")
    return original, digest.hexdigest()


def packet_timeline(path, video, rate, count, cancelled):
    base = Fraction(video["time_base"])
    nal_width = length_size(video)
    result = {}
    previous_dts = None
    with packet_records(path, "v:0") as packets, path.open("rb") as source:
        for packet in packets:
            check_cancelled(cancelled)
            frame = hdr10plus_master.picture_number(packet, base, rate, count)
            pts, dts, duration = (int(packet[key]) for key in (b"pts", b"dts", b"duration"))
            if (frame in result or dts > pts or
                    (previous_dts is not None and dts-previous_dts != duration)):
                raise NativeFailure("The mixed master has a discontinuous video packet clock")
            block = sample_metadata(source, int(packet[b"pos"]), int(packet[b"size"]), nal_width)
            # The version-1 parser accounts for every variable field and
            # requires zero padding, so complete field equality binds the payload.
            if block is None or conformance_issues(block):
                raise NativeFailure("The mixed master has a missing or invalid HDR10+ payload")
            result[frame] = pts, dts, duration, block
            previous_dts = dts
    if len(result) != count:
        raise NativeFailure("The mixed master has an incomplete HDR10+ picture timeline")
    return result


def audio_packet_clock(path, cancelled):
    result = []
    with packet_records(path, "a:0") as packets:
        for packet in packets:
            check_cancelled(cancelled)
            result.append(tuple(int(packet[key]) for key in (b"pts", b"dts", b"duration")))
    return result


def verify_master(reference, candidate, state, count, work, cancelled):
    rate = timing.rate(state["output"]["fps"])
    program = SimpleNamespace(fps=rate, frames=range(count))
    result = compare_project(reference, candidate, program, work, cancelled)
    expected_samples = timing.sample_at(count, rate)
    if (not result["passed"] or result["per_frame_psnr_db"] != ["inf"]*count or
            result["decoded_pq_psnr_db"] != "inf" or not result["exact_decoded_pcm"] or
            result["audio_endpoint_samples"] != expected_samples):
        raise NativeFailure("The mixed output did not match every decoded picture and audio sample")
    before, _ = hdr10plus_export.media(reference)
    after, _ = hdr10plus_export.media(candidate)
    expected = packet_timeline(reference, before, rate, count, cancelled)
    actual = packet_timeline(candidate, after, rate, count, cancelled)
    if actual != expected:
        raise NativeFailure("The mixed output changed video packet clocks or HDR10+ payloads")
    if audio_packet_clock(candidate, cancelled) != audio_packet_clock(reference, cancelled):
        raise NativeFailure("The mixed output changed the AAC packet clock")
    return {"verifiedFrames": count, "verifiedHdr10PlusFrames": count, "verifiedAudioSamples": expected_samples,
            "x265PoolWorkers": 2}


def export_mixed_editor(state, destination, reference, runtime, scratch, *, publish, fallback, progress, cancelled):
    """Keep the candidate private until both existing and all-picture checks pass."""
    destination = Path(destination)
    reference = Path(reference).resolve()
    receipt = {"verificationPolicy": VERIFICATION_POLICY}
    publishing = False

    try:
        check_cancelled(cancelled)
        protect_comparison_master(destination, reference)
        output = state["output"]
        profile = (output["width"], output["height"], timing.rate(output["fps"]), output.get("encoder"),
                   output.get("preset"), output.get("crf"), output.get("bitrate"))
        if profile != (3840, 2160, 60, "libx265", "slow", 20, 60):
            raise NativeFailure("Mixed GPU rendering requires UHD60 Slow CRF 20 and the 60 Mb/s project setting")
        count = hdr10plus_master.preflight(state)
        if not 2 <= count <= MAX_FRAMES:
            raise NativeFailure(f"Mixed GPU rendering is limited to {MAX_FRAMES} pictures")
        video, audio = hdr10plus_export.media(reference)
        if ((video.get("width"), video.get("height"), video.get("time_base"), video.get("duration_ts"),
             video.get("nb_frames"), Fraction(video["avg_frame_rate"])) !=
                (3840, 2160, "1/120000", 2000*count, str(count), 60) or
                (audio.get("time_base"), audio.get("duration_ts")) != ("1/48000", timing.sample_at(count, 60))):
            raise NativeFailure("The comparison master does not match the mixed project's dimensions or clocks")
        reference_pin = master_identity(reference, cancelled)
        flat = sequences.playback(state)
        sources = source_snapshot(flat, include_hidden_audio=True)
        authoring = author_options(runtime/"hdr-statistics.dll")
        with tempfile.TemporaryDirectory(prefix="mixed-editor-", dir=scratch, ignore_cleanup_errors=True) as directory:
            work = Path(directory)
            candidate = work/"candidate.mp4"
            native = export_native(state, candidate, None, runtime/"VlogCraftProject.exe", runtime,
                                   authoring=authoring, first_time=True, camera_range=True, qualification=True,
                                   camera_raster=True, mixed=True, fast_raster=True, parallel_x265=False,
                                   timeout=max(600, 5*count), cancelled=cancelled, progress=progress,
                                   diagnostics=work/"diagnostics", scratch=work, publish=os.replace)
            if native.get("delivered_backend") != "mixed-d3d11-zimg-managed":
                raise NativeFailure("The mixed GPU renderer did not produce a verified candidate")
            progress(99, "Comparing every picture, HDR10+ payload and audio sample")
            receipt.update(verify_master(reference, candidate, state, count, work, cancelled))
            if master_identity(reference, cancelled) != reference_pin:
                raise NativeFailure("The selected comparison master changed")
            if source_snapshot(flat, include_hidden_audio=True) != sources:
                raise NativeFailure("An original media file changed during the export")
            protect_comparison_master(destination, reference)
            check_cancelled(cancelled)
            publishing = True
            publish(candidate, destination)
            receipt["deliveredBackend"] = native["delivered_backend"]
    except (OSError, ValueError, KeyError, RuntimeError, AssertionError, MemoryError, subprocess.SubprocessError):
        if publishing or cancelled():
            raise
        protect_comparison_master(destination, reference)
        fallback()
        receipt = {"verificationPolicy": VERIFICATION_POLICY, "deliveredBackend": "reference"}
    return receipt
