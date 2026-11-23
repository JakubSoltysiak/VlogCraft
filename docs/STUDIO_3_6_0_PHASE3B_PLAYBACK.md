# VlogCraft Studio 3.6.0 Phase 3B playback and editing

The starting point was Phase 3A at [f4a852b](https://github.com/JakubSoltysiak/VlogCraft/commit/f4a852ba36d9cd6e417c2cbfd1dc90af1ad2d630). [Draft PR #21](https://github.com/JakubSoltysiak/VlogCraft/pull/21) targets the Phase 3A branch. Windows results use the development MSI applications on the Radeon 890M workstation. Administrative MSI images and test projects were local and isolated from the user's active installation and projects.

Current results are in the [triggered freeze investigation](#triggered-freeze-investigation). The preceding [follow-up qualification](#follow-up-acceptance-protocol) established the comparison package. Three 125-second rapid-switch runs completed with zero skips. Two of three 60-second three-layer runs met all timing screens. The third lost 222 frames.

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

## Earlier Phase 3B measurements

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

## Follow-up acceptance protocol

The two principal controls use 3840 × 2160 source and composition, 60/1 timing, visible 356 × 200 physical preview, AC power and a fresh editor process per trial. OS file caches are unmanaged. The 60-second control has three simultaneous picture and audio layers. The 125-second control alternates three files in one picture and audio track every half second. A separate actual-layout trial records its measured panel dimensions. The native endpoint counts distinct sequence submissions and separately reports completed frames and active Present intervals.

Before final candidate measurements, we selected the existing 59.5 distinct FPS and fewer-than-30-skips screens for each short run. We also require the exact last completed frame and PCM sample count, zero underruns, held visibility and no owned survivors. A 100 ms maximum active gap is a follow-up screen for a visible freeze of six or more frame periods. The historical stricter protected skip median of 3.5 and worst of 16 remain separate reporting targets. We compare p95/p99 intervals and seek p95 using the existing 10% latency investigation threshold. A repeatable short failure gates the 600-second playback and 30-minute editing tests. Working set, private commit, decoder and texture ownership are reported separately. An additional decoder must fit its declared count and byte limits and be released on close.

### What delayed the picture

The published Phase 3B worker repeated its three-layer failure at 50.18 FPS with 572 skips and a 1.364 s active gap. The frozen Phase 3A image also had a long gap under the current visible AC conditions at 52.95 FPS, 399 skips and 1.156 s. The historical one-second event cannot be assigned uniquely to the Phase 3B seek changes.

For alternating sources, a 12-second trace of the original scheduling policy recorded 24 decoder opens for 24 clips. Probing the file's streams took a median 22.0 ms across the 23 measured cut boundaries. The first call to submit a packet to the hardware decoder took 127.5 ms at sequence frame 30 and 118.0 ms at frame 90. The previous decoder typically took about 2.8 ms to retire. Rebuilding the decoder and waiting for its first decoded picture on the cut explains the repeated missed deadlines. Sampled disk reads, seeks and flushes did not register a 2 ms event in this trace.

Keeping compatible decoders for their imminent next use reduced the 12-second diagnostic from 238 skips to 18. Sixteen of the remaining skips occurred on the first visits to the second and third sources. Preparing these sources after the current paused frame had been acknowledged brought the same diagnostic to one skip. The worker opened three decoders, resumed them 23 times, and used 870,912,000 bytes for the two standby surface arrays.

Three simultaneous layers showed a different failure. The original loop stopped checking its other active sources when the first one was late. Their four-picture queues could then fill and prevent the decoder workers from catching up. The candidate requests the target from all active sources and retains the actual PTS interval around it. In one traced 60-second run, a two-frame miss ending at frame 1807 had a 52.4 ms window. The presenter spent 51.4 ms in DXGI Present. Concurrently, decoder 2 held the shared video-device lock for 51.7 ms and the other two decoders waited for 51.8 and 52.0 ms. These are simultaneous observations. They establish the affected calls and queue behavior. The driver or scheduler trigger for every long historical gap remains unresolved.

The original policy produced another 51.8 ms Present at frame 2257 while a decoder held the shared device lock for 52.1 ms. The candidate defers a decoder refill during presentation only when at least two future pictures are already available. A hungry source, a seek and the active target keep priority. Preparation permits at most three live decoders, two idle owners, one pending cold initialization and 896 MiB of inactive decoder texture payload including reservations. Active surfaces, the four-picture reader queues, four GPU slots and existing warm cache are separate. A resident decoder can continue only across an exact compatible source boundary. Late work is fenced by seek generation. Teardown wakes the decoder workers and joins them before releasing their owners.

| Diagnostic change, same 60 s three-layer fixture | Distinct FPS | Skips | Longest active gap |
|---|---:|---:|---:|
| Wait for a swap-chain slot before submission | 57.174 | 159 | 107.29 ms |
| Serialize the whole Present against decoder work | 59.374 | 16 | 73.04 ms |
| Give Present priority over well-buffered refills | 59.652 | 13 | 59.70 ms |

The final candidate uses the third policy. In the 125-second rapid-cut experiment, reuse alone still caused a 166.86 ms first-visit gap. Adding bounded preparation delivered 59.771 FPS, zero skips and a 35.14 ms maximum gap in the next normal run. The independent four-source Windows check read back the physical preview at 23 destinations, matched FFprobe timestamps, completed 115,200 audio samples with zero underruns and cancelled during seek. It included direction changes, repeated source positions and a fourth source exceeding the pool. A separate fractional-timebase fixture reproduced the original early selection of the 500 ms picture for a request at 499.5 ms. The corrected package held the independently verified 300 ms picture until 500 ms, including after a backward cut.

The 60-second observer measures wall time through the final GUI poll. One candidate diagnostic recorded 59.010 wall FPS with eight skips and 59.847 active native Presents per second. Its observer interval exceeded the nominal minute by 854 ms. All results retain the wall measurement. The GPU-counter observer sampled on a separate thread. A control without those counters still returned 59.418 FPS, 14 skips and a 72.36 ms maximum gap. The tests do not establish that observation caused the original one-second freezes.

### Repeated three-layer controls and the source rewind

In the original three-layer fixture every picture source restarts its media span at the same sequence frame every 90 frames. The native worker retains six decoded prefix pictures per source. A held VFR picture needs its following timestamp to establish the right edge of its interval. The first five intervals can therefore be served wholly from that prefix. In the unchanged-policy detailed run, ten of twelve skipped positions belonged to gaps starting in the first eight frames after a rewind. This region covers 8.9% of the timeline. The corresponding figures were 12 of 15 in the traced preparation variant, 13 of 14 without GPU performance counters and 313 of 572 in the slowest frozen run. This locates a recurrent failure at the transition back to fresh decoded pictures.

The new package also lost 67 positions during the first 90 frames of one run, before any rewind. All three source queues started full. The 1.702 s maximum active interval in that run exceeded both its largest individual Present call (101.2 ms) and its largest GPU composition (10.0 ms). General source starvation remains a separate investigation. The original, synchronized workload retains its acceptance threshold.

The follow-up implementation now checks whether each source already holds the exact outgoing pictures needed for the final three, two or one frames before a backward cut. Only then may that source's existing decoder start seeking to the next clip. The incoming queue and outgoing tail share four slots. Every retained picture carries its original timestamp, clip and generation. A different destination invalidates the preparation. When the evidence is insufficient, the worker takes its ordinary seek path.

An isolated worker on the synchronized fixture adopted all 39 early rewinds on each of three layers in both runs. The traced result was 59.822 FPS, two skips and a 44.67 ms maximum gap. The run without native miss tracing reached 59.713 FPS, one skip and a 36.56 ms maximum. Neither recorded skips following a source wait. An offscreen hardware test independently checked 120 source/frame pairs across VFR cuts, sought backward during a pending rewind and closed the worker in 31 ms during another one. The final package repeats these checks.

The same intermediate MSI was then rerun with the original synchronized cuts and with the three source loops offset by one cut each. The traced synchronized run measured 59.507 FPS, 20 skips and a 73.50 ms maximum gap. The staggered diagnostic measured 59.829 FPS, zero skips and a 36.76 ms maximum. Each completed exactly 2,880,000 audio samples with zero underruns. This comparison changes the source offsets for diagnosis only. All protected final trials use the original timeline and source offsets.

### Consistency on the development MSI

With the native miss tracer off, the three matched frozen runs lost 5, 16 and 3 pictures in 60 seconds. The synchronized-rewind MSI lost 222, 0 and 1. Both packages passed two of three predeclared wall-time screens. Median skips improved from 5 to 1, but the worst matched result worsened from 16 to 222 and the maximum gap from 61.81 to 976.93 ms. The retained traced frozen outlier was worse still at 572 skips and 1.364 s. No run was removed for a low score.

In the 976.93 ms trial, the last submitted frame stayed at 2343 for at least 778.3 ms while source waits rose from 142 to 175 and GPU-slot waits did not increase. The first six cached source pictures give five fully bracketed VFR intervals. The stall began three frames into a source loop. Individual maxima were 102.48 ms in Present, 144.83 ms waiting for the device context and 11.81 ms of GPU composition. None explains the full missing interval on its own. Each decoder spent 7.08–7.73 s in decode over the full failing minute, versus 2.87–3.62 s in the two passing runs. Those three decoder times overlap. Windows logged no display-driver timeout, hardware-error report or critical power event in the failing trial.

All three revised 125-second rapid-cut trials delivered all 7,500 distinct pictures, with no redrawn frame needed to meet the count. The audio endpoint was exactly 6,000,000 samples in every trial. This qualifies the measured original-source switching case. Three simultaneous layers on the same machine still have an intermittent long stall.

### Windows graphics trace and actual editor size

At the ordinary editor layout the native preview measured 958 × 539 physical pixels on the 2880 × 1800, 120 Hz, 175% desktop. Both source and composition were UHD. Frozen Phase 3B measured 58.998 FPS, 30 skipped pictures and a 105.20 ms maximum gap. The new MSI measured 59.622 FPS, 11 skips and a 102.26 ms maximum gap. Both exceeded the 100 ms limit.

Two additional instrumented synchronized trials on the same MSI measured 59.645 FPS / 0 skips / 46.04 ms and 59.685 FPS / 2 skips / 52.37 ms. A separate bounded Windows graphics recording with the native miss tracer off yielded 59.626 FPS / 1 skip / 58.41 ms. It retained 828 of 3,599 native Present starts. There were 809 usable paired calls inside the conservative active range, covering about 14 seconds. Their observed p95 call time was 0.665 ms. Some intervals crossed missing events, including apparent API times longer than the worker's lifetime maximum. Three native-associated queue contexts provided 12,542 matched submission/completion pairs with a 53.0 ms p95 and 92.3 ms maximum. These queue intervals overlap. This recording did not reproduce or attribute the nearly one-second freeze. A separate partial trace had no independent worker identity.

The next diagnostic is a rolling capture triggered by a stalled last-submitted frame. Preserve device/decoder identity, requested and available PTS on all three layers, packet and device-lock ownership and GPU scheduling immediately before the stalled frame. End the capture after recovery. Keep the existing protected run, including its endpoint and observer, as the acceptance control. The 976.93 ms gap failed a prerequisite for the 600-second playback and 30-minute editing tests.

### Matched untraced native trials

Each row used a fresh process, original media, active GPU performance counters, AC power and a visible preview. The standard surface was 356 × 200. GPU execution and UMA residency have distinct accounting. Process working sets can contain overlapping mappings.

| Workload and trial | Distinct FPS | Distinct pictures after drain | Skips (after source wait) | Active p95 / p99 / maximum gap (ms) | Peak summed working set (MiB) | Gate |
|---|---:|---:|---:|---:|---:|---|
| Frozen 60 s, 1 | 59.648 | 3,595 | 5 (0) | 18.4 / 35.1 / 58.38 | 2,993.2 | passed |
| Frozen 60 s, 2 | 59.404 | 3,584 | 16 (0) | 18.6 / 34.1 / 51.05 | 3,097.4 | failed |
| Frozen 60 s, 3 | 59.608 | 3,597 | 3 (0) | 18.3 / 35.1 / 61.81 | 3,251.7 | passed |
| Revised 60 s, 1 | 56.020 | 3,378 | 222 (184) | 18.7 / 50.1 / 976.93 | 3,194.0 | failed |
| Revised 60 s, 2 | 59.824 | 3,600 | 0 (0) | 18.0 / 19.0 / 33.86 | 2,920.8 | passed |
| Revised 60 s, 3 | 59.728 | 3,599 | 1 (0) | 18.0 / 19.1 / 38.91 | 3,116.0 | passed |
| Frozen 125 s, 1 | 41.789 | 5,228 | 2,272 (2,248) | 99.5 / 255.4 / 255.42 | 3,097.0 | failed |
| Frozen 125 s, 2 | 41.805 | 5,232 | 2,268 (2,237) | 277.8 / 277.8 / 277.76 | 3,093.4 | failed |
| Frozen 125 s, 3 | 41.677 | 5,218 | 2,282 (2,255) | 99.1 / 245.6 / 245.61 | 3,056.9 | failed |
| Revised 125 s, 1 | 59.921 | 7,500 | 0 (0) | 17.8 / 18.4 / 30.81 | 2,816.2 | passed |
| Revised 125 s, 2 | 59.913 | 7,500 | 0 (0) | 17.9 / 18.6 / 34.85 | 2,851.2 | passed |
| Revised 125 s, 3 | 59.718 | 7,500 | 0 (0) | 17.9 / 18.6 / 35.19 | 2,865.9 | passed |

The 60- and 125-second trials ended on the exact final picture with 2,880,000 and 6,000,000 audio samples respectively and zero underruns. Distinct picture totals include the final drain. FPS retains the last GUI poll and its wall interval. In the second revised switch run that poll saw 7,496 pictures and the subsequent drain confirmed 7,500. Histogram percentiles are bucket upper bounds. The frozen switch control could open only one decoder at a time. The revised switch tests used three live decoders, two cold preparations and 249 resumes, with at most four pictures per source queue. The maximum standby payload was 870,912,000 bytes within a 939,524,096-byte reservation. Full process-role private commit and GPU allocations are in the measurement record. The traced and intermediate cohorts retain their own identities and results.

### Packaged Windows qualification

The earlier handoff candidate at `40e43da66797f70c57691b734effafcb34bc552a` used MSI SHA-256 `9a06324bb5ed51e49ba9fc44637f45e11321dd861c2771a4edb576799c590e0f` (286,261,349 bytes). It passed 48/48 image checks after a long-target extraction failed (Windows Installer 1603 / 1320). Its playback trials are retained separately; the 150-second editing pair compares frozen Phase 3B and the subsequent synchronized-rewind build. The checks below apply only to the subsequent synchronized-rewind candidate.

The development MSI was 286,269,541 bytes (SHA-256 `4513cef410ffe7d2fe775b0b1eec8dc86732f82dcbe9cf5d7ae30d055dd76fa0`). The x64 build produced 6 verified binaries at source `7fb4a7208e26d23e6ae6a0e15284cf48145d33a1`. The isolated administrative image passed 48/48 source, runtime and icon checks.

The packaged GPU worker held the 300 ms picture at a request of 499.5 ms, switched to the 500 ms picture at 500.0 ms and retained it at 500.5 ms. An adjacent backward cut to 400 ms returned to the red 300 ms picture. The frozen worker failed both the just-before and backward cuts. FFprobe timestamps and FP16 center-pixel readbacks independently verified these results.

The four-source seek and handoff fixture passed 23 physical color checks, verified exact held timestamps, cancelled during a pending seek and completed 115,200 PCM samples with 0 underruns. It observed at most 3 live decoders and 4 queued pictures per producer.

The packaged simultaneous-rewind fixture compared 117 active source-frame selections against independent VFR timestamps, confirmed an exact seek during pending rewind and closed the worker in 31.0 ms while another rewind was pending.

Packaged transport passed playing seeks, pause/resume, physical resize and modal visibility. An owned process failure and an unsupported effect both selected the whole reference program. This transport fixture recorded 86,486 samples after its final reposition and 0 underruns. The maximum measured window-alignment error was 0 physical pixels.

The mixed edit linked all three recordings and combined two tagged PQ originals in three one-second clips, a generated still and two scale keyframes. Its picture clips used an explicit square-pixel interpretation. The third recording has unknown primaries and transfer and remained in the library. Its 3840 × 2160 HDR project used the explicit 960 × 540 SDR Composited monitor in a 666 × 374 physical stage. The derivative contained 180 independently decoded pictures. The browser reported 179 callbacks, 0 drops and a 25.30 ms maximum callback gap. Initial import-to-ready cost was 149.75 seconds.

A separate 3-second real-camera PQ clip reached the native scRGB surface with 144,000 exact samples, 0 underruns and 0 skips. Dynamic HDR10+ data was present at decode. This checks an HDR-capable surface, with calibrated monitoring still open.

Live Layers measured browser callback delivery in separate four-second arms. The completed case checked the requested asset, proxy URL flag and decoded dimensions. Active-generation samples show how much of each observation overlapped the encoder.

| Proxy condition | Browser source | Active job samples | Callbacks | Decoded / dropped | p95 / max gap (ms) |
|---|---:|---:|---:|---:|---:|
| Idle | 3840 × 2160 | 0 (0%) | 241 | 245 / 0 | 25.20 / 209.30 |
| Active | 3840 × 2160 | 6 (43%) | 220 | 255 / 31 | 41.90 / 276.30 |
| Completed | 1280 × 720 | 0 (0%) | 253 | 253 / 0 | 17.00 / 75.40 |

Packaged WebView faults restored 80 undo states after the renderer fault (7.27 s) and 80 undo states after the browser fault (8.22 s). Each recovery checked the exact full history, tracks and output settings, unsaved draft, paused position and undo/redo.

The offline packaged first export completed in 45.521 s. Independent decoding verified 48 pictures, 48 conforming and correctly associated HDR10+ blocks, exact video PTS, static HDR declarations and 38,400 exact PCM samples (55.63 dB PQ). Active cancellation and confirmed shutdown left 0 owned survivors. The representative 60-second mixed UHD60 HDR10+ export is still a separate gate.

Regression results were loopback-only Python 191/192 passed, 1 skipped, separate WARP/export 9/9 passed, 0 skipped, JavaScript 32/32 passed.

All 3 originals matched the pre-existing hashes and modification times before and after the final camera retry. There were 0 matching Git media objects, 0 matching text objects and 0 matches in publishable working files.

The 150-second ownership diagnostic used unforced natural idle. Frozen Phase 3B observed 15 batches and 0 underruns, with final active / natural-idle renderer private commit 540.6 / 504.6 MiB. Final follow-up failed its visibility control when the preview center was covered at 132.473 s. Final follow-up (failed visibility) observed 15 batches and 0 underruns, with final active / natural-idle renderer private commit 538.1 / 480.0 MiB. Final follow-up repeat observed 15 batches and 0 underruns, with final active / natural-idle renderer private commit 541.1 / 478.1 MiB. This scope cannot establish a leak or long-session stability. Working set, private commit and potentially overlapping UMA or shared GPU allocations are distinct measurements.

Median private commit over the last 30 seconds of each 150-second editing diagnostic (MiB). A dash indicates missing owner samples.

| Build | Host | Native | WebView family | FFmpeg |
|---|---:|---:|---:|---:|
| Frozen Phase 3B | 881.3 | 2,385.8 | 1,031.1 | 1,454.1 |
| Final follow-up (failed visibility) | 886.0 | 2,396.2 | 1,035.5 | 1,350.5 |
| Final follow-up repeat | 872.9 | 2,369.9 | 1,035.1 | 1,430.9 |

Retained failed trials include final2/mixed, final2-mixed-retry/mixed, final2-mixed-geometry/mixed. The editor rejected the initial default SDR encoder for the HDR10 project and subsequently rejected an unspecified source pixel aspect. Both refusals preceded playback. With those settings corrected, a third run failed while publishing its rendered preview. Windows returned error 3 when replacing a 226-character temporary file path with a 268-character cache path. The frozen Phase 3B and the follow-up contain identical cache-publication and preview-serving code. Deep project paths remain an open Windows compatibility issue.
## Triggered freeze investigation

Before the first diagnostic run, the campaign budget is six 60-second protected three-layer trials with the recorder enabled, alternating with three fresh uninstrumented frozen controls where practical. End diagnostic collection early after a usable active gap of at least 500 ms with three identified source lanes and a stable playing generation. Keep all shorter triggers and failed attempts. If the threshold is not reached in six trials, report the capture limit and leave the historical cause open. Use up to three additional same-workload trials to test a specific change if causation is supported. Final packaged acceptance uses three fresh uninstrumented 60-second trials plus the 125-second rapid-cut control and the ordinary editor layout. The existing FPS, skip, gap, audio, visibility and ownership requirements apply unchanged.

### What the recorder measures

Set `VLOGCRAFT_STALL_CAPTURE` to a new absolute local output filename before starting the packaged host. The worker samples native state on its own thread. The render loop publishes its requested frame, audio-clock snapshot, next frame deadline, and the most recent **distinct draw that returned**. A separate GPU counter advances after Flush, before Present. Seeing the GPU counter advance while the same draw is outstanding distinguishes a blocked Present from a decoder that has not supplied the next picture. The WebView reporter is outside this trigger path.

A trigger requires at least 100 ms without a new returned picture while the native audio clock expects a later one, the sequence still has pictures remaining and the reader, renderer and previous submission agree on the playing generation. Pause, seek, EOF and clock-mode changes fence measurements. A pause during an incident is reported as a transition. The watchdog never takes the device, producer, input or status-output locks. Only the watchdog writes files. A separate live snapshot at 500 ms can survive a blocked producer or renderer. A hard kill before that write can leave no report.

The sampler requests a 4 ms sleep. Actual poll intervals, the largest scheduling gap and torn observations are recorded. Each sample has the three producers' numeric source/decoder IDs, timebases, packet PTS/DTS and read count, requested and available PTS intervals, queue depth, retained prefix and outgoing tail, decode epoch, selection path, D3D lock state, current and last slow operation. All producers share device ordinal zero. The first synchronous decoder open runs on the render thread. Unbound codec helper threads, kernel scheduling reasons and driver internals are outside this recording. Thread CPU times come from Windows and can update coarsely. Read all lanes as observations within an interval. A short lock transaction can occur between polls, and per-stage counters can change while a row is read. Cross-thread timing totals cannot be summed.

Retention is 96 samples before the trigger, up to 768 through the stall including that prefix, and up to 64 further samples when needed for recovery. Recovery is observed for 180 ms. The longest three incidents survive in the final file. A fourth, active incident and the rolling prefix use at most 3,424 resident sample slots (4.60 MiB of sample payload in the tested x64 binary) plus container and I/O overhead. Each serialized sample is below 8 KiB for the fixed schema and stage names, bounding the final payload below 20 MiB and the single live payload below 7 MiB, plus small headers and temporary replacement files. The report counts triggers, partial reads, explicitly omitted middle samples and truncated incidents. The post-recovery interval can overlap the start of another stall. Missing-file, poll-gap or truncated coverage limits any causal inference.

Diagnostic trial 2 established a testable software contribution. During a 277 ms gap after frame 400, the render lane was waiting for the device lock in every one of 17 coherent stalled observations. A decoder held the device in each observation. The final nine showed 391 submissions and 391 completions. At that point a completion poll acquires the shared lock without having a query to read. The candidate experiment will bypass that acquisition only when the renderer already knows all submissions completed, and reuse a free slot already inspected in the same render iteration. A second poll remains possible if the first found no free slot. Support would require removal of idle completion-lock waits in corresponding captured rows and passing matched playback and correctness controls. Persistent long gaps or failed timing gates would leave general smoothness open. The 112 ms Present stall from diagnostic trial 1 is a separate observation.

### The one-second capture

Recorder trial 3 met the predeclared early-stop rule. Its protected presentation counter recorded 1,039.31 ms. The independent worker measured 1,039.307 ms from frame 2307 to frame 2372 in playing generation 2. A live file existed at 515 ms. The final file retained 1.398 s before the last returned draw and 188 ms after the first observed recovery, with 66 coherent samples of the stall, no truncated middle and no torn stalled rows. The longest poll interval over the trial was 18.19 ms.

The slowdown was already visible before frame 2307. Earlier Presents and device-lock waits let the audio target advance several frames ahead. At the first stalled sample the requested frame was 2311 and the three source FIFOs were empty. Across the 66 observations, 65 saw the renderer waiting to acquire the device for a completion poll. The last saw it waiting to compose. Each observation identified a decoder holding that device, with ownership split 23, 19 and 24 times among the three lanes. In 55 samples submitted and completed counts were both 2,225. All three source packet counters advanced by 68, including a rewind epoch change from 25 to 26 during the gap. Selection showed zero ready layers in 62 samples, one ready layer once, two twice and all three at recovery. The audible clock, loop and decoders continued advancing as the renderer repeatedly sampled later deadlines. This was a starvation and catch-up interval across multiple calls. It did not begin at a rewind or require a single one-second driver call. The longest individual Present in the trial was 88.44 ms.

The candidate removes completion-lock acquisition when the renderer's own counters prove that no query remains, and reuses a free slot already inspected in the iteration. Only the render thread mutates slot ownership. Selection and draining cannot occupy that slot, draw still takes the existing D3D lock, completion still releases references only after a successful query, and FFmpeg keeps its recursive device synchronization. The captured episode identifies a removable contribution. There is no paired recorder for the historical frame-2343 episode and no kernel scheduler trace of this capture. Exclusive driver-level attribution and general resolution of the freeze require additional evidence.

### Tested development MSI

The native suite was compiled at `893dc6e23af419a69591bdbe5386f0db3f97cceb` with input SHA-256 `3fd8e7cb64c14ae97e6f8a8eda59d6749d51209fd205ed109d5ae6df0292c516`. The administrative extraction passed the bundle comparison. All distributed native worker and DLL bytes matched the isolated compiler outputs. The workstation retained the frozen MSI separately.

| Candidate artifact | SHA-256 |
|---|---|
| Development MSI | `4d82887f41389b458278056970e12a49319850b0fb13df281c1f36fe947e9bd4` |
| Packaged desktop host | `cb09208757e396e6a808d9f9bb88312817154a3e373eb34d40a430ac315eaf93` |
| Packaged playback worker | `1717545bd55170d5299b524fd4a94bd12cb1564e6c31ff3f7cd3a9ab313746e0` |

### All short playback trials

Fresh host and project per run, unmanaged OS file caches, 2880 × 1800 desktop at 120 Hz and 175% scaling. The protected preview was 356 × 200 with a UHD60 composition. Every scheduled diagnostic and final trial is retained below. Peak working set sums process values and can include shared pages. Per-trial first-ready time, physical geometry, sampled conditions, p95/p99 intervals, exact final frame, ownership and pass/fail fields appear in the [sanitized record](benchmarks/studio-3.6.0-phase3b.json).

| Group | Trial | Distinct FPS | Skips | Max gap ms | PCM samples / underruns | Peak summed working set MiB | Screen |
|---|---|---:|---:|---:|---:|---:|---|
| Frozen | watch-frozen60a | 55.484 | 249 | 61.75 | 2,880,000 / 82 | 2983 | failed |
| Frozen | wd1-frozen602 | 57.905 | 104 | 658.56 | 2,880,000 / 0 | 3184 | failed |
| Frozen | wd1-frozen603 | 59.704 | 3 | 77.80 | 2,880,000 / 0 | 3193 | passed |
| Frozen | fix1-frozen604 | 59.617 | 2 | 35.23 | 2,880,000 / 0 | 3243 | passed |
| Pre-fix recorder off | wd1-diag60-off | 57.935 | 113 | 1304.28 | 2,880,000 / 0 | 3968 | failed |
| Pre-fix recorder on | wd1-diag60-on1 | 59.129 | 29 | 112.07 | 2,880,000 / 0 | 3536 | failed |
| Pre-fix recorder on | wd1-diag60-on2 | 58.754 | 50 | 276.64 | 2,880,000 / 0 | 3798 | failed |
| Pre-fix recorder on | wd1-diag60-on3 | 57.275 | 154 | 1039.31 | 2,880,000 / 0 | 3840 | failed |
| Revised worker recorder on | fix1-diag60-on1 | 59.854 | 0 | 34.14 | 2,880,000 / 0 | 3276 | passed |
| Revised worker recorder on | fix1-diag60-on2 | 59.629 | 7 | 96.91 | 2,880,000 / 0 | 3381 | passed |
| Revised worker recorder on | fix1-diag60-on3 | 58.921 | 45 | 388.15 | 2,880,000 / 0 | 3460 | failed |
| Final MSI | cand1-comp60a | 58.934 | 4 | 69.25 | 2,880,000 / 0 | 3693 | failed |
| Final MSI | cand1-comp60b | 58.181 | 99 | 438.60 | 2,880,000 / 0 | 3899 | failed |
| Final MSI | cand1-comp60c | 58.801 | 21 | 133.98 | 2,880,000 / 0 | 3878 | failed |
| Final MSI | cand1-switch125 | 59.958 | 0 | 31.33 | 6,000,000 / 0 | 2882 | passed |
| Editor size | cand1-frozen-editor60 | 58.847 | 63 | 762.42 | 2,880,000 / 0 | 3965 | failed |
| Editor size | cand1-editor60 | 59.433 | 27 | 112.26 | 2,880,000 / 0 | 3816 | failed |

The first frozen control spent 8 of 58 power samples off AC and recorded 82 underruns. It is included above and excluded only from the matched AC comparison. All three subsequent frozen controls and the three final protected measurements held AC and visibility. Two of three matched frozen controls passed. Zero of three final protected controls passed. The new worst active gap was smaller in this sample, but the median skip count rose from 3 to 21. Final median/worst skips of 21/99 exceed the historical goals of 3.5/16. The four-skip candidate run spanned 61.001 s and therefore failed the original wall-time FPS screen. Both 958 × 539 editor-size controls failed their 100 ms gap screen.

The same pre-fix worker with the recorder disabled delivered 57.935 FPS, 113 skips and a 1,304.28 ms gap. Enabling it gave 57.275–59.129 FPS, 29–154 skips and 112.07–1,039.31 ms maximum gaps. Recorder-on median FPS was 58.754, 0.819 FPS above the single off control. This variability prevents a reliable estimate of a small positive or negative tracing cost. The recorded windows survived without apparent sampler starvation: 4,054–4,117 observations per pre-fix process, at most 18.19 ms between polls, zero torn samples and 101–276 KiB per completed file. The revised recorder saw up to two torn observations per run and flags them.

### Remaining stall and handoff decision

The reserved third revised-worker diagnostic captured a 388.14 ms native gap from frame 55 to 80, **before the first rewind**. There were 24 coherent observations. Eleven saw completion polling with outstanding GPU work and thirteen saw source retries after every GPU job completed. Zero saw an empty completion poll. In 20 of the 24 samples the last selection showed no ready layer. Packet counts grew by 23, 24 and 24, with decode epoch zero throughout. The target advanced from frame 58 to 80. The prior needless lock acquisitions are gone in this capture, while the renderer still runs out of exact source intervals when three streams must catch up together. Driver-internal scheduling and the trigger for the initial loss of decode headroom are unresolved. The default exporter remains FFmpeg and the optional native preview remains experimental.

For the next diagnostic, trigger on the *first* presentation deadline missed with an unavailable layer. Correlate each layer's floor and successor PTS, packet-to-picture time, outermost lock wait and hold, query backlog, and time at which all three intervals first overlap the same requested frame. Retain the preceding Presents. Investigate the observed media-clock advance separately from the time until the end-of-playback acknowledgement. Keep admission, audio clock, queue bounds and the protected 60-second observer fixed. Further driver scheduling attribution needs a correlated trace with checked event loss. The long tests remain blocked pending three passing short runs and passing editor-size playback. [Executable qualification handoff](STUDIO_3_6_0_PHASE3B_HANDOFF.md).

### Packaged regression results

| Check | Frozen and/or revised measurements |
|---|---|
| Controlled seek | Twelve targets. Frozen p50/p95 450.17/608.59 ms, revised 454.94/584.37 ms. |
| Committed ruler drag | Paused median release-to-picture 513.70 to 486.80 ms. Playing release 523.80 to 439.40 ms. Every measured drag fetched PCM once and checkpointed once, with zero post-release frames before the target and zero underruns. |
| VFR and pending rewind | Correct 499.5 ms boundary, adjacent backward cut, 23 physical picture checks and 117 extra layer/frame pairs. Correct final seek during pending rewind and close during another in 32 ms. |
| Resource ownership | The VFR handoff used at most three decoders, four queued pictures per producer and 6,819,840 bytes of standby surfaces against the 896 MiB reservation limit. Protected workloads stayed within four in-flight slots. Every supervised trial released its owned processes. |
| Recovery and reference fallback | Packaged renderer and browser fault recovery restored the exact 80-entry history, unsaved draft, paused position and undo/redo in 7.40/7.45 s. Native worker failure, resize, modal visibility and reference fallback checks passed. |
| First HDR10+ export | 44.80 s to terminal job. Independent decoding returned 48 pictures, exact PTS, matching static HDR, 48 conforming picture-associated dynamic blocks, 38,400 exact PCM samples and 55.63 dB PQ PSNR. Active export cancellation and confirmed shutdown released all owned processes. |
| Repository and bundle | Loopback-only Python 196 passed, one skipped. Packaged WARP/export 9/9 and JavaScript 32/32 passed. Three dedicated watchdog tests passed, including live reporting while a producer held a real mutex wait. All 48 development MSI bundle comparisons passed, including the approved icon. |
| Private originals | Three of three hashes and modification times matched the recorded manifest before and after the media checks. Zero tracked paths, history-path hits, matching binary/text objects or publishable text matches. |

The MSI and native worker above identify the locally tested bytes. Later evidence commits bind the complete set of observations to the source and benchmark protocol. The hosted Windows regression and MSI lifecycle jobs run on the published PR revision. [Draft PR and exact-head checks](https://github.com/JakubSoltysiak/VlogCraft/pull/21/checks).
