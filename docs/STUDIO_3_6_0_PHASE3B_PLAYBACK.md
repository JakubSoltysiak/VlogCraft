# VlogCraft Studio 3.6.0 Phase 3B playback and editing

The starting point was Phase 3A at [f4a852b](https://github.com/JakubSoltysiak/VlogCraft/commit/f4a852ba36d9cd6e417c2cbfd1dc90af1ad2d630). [Draft PR #21](https://github.com/JakubSoltysiak/VlogCraft/pull/21) targets the Phase 3A branch. Windows results use the development MSI applications on the Radeon 890M workstation. Administrative MSI images and test projects were local and isolated from the user's active installation and projects.

## Playback architecture and reproduced problems

The native worker selects original source frames using rational timeline and source timestamps, decodes through libav with bounded queues, and composites with D3D11. The preview clock is driven by 48 kHz reference PCM played through an AudioWorklet. The WebView owns editor state and sends seek generations to the desktop host. Unsupported native effects and color contracts retain the existing explicit fallback. Neither the native export provider nor HDR10+ authoring changed here.

[Issue #9](https://github.com/JakubSoltysiak/VlogCraft/issues/9) describes an older Live Layers session with mixed 4K footage, images and proxy generation. The Phase 3A installed controls reproduced slow final-picture delivery when dragging a long native timeline. Intermediate pointer updates entered the full recovery bridge and could restart FFmpeg PCM while the decoder was also seeking. In active playback, incoming clock updates could temporarily move the visible playhead behind the intended drag position.

The earlier [3.4.9 reliability report](RELIABILITY_MEMORY_3_4_9.md) recorded a 4.629 s presentation gap in a trial with window-condition failures, 657 underruns in a separate memory diagnostic, and roughly 10.976 MiB/min of late WebView private-commit growth in one extended editing test. Those historical values remain separate from the current hardware measurements. Calibrated thermal telemetry was unavailable for these runs.

## Changes

- A transient ruler position updates the marker without serializing the native project signature or writing a recovery checkpoint. The release or cancellation commits the final UI position through the existing journal. Undo depth, journal schema, snapping and frame alignment retain their existing contracts.
- Native seeks hold the requested frame on the timeline until that exact GPU generation and frame complete. The seek queue retains one pending destination. A transient seek can proceed when its predecessor finishes or after a bounded 65 ms interval. A committed seek bypasses the interval and reuses the generation if its exact frame is already requested. PCM is prepared once at commit and audio is released while dragging.
- The worker publishes the first completed paused target without waiting for its regular status report. A changed generation fences an obsolete paused submission. Pending seeks read full native status without sending a redundant paused clock update. Ordinary playback keeps the full clock response and existing audio sample budgets.
- Proxy encoding retains one queued worker, the existing codec, output, cancellation and atomic rename. On Windows it now runs at below-normal priority. Quality and cache capacity were unchanged.

## Measurement method

Native throughput uses distinct submitted sequence frames, DXGI Present counters where available and the native playback-only interval distribution. The measured endpoint is the native compositor and DXGI submission. The source is 3840 × 2160 at 60 fps for the generated native playback controls. The workload tables distinguish 3840 × 2160 program composition from the 356 × 200 scaled physical monitor used by the controlled native playback benchmark. Ruler tests use a 960 × 540 program and actual WebView DPI, with Windows reporting 120 Hz in those tests. Foreground ownership, center visibility and power samples are recorded. Live Layers controls use browser video-frame callbacks and decoded/dropped counters, a separate endpoint from native presentation.

Ruler drags use actual pointer input across a 90-second project with three video and three audio tracks and 0.5-second cuts. The expected release frame is calculated from the pointer and ruler geometry. The UI timing measures synchronous `seek()` work. The picture timing measures release to exact completed-generation acknowledgement. A benchmark return code establishes its functional assertions. Qualification also considers skips and presentation gaps.

## Measured results

<!-- PHASE3B_RESULTS_START -->

### Native ruler and seeks

| Packaged editor and trial | Native requests per drag | Recovery checkpoints per drag | PCM fetches per drag | Median UI work, paused (ms) | Median release to completed picture, paused (ms) | Playing release (ms) | Playing samples with marker behind target |
|---|---:|---:|---:|---:|---:|---:|---:|
| Phase 3A | 46/37/36 | 46/46/46 | 1/4/6 | 1.90 | 433.1 | 458.3 | 5 |
| First candidate | 46/46/46 | 1/1/1 | 1/1/1 | 0.60 | 554.3 | 629.4 | 0 |
| Paced candidate | 12/7/8 | 1/1/1 | 1/1/1 | 0.10 | 554.4 | 599.2 | 0 |
| Phase 3A repeat | 39/39/42 | 46/46/46 | 5/6/3 | 1.80 | 577.3 | 675.4 | 2 |
| Final candidate | 9/7/8 | 1/1/1 | 1/1/1 | 0.10 | 506.1 | 523.7 | 0 |

The three slash-separated counts are individual paused drags. The first candidate removed repeated recovery and audio work. Decoder resets were still frequent, and the paced variant reduced request volume. Exact decoded-picture latency is measured separately from playhead work.

The matched visible AC repeat measured 577.3 → 506.1 ms median release to the completed paused picture. The playing release took 675.4 → 523.7 ms. The original Phase 3A cohort settled faster than its later repeat, so the full set of observations remains in the comparison.

| Package | First native frame (ms) | Twelve repeated seeks p50 / p95 (ms) |
|---|---:|---:|
| Phase 3A | 785.8 | 358.6 / 618.8 |
| First candidate | 1,049.0 | 517.8 / 625.9 |
| Paced candidate | 1,149.4 | 521.4 / 625.6 |
| Final candidate | 930.9 | 433.8 / 550.3 |
| Phase 3A controlled repeat | 1,059.0 | 521.5 / 657.8 |
| Final candidate controlled repeat | 938.1 | 421.1 / 559.9 |

### Native continuous playback

| Trial | Distinct FPS | Skips | Skips after source waits | Maximum active Present gap (ms) | Audio samples / underruns | Peak summed working set (MiB) | AC / visible |
|---|---:|---:|---:|---:|---:|---:|---|
| Phase 3A, 15 s 1+1 | 59.09 | 0 | 0 | 87.25 | 720000 / 0 | 1,518.3 | True / True |
| First candidate, 15 s 1+1 | 59.41 | 0 | 0 | 26.50 | 720000 / 0 | 1,507.6 | True / True |
| Phase 3A, 15 s 3+3 | 58.60 | 1 | 0 | 59.00 | 720000 / 0 | 2,773.1 | True / True |
| First candidate, 15 s 3+3 | 58.81 | 9 | 1 | 57.91 | 720000 / 0 | 2,799.9 | True / True |
| Paced candidate, 15 s 3+3 | 59.48 | 2 | 0 | 52.17 | 720000 / 0 | 2,952.0 | True / True |
| Final candidate, 15 s 3+3 | 59.03 | 1 | 0 | 48.27 | 720000 / 0 | 2,929.4 | True / True |
| Phase 3A, 60 s 3+3 | 58.95 | 47 | 23 | 106.23 | 2880000 / 0 | 3,244.7 | True / True |
| Paced candidate, 60 s 3+3 | 53.08 | 390 | 332 | 1,413.86 | 2880000 / 0 | 3,590.9 | True / True |
| Phase 3A repeat, 60 s 3+3 | 59.82 | 2 | 0 | 51.28 | 2880000 / 0 | 2,949.9 | True / True |
| Final candidate, 60 s 3+3 | 57.18 | 152 | 113 | 1,019.53 | 2880000 / 0 | 4,005.6 | True / True |
| Phase 3A, 125 s alternating three sources | 42.21 | 2212 | 2180 | 226.35 | 6000000 / 0 | 3,174.9 | True / True |
| Paced candidate, 125 s alternating three sources | 42.13 | 2226 | 2193 | 217.11 | 6000000 / 0 | 3,086.2 | True / True |

The 60-second paced run is a performance failure. It reported 390 skips, including 332 following source waits, and a 1.414-second Present gap. The Phase 3A and paced packages carried the same native worker checksum. Their mean GPU composition times were 3.48 and 3.43 ms, no skips were attributed to GPU slot waits, and exact PCM completion was observed in both. The receipt localizes the stalls to source availability in this workload, without establishing the trigger for the worst decoder delays. The table retains the failed timing.

The final repeat also failed the presentation gate at 57.18 FPS and 152 skips versus the frozen repeat's 59.82 FPS and 2 skips. The largest native event advanced past 64 pictures near frame 71 with a source-wait observation. All three prepared queues held four frames at startup, so empty initial prefill does not account for that gap. Audio clocks and endpoints remained intact. The most expensive phase inside the later source stalls remains unresolved.

The alternating-source control reproduced the bottleneck on both packages. Most skips followed source-frame waits (2,180 and 2,193). Each used one active video and one audio track, switched between three original 4K sources every half second and delivered the exact six million audio samples. The current native player drains work and can open or destroy a decoder at a source switch. The next performance gate is a bounded decoder handoff with evidence identifying which part of that transition consumes the gap.

### 150-second editing and memory

| Package | Edit batches | WebView private commit, first / last 30 s median (MiB) | Native private commit, first / last 30 s median (MiB) | Audio underruns |
|---|---:|---:|---:|---:|
| Phase 3A | 15 | 1,009.2 / 1,520.1 | 2,435.0 / 2,417.9 | 0 |
| Paced candidate | 15 | 1,004.4 / 1,036.9 | 2,372.5 / 2,369.7 | 0 |

The fixture alternates selection, seeking, scrolling, opacity edits, playback restarts and preview size changes on a 125-second generated timeline. The profiler separately records browser and renderer private commit, JavaScript heap, DOM counts and process working sets. It observes natural idle and explicit native release without forced garbage collection. Samples describe this short editing fixture and can mix allocations from different active preview sizes. They cannot establish a leak or sustained stability. GPU-allocated memory can overlap system working set.

WebView renderer private commit was 955 and 548 MiB at the end of the pair. It fell to 814 and 502 MiB after 15 seconds of natural idle. Allocation ownership within WebView and longer-term memory behavior remain open.

### Live Layers and proxy contention

| Package and job status | Decoded / dropped | Browser video callbacks | Largest callback gap (ms) | Active proxy samples |
|---|---:|---:|---:|---:|
| Phase 3A, idle | 243 / 2 | 235 | 243.9 | 0 |
| Phase 3A, proxy | 237 / 0 | 233 | 711.4 | 2 |
| Below-normal proxy candidate, idle | 241 / 0 | 236 | 167.5 | 0 |
| Below-normal proxy candidate, proxy | 247 / 0 | 243 | 292.9 | 3 |

These short browser observations include startup. They cover processing a second source in the background while Live Layers uses the original. They leave sustained contention, completed-proxy playback, and frame-accurate Live Layers versus Composited parity open.

### Windows, export, and recovery

The local loopback-only suite ran 184 Python tests with 1 optional hardware test skipped. All 32 JavaScript tests passed. The isolated Windows timeline fixture checked 32 linked assets, live 600-frame trim, zoom anchoring, undo/redo, portrait/custom dimensions and reopen. The mixed HDR fixture authored all 18 dynamic blocks and matched every decoded static-reference picture with edits and transitions retained on reopen.
The separate local WARP/export fixture passed 9 tests, including fractional timing, exact decoded PCM and a complete managed fallback after injected device failure.
The exact final JavaScript suite passed 32 tests.
The final optional development MSI and administrative image passed 48 bundle identity, runtime and icon checks.
The final packaged transport passed rapid and playing seeks, pause/resume, zero underruns, physical resize and modal alignment, and complete SDR fallback after an owned renderer failure or unsupported effect.
Both packaged WebView recovery fault injections restored all 80 undo entries and exact project and history contents, with paused position and exact undo/redo.
The final packaged first-export workflow delivered in 45.123 s. Independent checks passed all 48 HDR10+ blocks, exact 38,400-sample decoded PCM, video PTS and static HDR declarations. Decoded PQ scored 55.63 dB overall. Active cancellation and shutdown left 0 owned survivors.
The frozen local 3-second HDR preview delivered 144000 samples, 0 underruns and 0 skips with a visible scRGB surface. Display calibration remains open.
The final local 3-second HDR preview delivered 144000 samples, 0 underruns and 0 skips with a visible scRGB surface. Display calibration remains open.
All 3 originals matched their recorded hashes before and after the local camera control. No camera images, paths or identifying metadata are in this evidence.

The initial MSI administrative extraction rejected a forward-slash destination. The same MSI extracted at a canonical Windows path. The first hosted checkpoint stopped on a source-fingerprint mismatch. The Windows workflow now checks the Phase 3A record in its archived historical tree and binds this record to Phase 3B. The original failures are retained in the data.

<!-- PHASE3B_RESULTS_END -->

## Workload coverage and remaining gates

The native matrix covers single-source playback, three concurrent picture/audio tracks, repeated seeks, ruler input and independent source changes. The managed Windows editing fixture covers mixed photos, HDR video, keyframes and transitions. Longer real-world presentation measurements for that mixed timeline and for completed-proxy playback remain open. The Live Layers controls compare idle and actively encoding proxies. The editing diagnostic covers 150 seconds with repeated edits.


Phase 3B is a development checkpoint. Smooth sustained UHD60 across long live-decoded multitrack projects, a representative mixed project with active and completed proxies, calibrated HDR monitoring, and physical device recovery require further qualification. Playback varies with source readiness on an unchanged native binary, so a short run alone cannot qualify the editor. The 600-second continuous and 30-minute editing gates depend on resolving the short and representative outliers. The full 60-second matched HDR10+ **export** remains a separate release gate.

[Machine-readable evidence](benchmarks/studio-3.6.0-phase3b.json) · [Project verification](../VERIFICATION.md) · [Complete roadmap](../TODO.md)
