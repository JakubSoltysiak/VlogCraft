"""Finite source-clock test path for changing decoded pictures."""
from bisect import bisect_right
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from fractions import Fraction
import json
from pathlib import Path
import re
import struct
import subprocess
import time

import numpy as np

if __package__:
    from .render_phase2 import call, source_picture
else:
    from render_phase2 import call, source_picture


CREATE_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)
LINEAR = "zscale=threads=1:agamma=0:p=2020:t=linear:m=gbr:r=full:npl=100"
SDR = "setparams=range=limited:color_primaries=bt709:color_trc=bt709:colorspace=bt709"
PACK_SLOT_MASK = struct.Struct("<I")


def select_pictures(ticks, base, in_point, fps, count):
    """Select the latest original PTS at or before each exact sequence time."""
    if not ticks or any(current <= prior for prior, current in zip(ticks, ticks[1:])):
        raise ValueError("This decoder requires strictly increasing timestamps")
    if base <= 0 or in_point < 0 or fps <= 0 or count < 1:
        raise ValueError("Invalid source clock or range")
    first_tick = ticks[0] + in_point / base
    last_tick = first_tick + Fraction(count - 1, fps) / base
    if last_tick >= ticks[-1]:
        raise ValueError("There is no following source picture to validate the requested range")
    return tuple(bisect_right(ticks, first_tick + Fraction(index, fps) / base) - 1
                 for index in range(count))


