"""Opt-in, exact final-picture authoring using a larger pipe and native histograms."""
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
import ctypes
from functools import partial
import os
from pathlib import Path

import numpy as np

from hdr10plus_authoring import decoded_frames, serialize, summarize


@contextmanager
def windows_output_pipe(size=1024*1024):
    """An anonymous Windows pipe sized for bulk reads, with no named endpoint."""
    import _winapi
    import msvcrt

    reader, writer = _winapi.CreatePipe(None, size)
    try:
        with ExitStack() as stack:
            descriptor = msvcrt.open_osfhandle(reader, os.O_BINARY | os.O_NOINHERIT | os.O_RDONLY)
            reader = None
            source = stack.enter_context(os.fdopen(descriptor, "rb", buffering=1024*1024))
            descriptor = msvcrt.open_osfhandle(writer, os.O_BINARY | os.O_NOINHERIT | os.O_WRONLY)
            writer = None
            sink = stack.enter_context(os.fdopen(descriptor, "wb", buffering=0))
            yield source, sink
    finally:
        for handle in (reader, writer):
            if handle is not None:
                _winapi.CloseHandle(handle)


class NativeStatistics:
    def __init__(self, library):
        self.library = ctypes.CDLL(str(Path(library).resolve(strict=True)))
        self.analyze = self.library.hdr_maxrgb_histogram
        self.analyze.argtypes = (ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p)
        self.analyze.restype = ctypes.c_int

    def payload(self, frame):
        frame = np.ascontiguousarray(frame, dtype="<u2")
        if frame.ndim != 3 or frame.shape[0] != 3:
            raise ValueError("The native analysis accepts planar GBR16")
        pixels = frame.shape[1]*frame.shape[2]
        histogram = np.empty(65536, dtype=np.int64)
        maxima = np.empty(3, dtype=np.uint16)
        if not self.analyze(frame.ctypes.data, pixels, histogram.ctypes.data, maxima.ctypes.data):
            raise ValueError("The native analysis rejected this picture")
        return serialize(summarize(histogram, maxima, pixels))

    def records(self, frames, workers):
        if workers == 1:
            for frame in frames:
                yield self.payload(frame)
            return
        if not 2 <= workers <= 4:
            raise ValueError("The analysis worker budget is one to four")
        pending = deque()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            try:
                for frame in frames:
                    pending.append(pool.submit(self.payload, frame))
                    if len(pending) == workers:
                        yield pending.popleft().result()
                while pending:
                    yield pending.popleft().result()
            finally:
                for item in pending:
                    item.cancel()


def author_options(library=None, workers=1, *, large_pipe=True):
    options = {}
    if large_pipe:
        options["frame_source"] = partial(decoded_frames, output_pipe=windows_output_pipe)
    if library:
        statistics = NativeStatistics(library)
        options["picture_records"] = partial(statistics.records, workers=workers)
    return options
