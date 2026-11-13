# Engine measurements — architecture investigation, 13 November 2026

Generated sources only. No personal footage, paid endpoint, cloud processing or camera calibration was used. The owner intends to provide a camera folder; no path was available for this qualification. [Audit](ARCHITECTURE_AUDIT.md), [decision](ARCHITECTURE_DECISION.md), [raw sanitized records](benchmarks/2026-11-13) and [reproduction commands](#reproduction) accompany these numbers.

## Environment and interpretation

Windows 11 Pro build 26300, Ryzen AI 9 HX 370, 24 logical CPUs, 33,413,771,264 physical RAM bytes, Radeon 890M driver 32.0.32015.7029 (18 October 2026). One workstation, ordinary desktop environment; CPU/GPU power/thermal and OS file cache not controlled. Timed jobs ran sequentially without another benchmark/build running. Results are short runs with variation, not certified worst-case rates.

Production and lab FFmpeg report 9.0.2. The native experiment links the isolated shared SDK; MLT is Shotcut 26.9.27 portable, melt 7.41.0. Zig 0.17.1 built the C++17 D3D11 slice. Pinned archive hashes are in tools/setup_architecture_lab.py and exact native source/binary hashes in comparison-current.json. No globally installed development tool or new product runtime is required for normal editing.

Process-tree sampling is about 100 ms: brief children/allocations can be missed. “Summed working set” can count shared pages more than once. Windows process read/write bytes include pipes/sockets and are **not physical SSD I/O**. PDH engine utilization was near zero even in verified GPU work: preserve raw readings but treat decoder/encoder occupancy as unqualified. GPU memory is reported separately. There is no physical display probe, acoustic loopback, ETW disk trace or calibrated HDR measurement.

## Matched video-only comparison

Three independently encoded moving 3840×2160 H.264/AAC sources, six seconds each, 60/1, GOP 60, three B frames, CRF 20, BT.709. Layers use the same static position, half-size overlay geometry and alpha (1, .75, .75). Every engine decodes full original frames. Output is either 960×540 or 3840×2160; **no proxies, audio, title, mask, LUT, animated transform, export encode or display** in this comparison.

FFmpeg executes a real serial filter graph and counts processed images. MLT calls mlt_frame_get_image through the real C ABI; its image-less null consumer is deliberately not used. Native processes NV12/P010 surfaces, blends to RGBA16_FLOAT and waits for GPU completion after each frame. Thus these are completed image workloads, not queued shader calls. MLT uses RGBA8 here; its separate RGBA64 check below establishes precision capability.

Each cell is full-process FPS median, then observed min–max across three repetitions. 540p runs process 180 frames; 4K runs process 60 frames. Startup is included, including Python loading for MLT. Full process wall ends after resource-monitor teardown. Native internal processing-only rates in raw records exclude different overhead; do not compare them to this table as the same metric.

| Output / streams | FFmpeg software | MLT CPU image pull | Native HW resident | Native HW download/upload | Native SW decode/upload |
|---|---:|---:|---:|---:|---:|
| 540p / 1 | 75.65 (67.13–76.27) | 18.51 (11.16–19.02) | 210.60 (175.05–230.30) | 116.26 (114.75–119.72) | 63.54 (63.49–63.54) |
| 540p / 3 | 33.12 (33.01–33.21) | 6.63 (6.54–6.65) | 85.34 (76.96–97.30) | 38.55 (38.48–39.37) | 21.24 (20.98–21.36) |
| 4K / 1 | 67.92 (65.73–71.39) | 24.33 (22.74–24.51) | 135.69 (113.72–140.62) | 80.61 (80.12–82.25) | 51.52 (50.97–51.52) |
| 4K / 3 | 18.92 (16.96–19.12) | 6.45 (6.28–6.59) | 60.91 (51.86–61.07) | 31.50 (29.69–31.66) | 18.65 (18.24–18.79) |

All 60 invocations completed their required frames. The earlier complete run, before adding presentation/high-bit software controls, measured 4K/three-layer medians 16.72 / 5.61 / 53.02 / 26.09 / 15.77 FPS respectively. Both records are retained: run-to-run conditions and startup have material influence. Native 4K60 is promising but not a demonstrated sustained minimum.

Picture check: first/last matched generated frames versus FFmpeg had native RGB mean absolute error 1.96–2.01 levels and MLT 2.46–2.50 on an 8-bit scale; about 90% of pixels were within 8. Chroma reconstruction/resampling differs. All generated comparison pictures were visually inspected. This is static image correctness, not full effect/color/alpha or frame-timing parity. A production migration requires tighter documented tolerances and appropriate linear-light color tests.

MLT's separate four-worker CLI rawvideo consumer took 23.48–27.54 seconds for the requested 180-frame three-layer case. The direct C ABI table is the primary frame-counted comparison; no claim of a fast MLT null sink is made. MLT 7.42 placebo GPU processing was not benchmarked.

## Direct presentation and continuous transport

| Experiment | Actual result | Qualification limit |
|---|---|---|
| A: production video graph → RGBA pipe → localhost → WebGL2 canvas, 3 original4K layers → 540p, 120 frames | Three runs: first canvas .284–.309 s; total 4.003–4.088 s; 29.35–29.98 completed canvas FPS. First-frame upload readback MAE 0.0. No temporary encoded video. | Video-only unpaced throughput; CPU composition and RGBA copies remain. No A/V clock or physical-display FPS. |
| A complex path: rotations, LUT and top ellipse mask, 24 frames | First canvas .469 s; 2.410 s total; 9.96 FPS; upload MAE 0.0 | Not comparable to the static native workload. Equivalent advanced native/MLT effects are missing. |
| C: visible D3D11 SDR child surface alongside WebView2, 3 original4K layers → 540p | First ready .338 s; 120 Present calls, DXGI count 119, application call rate after first 57.72 FPS, DXGI rate 58.51; WebView produced 158 callbacks | Two-second video-only proof. Last queued Present does not automatically mean a dropped picture. 114 late source frames and per-frame fence waits: no gap-free 60 FPS claim. |
| C: original HEVC10 3840×2160 at 60000/1001 | 180 frames decoded/composed into float16; capture succeeded | No full VFR/seek/audio/HDR qualification. Capture/debug throughput is not a headline comparison. |

Native measured 1.942 s GPU completion wait versus .0383 s in Present calls. A bounded asynchronous ring is the next concrete change. The prototype is not enabled in the editor.

## Isolated production optimizations

### Opaque full-frame export

Same generated historical 4K60 source, three-second original-resolution export, 35 Mbps, veryfast, libx264. Three repetitions per version, 180 decoded frames each. Baseline 3.4.4 median **7.325873 s** (7.253156–7.327307); guarded fastpath **6.101490 s** (6.025161–6.154562), a **16.7% wall-time reduction**. These were sequential before/after sets, not randomized/interleaved trials. Do not generalize to layered/alpha/masked projects. Retaining old metadata without the new format/SAR fields safely disables the fastpath.

Baseline staged rendering attributed roughly 6.57–6.89 s to video, .07–.18 to audio, .12–.24 to mux and .19–.20 to final concat. Splitting audio/video remains essential to the historical stall repair.

### Range-dependent program cache

Same three independent original4K sources, six-second program range and an unrelated caption edited at 16 seconds. Old first preparation 12.973126 s; unrelated edit **12.716990 s** and a new render. New first preparation 12.853892 s; unrelated edit **.001731 s** and the same cache ID. The resulting MP4 bytes were identical. This is one paired integration trial, not a throughput gain for cache misses.

Unit checks additionally cover changed source/proxy identity, nesting, solo context, offline proxy compatibility, persisted manifests, tampered output, eviction and source protection. The budget covers complete program files across restarts; it does not cap every temporary/cache family.

### Index shutdown

The actual native app imported HEVC10, started source stepping and launched ffprobe -show_frames. Before the fix, an owned indexing child was still alive after host exit and diagnostic cleanup reaped it. After atomic registration/close/reap, the same automated native test observed no surviving child. Deterministic close-before-launch and real owned-child tests supplement this reproduction.

## Filter, service and UI profiles

120 original 4K60 frames, scaled to 540p; three repetitions, median process seconds, software filter threads fixed:

| Graph | Seconds |
|---|---:|
| Decode baseline | 1.723937 |
| Scale | 1.747262 |
| RGBA conversion | 1.759057 |
| Rotation | 1.775096 |
| Ellipse GEQ mask | 20.973431 |
| LUT | 2.068320 |
| Opacity | 1.817427 |
| Chroma key | 1.755089 |
| Animated primary color | 1.771885 |

These are separate filter probes, not additive stage timings. Wipe, motion analysis, stabilization, every keyframe/effect and simultaneous effects were not exhaustively profiled.

Service medians: process start .04035 s (five); probe .06772 s (five); first full HEVC PTS index 5.122 s (one), warm index lookup .0003155 s (20). Large raw MOV audio extraction .0740 s (one); original waveform .07039 s vs FLAC .06631 s (three), images not byte-identical. Project serialization .03159 s; durable save .14154 s, range .0719–.2742 (three), 1,007,796-byte 1,500-clip project. OS cache not cleared; these are not guaranteed cold-disk costs.

UI: 1,500 clips/600 seconds, 32 independently allocated generated 720p60 source files, 1440×850 viewport, 110 visible clip nodes, DPR approximately 1.0. Thirty operation samples:

| Synchronous JS operation | Median / p95 ms |
|---|---:|
| Interval index | .2 / .4 |
| Visible timeline | 4.9 / 9.7 |
| Selection | 1.9 / 2.4 |
| Zoom | 4.9 / 6.6 |
| Scroll | 6.0 / 7.8 |
| Library (32 assets) | 1.5 / 2.2 |
| Inspector | 1.7 / 2.8 |

Import/background settling was 4.196 s. Two-rAF-inclusive measurements cluster at 33.3 ms at 60 Hz; they include waiting and are not CPU time or physical input latency. Occasional spikes exist, including a 104 ms selection maximum. No browser errors. This does not qualify a 1,500-asset library, physical scrolling or 120 Hz/high-DPI behavior.

## Precision and audio capability experiments

Lossless HEVC10 ramp produced 877 distinct luma values after native hardware sampling/float16 output. Mean normalized error .0004743; software and hardware-download high-bit controls also retained 877 levels, error .0001618. MLT RGBA64 retained 877, error .001924. This proves more-than-eight-bit precision in these paths, **not HDR transfer/gamut/display correctness**.

MLT six-channel PCM pull returned 120 video frames and 96,000 audio sample frames at 48 kHz; every channel matched the generated source exactly (mean PCM error 0.0). Two seconds of channel preservation is not long synchronization, Atmos, object metadata or integrated multichannel routing.

## Sustained tests

The 70-second source smoke used 1,500 clips/600 seconds across **32 distinct two-second 720p60 recordings**, not 1,500 independent recordings or native4K sources. The 540p composited monitor averaged 52.04 callbacks/s; browser totals 4,165 frames with 548 drops, .0889 s measured buffering, 1.953 s initial preparation, 1,331.2 MiB peak summed working set, no browser errors and ten complete files/49,709,854 bytes. Original sources, no proxies. Dropped frames remain a blocker. Installed full-sequence and long-render results are recorded in VERIFICATION.md after completion.

Browser quality counters count decoder/presentation behavior of one composed stream; callbacks can be coalesced or obscured. They are not panel scanout measurements. Meter activity demonstrates non-silence, not measured audible clock drift.

## Failed or limited experiments

- An early MLT comparison accidentally included post-loop seeks in total throughput. It was rejected and all configurations rerun with seeks disabled; first uncached seeks were seconds, a repeated seek about .042 s, not comparable to fresh native process startup.
- MLT relocation under Python initially could not find avformat module data. Explicit DLL-directory/data environment setup resolved it. No empty framework startup is counted as decoding.
- Software/download native controls initially reduced HEVC10 to NV12. They were changed to preserve P010 and the precision test rerun; current-source comparisons are separately retained.
- FFmpeg raw-page inline JavaScript initially failed syntax preflight. It was corrected; only completed canvas runs are reported.
- Native per-frame fences verify finished GPU work but serialize the pipeline. The display proof exposes this limitation rather than counting submissions as presentation.
- Offline visual regression initially failed because historical control references used another DPI capture configuration. Expected controls were regenerated from the independently verified installed 3.4.4 binary under explicit DPR1, inspected, and both baseline and changed source passed at unchanged pixel tolerance.
- The installed PyInstaller executable does not load the optional Python sitecustomize socket guard. Browser proxy/routing blocks still apply. Source Python is guarded; neither is an OS-firewall/physically disconnected qualification.
- Current candidate comparison omits equivalent advanced effects/audio; no performance winner is declared for those missing scenarios.

## Reproduction

Use Windows x64, Python 3.11 with packaging/requirements.txt, Node 22, FFmpeg/FFprobe 9.0.2. No private media needed. These commands create substantial ignored local tools/media; no binaries are uploaded.

~~~powershell
python tools/setup_architecture_lab.py --build-native
python benchmarks/compare_engines.py build/qa/architecture/media build/qa/architecture/comparison-current
python benchmarks/precision_audio.py build/qa/architecture/precision-audio-final
python experiments/native_d3d11/host.py build/qa/architecture/native-host-final build/qa/architecture/media/h264-4k60-0.mp4 build/qa/architecture/media/h264-4k60-1.mp4 build/qa/architecture/media/h264-4k60-2.mp4
python experiments/ffmpeg_raw.py --help
python benchmarks/ui_profile.py .venv/Scripts/python.exe build/qa/architecture/distinct-media build/qa/architecture/ui
python benchmarks/distinct_playback.py .venv/Scripts/python.exe build/qa/architecture/distinct-media build/qa/architecture/playback --seconds 660 --until-end
python benchmarks/long_render.py build/qa/architecture/distinct-media build/qa/architecture/long-render
python -m unittest discover -s tests -p "test_*.py" -v
node --test tests/timeline_commands.test.js
~~~

The original4K corpus generator and command details are in benchmarks/README.md. First-frame timestamps differ by endpoint: FFmpeg output, native completed frame, canvas readback or ready program media. Cold source-index build, warmed lookup, cached program seek and uncached range preparation must remain separately labeled. Unavailable metrics are missing, never nominal FPS substitutions.