def fit_dimensions(width, height, canvas_width, canvas_height):
    scale = min(Fraction(canvas_width, width), Fraction(canvas_height, height))
    return max(2, int(width * scale) // 2 * 2), max(2, int(height * scale) // 2 * 2)


class Source:
    def __init__(self, filename, in_point, scenario, frames):
        self.path = filename.resolve(strict=True)
        self.in_point = in_point
        interval = in_point + Fraction(frames, scenario.fps) + 2
        fields = ("stream=width,height,codec_name,pix_fmt,time_base,sample_aspect_ratio,color_space,color_range,"
                  "color_primaries,color_transfer:stream_side_data=rotation:frame=best_effort_timestamp")
        started = time.perf_counter()
        observed = json.loads(call(["ffprobe", "-v", "error", "-select_streams", "v:0",
                                    "-read_intervals", f"%+{float(interval):.8f}", "-show_entries",
                                    fields, "-of", "json", self.path], 60).stdout)
        video, = observed["streams"]
        identity = tuple(video.get(key) for key in ("color_primaries", "color_transfer", "color_space"))
        if (video["codec_name"] not in ("h264", "hevc") or
                identity not in (("bt709", "bt709", "bt709"), ("bt2020", "smpte2084", "bt2020nc")) or
                video.get("color_range") not in ("tv", "pc") or
                video.get("sample_aspect_ratio") not in (None, "1:1", "N/A") or
                video["pix_fmt"] not in ("yuv420p", "yuv420p10le", "p010le")):
            raise ValueError("Unsupported live codec or explicit SDR/PQ color contract")
        ticks = tuple(int(frame["best_effort_timestamp"]) for frame in observed["frames"])
        base = Fraction(video["time_base"])
        self.selected = select_pictures(ticks, base, in_point, scenario.fps, frames)
        self.expected_ticks = ticks[:self.selected[-1]+1]
        self.base = base
        rotation = next((row["rotation"] for row in video.get("side_data_list", []) if "rotation" in row), 0)
        if rotation % 90:
            raise ValueError("Only right-angle source rotation is supported")
        width, height = video["width"], video["height"]
        coded_dimensions = [width,height]
        if rotation % 180:
            width, height = height, width
        self.width, self.height = fit_dimensions(width, height, scenario.width, scenario.height)
        self.canvas_width, self.canvas_height = scenario.width, scenario.height
        self.frame_bytes = self.width * self.height * 12
        frame_gaps = {b - a for a,b in zip(ticks, ticks[1:])}
        self.stats = dict(codec=video["codec_name"], pixel_format=video["pix_fmt"], transfer=identity[1],
                          time_base=str(base), variable_presentation_gaps=len(frame_gaps) > 1,
                          source_pictures_used=len(set(self.selected)),
                          source_indices=list(self.selected if frames<=10 else self.selected[:8]+self.selected[-2:]),
                          source_in_seconds=str(in_point), decoded_width=self.width, decoded_height=self.height,
                          coded_dimensions=coded_dimensions,
                          source_probe_seconds=time.perf_counter()-started)
        self.process = None
        self.position = -1
        self.read_seconds = 0.
        self.pack_seconds = 0.
        self.transferred_bytes = 0

    def start(self, log):
        self.log_path = Path(log.name)
        arguments = ["ffmpeg", "-v", "info", "-nostats", "-nostdin", "-xerror", "-copyts",
                     "-threads", "2", "-i", str(self.path),
                     "-map", "0:v:0", "-an", "-sn", "-dn", "-filter_threads", "1",
                     "-vf", f"showinfo=checksum=0,{LINEAR}:w={self.width}:h={self.height},format=gbrpf32le",
                     "-fps_mode", "passthrough", "-frames:v", str(self.selected[-1]+1),
                     "-c:v", "rawvideo", "-threads:v", "1", "-flush_packets", "1", "-f", "rawvideo", "pipe:1"]
        self.process = subprocess.Popen(arguments, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                        stderr=log, creationflags=CREATE_FLAGS)

    def picture(self, wanted):
        if wanted<=self.position:
            raise ValueError("Live textures only accept new decoded pictures")
        started = time.perf_counter()
        while self.position < wanted:
            raw = self.process.stdout.read(self.frame_bytes)
            if len(raw) != self.frame_bytes:
                raise ValueError("The decoder ended before the selected original PTS")
            self.position += 1
        self.read_seconds += time.perf_counter() - started
        started = time.perf_counter()
        green, blue, red = np.frombuffer(raw, dtype="<f4").reshape(3,self.height,self.width)
        picture = np.zeros((self.canvas_height,self.canvas_width,4),dtype="<f4")
        picture[...,3] = 1.
        y = (self.canvas_height-self.height)//2
        x = (self.canvas_width-self.width)//2
        area = picture[y:y+self.height,x:x+self.width]
        area[...,0], area[...,1], area[...,2] = red, green, blue
        self.pack_seconds += time.perf_counter() - started
        self.transferred_bytes += picture.nbytes
        return picture

    def report(self):
        trace = self.log_path.read_bytes()
        sizes = re.findall(rb"Parsed_showinfo[^\n]+config in time_base:\s*(\d+/\d+)",trace)
        stamps = tuple(int(x) for x in re.findall(rb"Parsed_showinfo[^\n]+?\bn:\s*\d+\s+pts:\s*(-?\d+)",trace))
        if (not sizes or Fraction(sizes[0].decode())!=self.base or
                stamps[:len(self.expected_ticks)]!=self.expected_ticks):
            raise ValueError("Live decoder timestamps do not match the original presentation index")
        return dict(self.stats, decoded_pictures=self.position+1,
                    original_pts_verified=True,
                    decoder_read_wait_seconds=self.read_seconds, rgba_pack_seconds=self.pack_seconds,
                    update_bytes=self.transferred_bytes)


class LiveInputs:
    def __init__(self, paths, offsets, scenario, frames, parallel=False):
        self.sources = [Source(path, offset, scenario, frames) for path,offset in zip(paths,offsets,strict=True)]
        self.scenario = scenario
        self.frames = frames
        self.parallel = parallel
        self.logs = []

    def start(self, folder):
        for index,source in enumerate(self.sources):
            log = (folder/f"decoder-{index}.log").open("wb")
            self.logs.append(log)
            source.start(log)

    def write(self, stream):
        with stream, ExitStack() as resources:
            readers = resources.enter_context(ThreadPoolExecutor(max_workers=2)) if self.parallel else None

            def update(slots, index):
                tasks = [(self.sources[slot],self.sources[slot].selected[index]) for slot in slots]
                if readers:
                    frames = [readers.submit(source.picture,frame) for source,frame in tasks]
                    pictures = (pending.result() for pending in frames)
                else:
                    pictures = (source.picture(frame) for source,frame in tasks)
                for picture in pictures:
                    stream.write(memoryview(picture).cast("B"))

            try:
                update(range(len(self.sources)),0)
                stream.write(memoryview(source_picture(self.scenario,2)).cast("B"))
                for index in range(1,self.frames):
                    slots = [slot for slot,source in enumerate(self.sources)
                             if source.selected[index] != source.selected[index-1]]
                    stream.write(PACK_SLOT_MASK.pack(sum(1<<slot for slot in slots)))
                    update(slots,index)
                for source in self.sources:
                    if source.process.stdout.read(1) or source.process.wait(timeout=10):
                        raise ValueError("The decoder did not finish on the requested source range")
            except BaseException:
                self.terminate()
                raise
        return [source.report() for source in self.sources]

    def terminate(self):
        for source in self.sources:
            if source.process and source.process.poll() is None:
                source.process.kill()

    def close(self):
        for source in self.sources:
            if source.process:
                source.process.wait(timeout=10)
                source.process.stdout.close()
        for log in self.logs:
            log.close()


def generated_sources(stage, scenario, frames, *, only_sdr=False):
    """Make changing H.264 SDR VFR and HEVC PQ source files with separate audio."""
    duration = (frames+24)/scenario.fps
    paths = []
    for index in range(1 if only_sdr else 2):
        width = scenario.width if index else scenario.width//2
        height = scenario.height if index else scenario.height//2
        name = stage/f"video-{index}.mp4"
        base = ["ffmpeg","-v","error","-nostdin","-f","lavfi","-i",f"testsrc2=s={width}x{height}:r=60",
                "-f","lavfi","-i",f"sine=frequency={433+302*index}:sample_rate=48000",
                "-map","0:v:0","-map","1:a:0","-t",f"{duration:.8f}","-filter_threads","1"]
        if index:
            filters = SDR+",zscale=threads=1:p=2020:t=smpte2084:m=2020_ncl:r=limited:npl=100,format=yuv420p10le,hflip"
            codec = ["-c:v","libx265","-x265-params","pools=2:frame-threads=1",
                     "-color_primaries","bt2020","-color_trc","smpte2084","-colorspace","bt2020nc"]
        else:
            filters = SDR+",select=not(eq(mod(n\\,5)\\,2))"
            codec = ["-c:v","libx264","-threads:v","2","-color_primaries","bt709","-color_trc","bt709",
                     "-colorspace","bt709"]
        call([*base,"-vf",filters,*codec,"-preset","ultrafast","-fps_mode","vfr","-color_range","tv",
              "-c:a","aac",name],180)
        paths.append(name)
    return paths


def mixed_audio(paths, offsets, samples, target):
    args=["ffmpeg","-v","error","-nostdin"]
    graph=[]
    for index,(path,offset) in enumerate(zip(paths,offsets,strict=True)):
        audio=json.loads(call(["ffprobe","-v","error","-select_streams","a:0","-show_entries",
                               "stream=index","-of","json",path],30).stdout)["streams"]
        if not audio:
            raise ValueError("This live mix requires audio in both sources")
        args.extend(("-i",path))
        graph.append(f"[{index}:a:0]aresample=48000,atrim=start_sample={round(offset*48000)},"
                     f"asetpts=PTS-STARTPTS,apad,atrim=end_sample={samples}[a{index}]")
    graph.append(f"[a0][a1]amix=inputs=2:weights='0.8 0.35':normalize=0,"
                 f"atrim=end_sample={samples}[mix]")
    call([*args,"-filter_complex",";".join(graph),"-map","[mix]","-ac","2","-c:a","pcm_s16le",target],60)
