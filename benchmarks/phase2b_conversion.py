"""Bounded experimental Main10 conversion stages for the Windows render lab."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from pathlib import Path
import subprocess
from threading import Timer
import time


PQ_TAGS = "setparams=range=limited:color_primaries=bt2020:color_trc=smpte2084:colorspace=bt2020nc"


def packed_encoder(reference):
    """Feed limited-range 10-bit planar YUV into the unchanged x265 settings."""
    command = reference.copy()
    command[command.index("-pixel_format") + 1] = "yuv420p10le"
    command[command.index("-vf") + 1] = "setsar=1," + PQ_TAGS
    return command


def raw_converter(reference, target="pipe:1"):
    """Take the same zimg graph as the frozen encoder and emit raw Main10 frames."""
    decode_end = reference.index("-i")
    filter_index = reference.index("-vf")
    return [
        *reference[:decode_end], "-probesize", "32", "-analyzeduration", "1", "-fpsprobesize", "0",
        "-threads", "1", *reference[decode_end:decode_end + 2],
        "-map", "0:v:0", "-vf", reference[filter_index + 1], "-filter_threads", "1",
        "-c:v", "rawvideo", "-threads:v", "1", "-fps_mode", "passthrough",
        "-flush_packets", "1", "-f", "rawvideo", str(target),
    ]


def convert_frame(worker, picture, output_bytes):
    started = time.perf_counter()
    worker.stdin.write(picture)
    worker.stdin.flush()
    converted = worker.stdout.read(output_bytes)
    if len(converted) != output_bytes:
        raise ValueError("The conversion worker ended before emitting a complete picture")
    return converted, time.perf_counter() - started


def relay(producer, encoder, reference, stage: Path, frames, width, height, slots, timeout):
    """Keep at most one picture per worker and emit results on the source clock."""
    if not 2 <= slots <= 4:
        raise ValueError("The lab allows two to four conversion workers")
    started = time.perf_counter()
    input_bytes = width * height * 12
    output_bytes = width * height * 3
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    workers, logs = [], []
    times = []

    def stop():
        for child in (encoder, *workers, producer):
            if child.poll() is None:
                child.kill()

    timer = Timer(timeout, stop)
    timer.daemon = True
    timer.start()
    pool_started = time.perf_counter()
    try:
        command = raw_converter(reference)
        for index in range(slots):
            log = (stage / f"converter-{index}.log").open("wb")
            logs.append(log)
            workers.append(subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                            stderr=log, creationflags=flags))
        setup_seconds = time.perf_counter() - pool_started
        with ThreadPoolExecutor(max_workers=slots) as pool:
            pending = []

            def emit():
                picture, elapsed = pending.pop(0).result(timeout=max(.01, timeout - (time.perf_counter() - started)))
                encoder.stdin.write(picture)
                times.append(elapsed)

            try:
                for index in range(frames):
                    if len(pending) == slots:
                        emit()
                    picture = producer.stdout.read(input_bytes)
                    if len(picture) != input_bytes:
                        raise ValueError("The compositor did not emit a complete float picture")
                    pending.append(pool.submit(convert_frame, workers[index % slots], picture, output_bytes))
                while pending:
                    emit()
                if producer.stdout.read(1):
                    raise ValueError("The compositor emitted excess picture data")
                encoder.stdin.close()
                for worker in workers:
                    worker.stdin.close()
                for worker in workers:
                    if worker.wait(timeout=max(.01, timeout - (time.perf_counter() - started))):
                        raise RuntimeError("A PQ conversion worker failed at end of stream")
            except BaseException:
                stop()
                raise
        return {"workers": slots, "worker_setup_seconds": setup_seconds, "frame_seconds": times}
    finally:
        timer.cancel()
        timer.join()
        for worker in workers:
            if worker.poll() is None:
                worker.kill()
            worker.wait(timeout=10)
            with suppress(BrokenPipeError):
                worker.stdin.close()
            worker.stdout.close()
        for log in logs:
            log.close()
