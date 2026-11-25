# VlogCraft Studio 3.6.0 Phase 3B playback and editing

## Two outstanding picture copies on Radeon 890M

Candidate source `57309c174955d061f72649f4f4de3347cb68c89d` occupies the same two transfer slots per layer as its predecessor. The original transfer thread waited for each submitted copy to complete before considering its second slot. The compositor now observes completed producer fences while the worker can submit the other picture. Query fallback stays with the producer worker. The held-clock path refreshes the decoded successor and the proved cut tail without advancing the source selector. Unused ready copies can return their keyed ownership directly. Source ranges, lease lifetime through GPU use, transport generation and the production shared-device preference are preserved. [Design precedents](phase3b-upstream.md).

The native build and physical NV12 and P010 probes passed. Each format submitted both slots before consumer polling, reused the exact prefetched successor, retired stale work and drained with zero retained frames. Fence publication completed during an independently blocked decoder. FP16 output matched the shared-device player on six draws per format. The controlled VFR checks matched the independent floor at 499.5, 500 and 500.5 ms. The genuine backward cut selected PTS 300 for target 400. The pending-rewind run checked 117 layer/frame pairs with exact seek and 109 ms close.

| Recorder-off, original three UHD60 picture and audio layers | Distinct FPS | Skips | Maximum active gap | Final frame | PCM sample frames | Underruns / owned survivors |
|---|---:|---:|---:|---:|---:|---:|
| Frozen shared device, R | 59.444 | 11 | 79.721 ms | 3,599 | 2,880,000 | 0 / 0 |
| Two-slot overlap, F | 41.804 | 1,066 | 1,427.330 ms | 3,599 | 2,880,000 | 0 / 0 |

Both ran visible, foreground and unobscured at a 958 × 539 physical preview on AC and a 120 Hz desktop. F recorded 12,775 active source waits and zero active compositor-slot waits. Each of its three producers sought 40 times. This counter combines waiting for a proved source interval with waiting for a matching handoff. The results reject serializing the transfer slots as a sufficient explanation for the previous 42 FPS measurements. The candidate failed all three timing screens. The ordinary reversal, physical MSI and endurance gates remain closed for this worker.

## Timestamped per-layer preparation

| Recorder-off, original three-layer UHD workload, 958 × 539 preview | Distinct FPS | Skips | Maximum active gap (ms) | Audio underruns |
|---|---:|---:|---:|---:|
| Previous request-invalidating worker | 16.697 | 2,595 | 5,531.420 | 0 |
| Frozen R paired with timestamped queues | 59.784 | 0 | 47.115 | 0 |
| Timestamped queues F | 42.842 | 1,021 | 587.559 | 0 |
| Frozen R paired with fence publication | 58.799 | 54 | 584.183 | 0 |
| Timestamped queues and fence publication F | 42.305 | 1,036 | 1,289.130 | 0 |

Both new pairs passed the measurement controls. All four arms reached frame 3599 with 2,880,000 sample frames and zero owned survivors. Neither candidate passed the unchanged 59.5 FPS, fewer-than-30 skips and 100 ms maximum gap requirements. The fence worker used three fence-enabled lanes, made 2,564 handoff draws through drain and had zero fallbacks. All 1,036 skips followed a source wait, with 12,652 active source-wait iterations and zero compositor-slot waits. Fence publication resolved a controlled lock dependency and demonstrated no additional throughput benefit in its ordinary trial. The combinations of decoder floor and copy availability across lanes at individual missed deadlines remain unknown. Reversal, physical package, protected and endurance gates remain pending.

The timestamped/event worker was built from `bd11ee44d437a949a9f7c8b54ef53d60e5f0bcae`, SHA-256 `51acb70e7c84d9d473c9316fd5f1b3510a47d1f20570499f637eb7be7a9b09e1`. The fence worker was built from `35ea06415b5b8f89e206072ce75d5ce8cc44bba1`, SHA-256 `39eca2f412fdc1205d9bd574c3ce0da6c02b1b4ca838051ac08260bc2a36a28f`. Both ran in the same frozen host. Reference MSI SHA-256 `8047cde8308fe394abc2fa2c6543d6c02f8b5dd2dc6ed7accfdb34e76daa0cf5`. Each passed hardware VFR, exact seek during pending rewind, backwards cut and six FP16 comparisons per format. The final worker verified 120 layer/frame pairs and closed in 78 ms during another pending rewind.

The experimental player offers each lane the selected decoded picture and its next available source timestamp. The producer exposes them through a read-only snapshot of its queue, warm frames or verified outgoing cut tail. Only the original source selector can authorize a picture for composition. A new picture on the same transport can reuse an existing copy. A seek invalidates all old leases, including copies with the same PTS. The ring still has two images per layer and retires each after its last consumer GPU use. The default player uses the shared device. [Upstream implementation comparison](phase3b-upstream.md).

On both UHD formats, a real producer-lock challenge advanced the clock during a blocked transfer, kept a peer unavailable, acquired the exact prefetched successor, retired and reused the old slot, then rejected the previous lease on a same-PTS seek. A separate local GPU fence confirmed that the initial version could finish a copy while its publication thread still waited for the FFmpeg device lock. In the revised implementation, the producer signals a fence and releases the image key within the original serialized transaction. Publication reads the completed value without entering the decoder context. An unavailable fence or failed signal uses the event-query path. Consumer completion and source retention remain in force. [D3D11 Signal](https://learn.microsoft.com/en-us/windows/win32/api/d3d11_3/nf-d3d11_3-id3d11devicecontext4-signal) · [DXGI keyed surface ownership](https://learn.microsoft.com/en-us/windows/win32/api/dxgi/nf-dxgi-idxgikeyedmutex-releasesync).

The independent compositor published, verified and retired the fenced NV12 picture 8.919 ms after the controlled block began. The P010 picture retired at 11.994 ms. All eight pictures per format matched the reference. Tests observed both pending-copy and pending-consumer cancellation, capacity backpressure, two retained sources at peak and zero retained after cancellation. GPU copy-duration timestamps were unavailable in the fence-only observation path. The earlier query measurement applies to the earlier worker.

## Independent completed pictures on Radeon 890M

The compositor finished a verified UHD draw while the next real FFmpeg decode call held its device lock in a controlled block. The same ownership mechanism in the opt-in three-layer player failed the first ordinary comparison. The shared-device player remains the default. The previously tested corrected shared-device worker came from `d247b6a`; its previously recorded 104.604 ms gap still exceeds the 100 ms limit.

| Recorder off, ordinary 958 × 539, R then F | Wall seconds | Distinct FPS | Skips | Active interval mean / max | Intervals over 100 ms | Audio underruns |
|---|---:|---:|---:|---:|---:|---:|
| Frozen physical MSI image | 60.503 | 58.791 | 42 | 16.864 / 499.933 ms | 2 | 0 |
| Same host with experimental worker | 60.131 | 16.697 | 2,595 | 59.783 / 5,531.420 ms | 55 | 0 |

Both arms met the protocol controls, reached frame 3599 and delivered 2,880,000 sample frames. Both missed all three performance limits. The experiment submitted 1,005 handoff draws through drain, with zero fallbacks. All 2,595 skips followed a source wait. Active source-wait iterations rose from 318 to 35,702, with zero compositor-slot waits in both arms. The longest candidate Present API call took 17.599 ms. Source-wait accounting includes waiting for a usable copied picture. It cannot identify which layer, copy, or decoder missed the deadline. The current player requests a copy after all source floors are available and replaces the request when the selected frame changes. Measure where requests are delayed or superseded before changing that scheduling policy. Reversal, physical MSI qualification and both endurance stages remain gated.

### Ownership and measured cost

Each producer copies one selected decoder-array slice into a free, single-image NV12 or P010 texture. The constructor checks distinct devices on the same adapter, extended sharing and format support, and opens and validates both plane views. Each of the two textures owns a separate keyed mutex. One temporary NT handle is open during setup and closes after import. A producer completion query precedes publication. Consumer acquisition is nonblocking. A second query covers all consumer draws before key release, frame unpinning and slot reuse. The source pool and FFmpeg locking contract are unchanged. The real player uses a decoder device per source, separating the three producers as well as the renderer. The one-producer proof establishes only renderer/producer independence. Individual producer isolation in this model also removes the application-level device lock shared between peer decoders. Driver scheduling remains common to the adapter.

| Eight UHD pictures per format, isolated run | NV12 | P010 |
|---|---:|---:|
| GPU copy min / median / max, ms | 1.203 / 1.294 / 1.461 | 0.969 / 1.374 / 1.778 |
| Submit to observed publication median / max, ms | 2.784 / 18.496 | 3.561 / 22.983 |
| Consumer end/flush to observed completion median / max, ms | 1.737 / 6.150 | 4.138 / 9.513 |
| Observed consumer completion to reusable median / max, ms | 0.052 / 0.112 | 0.068 / 0.111 |
| Visible / storage payload per image, bytes | 12,441,600 / 12,441,600 | 24,883,200 / 25,067,520 |
| Two populated slots, sampled process-local DXGI usage increase | 26.25 MiB | 50.25 MiB |

The P010 allocation descriptor is 3840 × 2176 for a visible 3840 × 2160 picture. Storage payload uses descriptor dimensions and excludes driver padding and allocation metadata. DXGI readings cover the whole process before creation and after touching each slot, with zero sampled nonlocal growth. Verification draw/readback targets were excluded from that separate measurement. Publication and completion include polling and the probe's schedule. Each isolated ring reached two occupied slots and two retained source references, rejected two submissions at capacity, and ended with zero retained references. The 35-slice probe decoder pool stayed intact. The three-layer configuration permits six additional images, separate from decoder pools, source queues and compositor slots.

For NV12 the consumer completed 8.122 ms into a 38.067 ms controlled FFmpeg device-lock interval. For P010 it completed 9.659 ms into 30.992 ms. In the unblocked concurrent attempt for each format, the actual subsequent decode completed before the entire consumer draw finished. The earlier 35.196 ms input acquisition spent 35.118 ms waiting, with its underlying object still unidentified. No additional elevated trace was needed.

Every visible luma and chroma sample and the source PTS matched the independent reference for all 16 pictures, including significant P010 bits. The two slots were repeatedly reused. A pending B stayed unavailable while A could draw. Both formats suppressed stale publication on a generation change after observing an incomplete copy query and safely drained after cancellation with an incomplete consumer query. Both pending conditions occurred on the first attempt. The verification harness initially failed to link the shader compiler, then hit a transient busy verification readback on both formats. Loading the system compiler and bounding the verification-only staging retry fixed those attempts. The ledger retains their outcomes.

The same real worker passed VFR floor/successor checks on both sides of 500 ms, a backwards cut, an exact seek during pending rewind, and shutdown during another pending rewind (109 ms, zero owned survivors). The rewind check verified 117 layer/frame pairs. Across six positions per format including a backwards cut, the default and opt-in workers selected identical timestamps and produced identical FP16 captures. Both parity fixtures used SDR transfer. The initial parity reader expected intermediate capture files the worker only emits at a run endpoint. Six bounded prefixes verified every position through the existing capture interface.

The experiment borrows mpv's GPU copy from a decoder array slice into a renderable texture. mpv uses its D3D11 renderer context and multithread protection. VlogCraft additionally transfers ownership between devices and retains its source through consumer completion. OpenShot provides a precedent for per-reader hardware devices. Its ordinary download to software frames crosses a different transfer boundary. Staging is confined to the independent VlogCraft verifier. [mpv D3D11VA implementation](https://github.com/mpv-player/mpv/blob/35efcf53d59470b3941e61a50c8a3133035a093d/video/out/d3d11/hwdec_d3d11va.c#L207-L270) · [OpenShot hardware devices](https://github.com/OpenShot/libopenshot/blob/c23ef4ad9a4893092ddea78fa140c81838738721/src/FFmpegReader.cpp#L480-L493) · [OpenShot frame transfer](https://github.com/OpenShot/libopenshot/blob/c23ef4ad9a4893092ddea78fa140c81838738721/src/FFmpegReader.cpp#L1788-L1805).

Worker source `14846b6b82b8457137960085e229ba683f2899b6`, SHA-256 `d3e65d037ee0e4576b082b620ee775e5a892c8da228d98386a6dced7fb11b637`. Ownership verifier at that source `c44ad391030de9ef7f05f1ba1eb6d4ac36ccc83e095860566d6a2cfde8c6b400`. Populated-memory verifier at `b9699284c61694c1d50cb4ab8c8ff0ce0588cbd8`, SHA-256 `db7f8e83501099e53c9e0ada92a13bfdac853ce763d2647bd89f391838832ad3`. The ledger contains every picture timing, attempt outcome and ordinary comparison control. Physical device-loss recovery and unsupported-driver fallback remain unqualified. [Benchmark ledger](benchmarks/studio-3.6.0-phase3b.json) · [Executable handoff](STUDIO_3_6_0_PHASE3B_HANDOFF.md#independent-picture-handoff).

## Same-call scheduler evidence and decoder-array sharing

The corrected worker missed the ordinary active-gap limit at the November 24 checkpoint. A subsequent instrumented run captured the decoder thread's scheduling state throughout an input-buffer acquisition. An isolated two-device experiment also established what can be shared on the Radeon 890M. Production playback retains the guarded continuous-cut rollback, source-first polling, bounded refill and shared FFmpeg device. All earlier timing failures remain in the ledger.

| Three-layer UHD60, ordinary 958 × 539 surface | Wall seconds | Distinct FPS | Skips | Maximum active gap |
|---|---:|---:|---:|---:|
| Earlier control, recorder off, frozen MSI | 60.200 | 59.120 | 40 | 505.267 ms |
| Earlier corrected worker, recorder off | 60.084 | 59.766 | 5 | 104.604 ms |
| Earlier corrected worker, API and GPU tracing | 60.5635 | 58.897 | 32 | 220.293 ms |
| Corrected worker, API, GPU and scheduler tracing | 60.2002 | 59.568 | 13 | 124.165 ms |

All four observations used the same frame and PCM endpoints. The new run had zero underruns and owned survivors, frame 3599 and 2,880,000 sample frames. It held foreground visibility, AC, original fixture offsets, 120 Hz and 175% scaling. Peak live decoders, queued source pictures and in-flight compositor frames were 3, 4 and 4. The wall denominator includes the observer. Its excess over the nominal minute was 200.2 ms. The precise terminal acknowledgement delay was unmeasured with this recorder configuration. Active interval p95 and p99 histogram upper bounds were 18 and 19.5 ms. All 13 skips followed a source wait.

### Inside the decoder call

The same PID, thread and D3D11 API pair identified source 3 acquiring picture parameters. The 35.196 ms call began 0.543 ms into the 124.170 ms watchdog incident after frame 3. Context-switch and ready-thread edges accounted for **35.118 ms waiting** with reason `UserRequest`, **0.024 ms ready** and **0.054 ms scheduled**. The thread waited from +0.057 to +35.174 ms in the longer of two waits. Two peer decoders each waited on the shared device for at least 31.598 ms. The renderer waited at least 15.569 ms. These observations overlap. Scheduling data identifies neither the specific waited object nor a module or instruction executing during the scheduled portion.

The previous same-thread fence-bearing queue packet completed at +25.454 ms, 9.720 ms before the thread became ready. No unique input-buffer/fence mapping was exposed. Frame 10, the first observed missing request, came 88.700 ms after the acquisition ended. All three source floors were 1792 for target 2560 at 1/15360 with no successor. The first fully covered request, frame 15, followed 77.958 ms later with floors of 3840 and successors of 4096. During that recovery, another decoder spent 13.193 of 13.238 ms in a scheduler wait with reason `WrPushLock`. The timing supports a contribution to lost source coverage. Other work occupied the rest of the presentation gap.

Both ETLs used the same boot and performance counter and reported zero lost buffers or events. Independent raw QPC timestamps from two windows 55 seconds apart agreed with their relative UTC origins at the 100 ns resolution checked. Dumper boundaries use integer microseconds. The native sample/ETL alignment has sub-millisecond uncertainty. The recorder retained all 3,604 requests with zero torn polls. The older 65.951 ms call had zero accounted thread CPU in 46.182 ms of coherent samples. Its individual scheduler states remain unknown.

Two isolated successful acquisitions on this workstation matched the Stop event's `ppBuffer` and `pBufferSize` to the **returned CPU pointer and byte count**. Distinct storage addresses for the caller's output parameters matched neither field. This calibrates the local provider schema. Reuse of that CPU pointer still does not identify a driver allocation or synchronization object. [D3D11 API contract](https://learn.microsoft.com/en-us/windows/win32/api/d3d11/nf-d3d11-id3d11videocontext-getdecoderbuffer).

### Independent-device admission experiment

FFmpeg 9.0.2 uses a recursive device mutex and the immediate video context. It enables D3D multithread protection when the interface is available. The frame transaction holds the shared callback across input acquisition, copy, release, submission and end-frame. The playback worker shares that device between producers and renderer. Unlocking an individual call inside the transaction would break this ownership contract. [FFmpeg device construction](https://github.com/FFmpeg/FFmpeg/blob/n9.0.2/libavutil/hwcontext_d3d11va.c#L471-L501) · [FFmpeg decode transaction](https://github.com/FFmpeg/FFmpeg/blob/n9.0.2/libavcodec/dxva2.c#L814-L965).

The probe first decoded each generated source with the existing decoder configuration. It closed that pool and created an equally sized, shareable decoder array. A second device on the same adapter opened the array and created both shader plane views. The producer took the keyed mutex before FFmpeg decoded and retained the frame through consumer completion. The consumer compared every visible luma and chroma byte with the control, including all ten significant bits for P010. The open itself required zero inter-device copies. CPU staging and readback were confined to picture verification.

| Tested first picture, PTS 0 | Decoder storage | Array slices | Visible bytes matched |
|---|---:|---:|---:|
| H.264 NV12 | 3840 × 2160 | 35 | 12,441,600 |
| HEVC P010 | 3840 × 2176 | 35 | 24,883,200 |

Both initial descriptor probes and both real-picture handoffs passed, with zero owned survivors. In both formats the consumer's immediate acquisition timed out while the producer held the array. Only releasing the entire array allowed the consumer to acquire it. A picture from an earlier slice therefore cannot be sampled independently through this mutex during a later decoder stall. The result rejects this design for normal playback. It establishes no FPS improvement. Cross-device generation changes, cancellation with work pending and concurrent retirement still need a viable ownership design. The existing worker, package and resource gates retain their previous status. [Extended sharing](https://learn.microsoft.com/en-us/windows/win32/direct3d11/direct3d-11-1-features#extended-support-for-shared-texture2d-resources) · [Reproduction and next decision](STUDIO_3_6_0_PHASE3B_HANDOFF.md#scheduler-and-sharing-handoff).

The starting point was Phase 3A at [f4a852b](https://github.com/JakubSoltysiak/VlogCraft/commit/f4a852ba36d9cd6e417c2cbfd1dc90af1ad2d630). [Draft PR #21](https://github.com/JakubSoltysiak/VlogCraft/pull/21) targets the Phase 3A branch. Windows results use the development MSI applications on the Radeon 890M workstation. Administrative MSI images and test projects were local and isolated from the user's active installation and projects.

Earlier package results are in the [refill deferral follow-up](#refill-deferral-during-present). The [source-readiness follow-up](#source-readiness-and-terminal-acknowledgement-follow-up) documents the earlier recorder and timing changes. The earlier [triggered freeze investigation](#triggered-freeze-investigation) preserves the first stall diagnosis. The preceding [follow-up qualification](#follow-up-acceptance-protocol) established the comparison package. Three 125-second rapid-switch runs completed with zero skips. Two of three 60-second three-layer runs met all timing screens. The third lost 222 frames.

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

## Source-readiness and terminal-acknowledgement follow-up

The primary comparison for this follow-up is the immediately preceding development MSI published at `28c0abf221c87e1b7c673a36abe70fac594cdc27`, with packaged source `893dc6e23af419a69591bdbe5386f0db3f97cceb`. The older `b817372` package and original Phase 3B and 3A results remain separate historical controls.

Before inspecting the new recorder output, the diagnostic budget is three recorder-enabled protected runs and one recorder-off run on the same observation worker, plus an instrumented completion run if the same trace cannot supply both timelines. Retain every result. Read each capture before scheduling the next. Finish this campaign early only if the initial unavailable interval and its preceding transition are clear enough to motivate a specific testable correction. After any correction, freeze and test the packaged implementation in three unchanged protected 60-second runs and the separate editor-size and rapid-switch controls. Keep the existing wall-time FPS denominator.

The first observation worker found an early miss before any rewind. The last successful request selected frame 13 with two queued successors per source, after a stretch of renderer queries waiting on the device. Frame 16 then asked for tick 4096 (timebase 1/15360). All three floor pictures exactly matched the target, but each FIFO had zero successors. No exact frame-16 composite became ready, and the first all-ready request was frame 17. Other retained incidents began with both missing floors and missing successors, including after rewinds.

The candidate tests one ordering change. When playing with a free render slot, source selection runs before an optional completion-poll acquisition. If the same request has all intervals, existing completion queries run under the same device lock as composition. At capacity, paused and terminal states still poll normally. This removes a standalone acquisition from source lookups, preserves query-before-release and uses the existing slot count. The remaining required test is whether the changed order protects the short gates without losing handoff or seek correctness.

The second pre-change capture showed a different precursor. Frame 39 had three queued successors per source and was followed by an approximately 69 ms interval between complete source observations. During that interval the watchdog repeatedly saw Present. At the first inspection of frame 43, all three queues were empty, each floor was tick 10752, and the target was tick 11008. All three recovered for that same requested frame 2.969 ms later. These observations isolate missing usable intervals, preceding render-side waits, and later catch-up, without identifying a single driver operation common to every miss.

The recorder publishes each completed source request as one revision-checked tuple. The three guarded observations have their own entry and inspection times, and share a sequence frame, transport generation and rational targets. Source IDs, seek epochs, first four queued PTS values, selection reasons and decode counters belong to these guarded observations. Packet counters are separate progress snapshots. A device or owner observation in the independently sampled rolling rows can precede or follow any of the three selections. The two streams are correlated by monotonic time and are not a global atomic snapshot. No renderer or producer writes files. At most 256 requests can await collection, 96 precede a capture and 256 are retained per incident, plus the first deadline capture. The first deadline also preserves up to 160 sampled rows. Sequence gaps, torn rows and overwritten requests remain visible.

### Completion timing under the unchanged observer

The retained four-skip run used 3,595 distinct pictures over 61.0007 s. The native status sampled at frame 3584 was at native wall 61.8106 s. The next sampled status was terminal at 62.9814 s, a 1.1708 s sampling gap. The observed preterminal native-wall and frame relationship places the nominal end near 62.077 s. The historical receipt did not capture when the first terminal status or GUI stop occurred, so it cannot allocate the excess 904 ms precisely.

Instrumented runs kept the same protected driver and denominator. Relative to its start, the candidate's projected final-picture deadline was 60.042619 s. The final draw returned 0.872 ms later and GPU completion and full drain were observed 5.549 ms after the draw. The final PCM worklet acknowledgement was at 60.009300 s. The output-timestamp estimate put the audible endpoint at 60.056260 s, with GUI Stop 1.940 ms later. The native clock reached EOS at 60.060175 s and its regular terminal status followed 97.364 ms later. Host receipt and publication took 0.071 and 0.060 ms. The GUI received terminal status 14.330 ms after publication. That status was separate from the already completed GUI Stop. Producer join was recorded at close only, at 61.227988 s.

The candidate's protected observer first saw the stopped UI and endpoint at 60.293800 s, **235.6 ms after GUI Stop**. Its final pair of observations was 803 ms apart. The nominal 250 ms Playwright wait RPC took 526.027 ms, and delivery of the previous evaluate result added approximately 276 ms. The old verified MSI repeated the observer tail. Its audible endpoint estimate was 60.048536 s, GUI Stop was 60.052300 s, and the observer first saw that state at 60.766700 s, **714.4 ms after Stop**. That unchanged binary has no host or native completion stamps. The reproduced tail identifies a material observation delay. The retained 61.0007 s result still fails the original FPS screen. No change was made to the denominator, EOS cadence or audio timing.

The same candidate endpoint run preserved source request observations. Its first post-deadline source miss was frame 11, while all three exact floors were present and their successors absent. It recovered all three intervals for frame 11 in 4.654 ms. The preceding sampled Present held three decoder refills. One row of the run's watchdog sampling was flagged torn, with zero request overwrites and no 100 ms watchdog incident. The combined diagnostic measured 59.608 FPS, five skips and a 51.44 ms maximum gap. It remains separate from the three uninstrumented MSI trials.

### First candidate and correctness regression

The pre-change diagnostic worker without capture recorded 56.807 FPS, 181 skips and a 1,562.80 ms active gap. With capture it recorded 54.143 FPS, 319 skips and 1,431.30 ms, then 58.012 FPS, 106 skips and 323.61 ms. Both retained full PCM with zero underruns, zero request loss and visible AC operation. The same-worker off result falls between the on results by FPS and skips. The data do not isolate a small recorder effect.

The first candidate MSI's three protected runs recorded 58.326/87/944.44 ms, 59.389/14/98.17 ms and 59.667/5/52.34 ms (FPS/skips/maximum gap). All finished frame 3599 with 2,880,000 PCM samples, zero underruns and visible AC operation. The first exceeded all three timing thresholds. The second met the skip and gap screens and missed the unchanged FPS floor. The third passed. Device-lock acquisitions fell from 12,748–12,818 in the preceding package's three protected trials to 3,572–3,644. Its first run still accumulated 630 source-wait iterations and zero GPU-slot waits. Its skip median was 14 and worst was 87, against the historical 3.5/16 targets.

The ordinary editor preview measured 958 × 539 physical pixels. The candidate missed the screen at 58.757 FPS, 68 skips and 963.11 ms. The rapid-cut control passed with all 7,500 pictures, zero skips, 6,000,000 PCM samples, zero underruns, final frame 7499 and a 29.92 ms maximum gap. The 600-second and 30-minute runs were blocked for that package.


The first MSI passed 23 paused VFR colors and exact PCM, but failed the active cut observer. Its completed-frame counter was often one frame behind the selected picture because the completion poll moved into the next draw. The revised candidate keeps eager polling on the single-layer/VFR control and around periodic status publication. The combined lock acquisition remains in ordinary multitrack playback between status reports. Paused and end-of-sequence completion paths still poll eagerly. The first MSI remains identified as `a7b81d18ff5d4a71f043c4d108babb238b133da1`, SHA-256 `6950250c453df0ac2944e61e0c2a80a999d255d385888d125e3581d59eca457e`.

An extra guarded trace on the first MSI completed at 59.519 FPS, two skips and 36.08 ms. It recorded 3,603 complete selection requests, zero lost requests, one torn polling row and no first-source miss or 100 ms incident. That run did not reproduce the 944.44 ms failure and does not replace it.

### Revised package identity

The revised build used source `7086ed380d279855b2d81f87d4d2105e268b6335` and native input SHA-256 `2b64013979934da70095dca25a0e6a9fdafa5c68b87a24d6b71bcc14d8e6f11d`. The extracted package and its native files were compared to the isolated build outputs.

| Artifact | SHA-256 |
|---|---|
| Development MSI | `2f9de210fe88a2e4903e679bb61e081201973b073f20bba2bce3cf14bc0b8266` |
| Desktop host | `23e85f11a30e6f885f00220aa9966fbf6545389b9c61d0ef4f22e49d6cfca490` |
| Native playback worker | `2251ac360af922971b0fbcde1a08eb2b4693e7f994e8bf77bf44d1897c0f36a6` |


### Final packaged result

All new performance trials used fresh processes and projects. The controls used synchronized original source offsets, as before. The desktop was 2880 × 1800 at 120 Hz with 175% scaling. The protected preview was 356 × 200 and the program composition stayed UHD60. Individual resource and ownership results are in the [sanitized benchmark record](benchmarks/studio-3.6.0-phase3b.json). File-system caches were unmanaged.

| Package and workload | Distinct FPS | Skips | Active gap maximum (ms) | Screen |
|---|---:|---:|---:|---|
| Previous MSI, protected, recorder on | 59.218 | 6 | 56.59 | Fail (FPS) |
| Previous MSI, protected, recorder off | 59.595 | 0 | 32.61 | Pass |
| Previous MSI, ordinary editor | 59.817 | 0 | 32.58 | Pass |
| Final MSI, protected A | 58.980 | 11 | 75.45 | Fail (FPS) |
| Final MSI, protected B | 59.295 | 6 | 52.55 | Fail (FPS) |
| Final MSI, protected C | 59.347 | 29 | 132.82 | Fail (FPS, gap) |
| Final MSI, 125-second rapid cuts | 59.806 | 0 | 32.83 | Pass |
| Final MSI, ordinary editor | 58.820 | 47 | 502.27 | Fail (FPS, skips, gap) |
| Final MSI, protected, recorder on | 59.509 | 0 | 32.99 | Pass |

The three final short trials missed 59.5 FPS. All three met the PCM, final frame, visibility, AC and cleanup gates. Final protected median/worst skips were 11/29, compared with historical thresholds of 3.5/16. The ordinary preview above is 958 × 539 physical pixels. The 600-second playback and 30-minute editing trials were not started.

The final controlled seek comparison measured 432.69/549.69 ms p50/p95. Paused ruler release median was 472.70 ms, with a playing release at 458.00 ms. Each measured commit fetched PCM and wrote one recovery checkpoint. The recorded interaction times are distinct from immediate UI work.

### Final package correctness

- The final package passed the active VFR handoff, 23 physical picture checks, the independent 499.5 ms boundary and backward cut, and exact seek during pending rewind. Another rewind test matched 117 picture/timestamp pairs and closed in 31 ms. The VFR handoff consumed 115,200 PCM samples with zero underruns. Peak simultaneous decoders and source queue depth were 3 and 4.
- Native fault recovery, visibility through resize and modals, and whole-project FFmpeg fallback passed. Injected WebView renderer and browser faults restored the exact 80-entry history and unsaved project state in 7.29 and 7.21 s, including undo/redo and preview alignment. All owned children were released.
- Offline HDR10+ first export reached terminal success in 41.60 s. Independent verification decoded 48 pictures and 38,400 exact PCM samples. It matched video PTS, static HDR signals and all 48 picture-associated HDR10+ blocks. Decoded PQ PSNR was 55.63 dB. Cancellation and confirmed shutdown passed. FFmpeg stays the default, with native first export experimental and restricted.
- The full loopback-only Python suite passed 200 tests with one skip. Packaged WARP/export passed 9/9, JavaScript passed 33/33, and the development MSI matched all 48 bundle checks including its approved icon. The local images were administrative extracts, with actual Windows MSI lifecycle checked by hosted validation.
- All three original private media hashes and modification times matched before and after testing. No private media objects or identifying paths were found in publication scope.

### Remaining work

The final recorder-only rerun produced 3,606 request observations without loss or torn rows and captured neither a source deadline miss nor a 100 ms presentation incident. It passed with zero skips in contrast with the uninstrumented failures. Repeated ordinary editor geometry misses are a stronger remaining concern than the protected observer tail alone. Use the ordinary 958 × 539 surface with the previous and revised verified packages to capture the interval immediately before loss of decode-ahead. In particular, measure refill-hold duration during costs of Present and required GPU work, alongside the first missing successor. Try a time-bounded hold only if the recorded sequence supports it. Keep the protected fixture and wall-time series as the acceptance reference. [Executable handoff](STUDIO_3_6_0_PHASE3B_HANDOFF.md).

The 226-to-268-character Windows cache publication failure, 149.75-second cold mixed monitor preparation, physical GPU recovery, calibrated HDR display and representative full 60-second mixed UHD60 HDR10+ export remain separate gates. [Exact-head hosted checks](https://github.com/JakubSoltysiak/VlogCraft/pull/21/checks).

## Refill deferral during Present

The diagnostic starts with two serial pairs at the ordinary 958 × 539 preview. Pair 1 is current hold A then no hold B. Pair 2 is B then A. The two arms use the same diagnostic worker extracted into a clone of the latest package host, the same recorder and original three-layer UHD60 fixture. Each attempt gets a fresh editor and project. Source-first ordering, completion cadence, bounded rewind policy, AC, visibility and unmanaged file caches are held fixed. Review each pair before proceeding.

Record a support finding only if an observed long Present contains a deliberately deferred producer with queue capacity remaining, and the resulting deficit is visible in the first coherent missed selection. Judge a correction on both paired timing and retained correctness. If A and B give conflicting performance or the dominant stalls persist without active holds, use one diagnostic comparison against the old polling order while preserving empty completion-poll bypass. Keep every failed run and stop the bounded experiment after that comparison.

### What the paired runs isolated

The retained earlier frame-39 trace shows why this was plausible. A 68.360 ms Present overlapped at least 47.641 ms of all three producers asleep with three queued successors and no device-lock wait or ownership. Their last successor covered 50 ms from the inspected source position. The next common request had no queued successor.

The new editor-size A/B runs used worker SHA-256 `e58e6636c0208dfd3f92a24220dc77fd170448ab6a5c82a56dda8269fa58d101`, reproducible from the native source at `67c2033233d9b59733fc336c01f8e61ad52baec3`. All four held visibility and AC and completed exact audio and final picture without underruns or owned survivors.

| Order | Refill policy | Distinct FPS | Skips | Max active gap | Max Present call |
|---|---|---:|---:|---:|---:|
| 1 | A · existing hold | 58.096 | 84 | 629.09 ms | 121.31 ms |
| 2 | B · hold disabled | 57.838 | 124 | 837.11 ms | 82.91 ms |
| 3 | B · hold disabled | 59.350 | 23 | 63.22 ms | 52.60 ms |
| 4 | A · existing hold | 59.530 | 4 | 71.56 ms | 53.10 ms |

In pair 1, all three A holds began about 9.46 ms before frame 8 entered Present. Each had two successors and 512 source ticks of available proof, equivalent to 33.33 ms. Present took 121.31 ms. The holds ended 15–32 microseconds after it returned, about 131 ms after installation. Frame 15 then requested tick 3840 from all three layers, which had floor 2816 and no successor. The subsequent 629.09 ms gap included decoder work, shared-device waits and repeated unavailable source requests after the scheduling holds had ended. In B, the 837.11 ms gap persisted with zero active holds. Its decoders continued packet progress around the shared device while source selections retried. Hold removal lost more pictures in both pairs, although it shortened the second pair's maximum gap.

The evidence supports the hold as one cause of headroom loss. The candidate therefore retains short coordination and gives it an independent producer deadline. The deadline is at most half a sequence frame after the requested frame's due time, shortened if needed to reserve one full frame of the observed successor-PTS headroom. It uses the source timebase and clip speed. Installation wakes a producer that was sleeping on a full queue, so the producer switches to a timed monotonic condition-variable wait. Reinspection cannot renew a hold for the same frame and transport generation. EOF, reset/rewind, errors and cancellation clear it. Actual wake time still depends on OS scheduling and the next decoder operation still uses the existing device synchronization. Selection proof, early rewind admission, query-before-release and all queue/resource limits remain in place.

The software liveness regression drives the real decoder and condition variable from a full queue, withholds renderer release, and verifies refill after expiry and no same-frame renewal. It does not measure physical GPU performance.

### Same-worker bounded variant

The additional A/D comparison held the host, worker and recorder fixed. A used the original unlimited hold and D used the monotonic expiry. A measured 58.950 FPS, 50 skips and a 568.41 ms active gap. D measured 59.364 FPS, 12 skips and a 75.47 ms active gap. Source retry iterations during the measured interval fell from 367 to 6. The longest direct Present increased from 55.58 to 75.10 ms, so the reduced active gap cannot be explained by a shorter longest Present. Both arms had exact PCM and final picture, zero underruns, full visibility on AC and no surviving owned processes.

The D recorder retained 22 distinct expiries around its first missing source request and associated 17 of them with an in-progress or completed Present interval. For example, all three producers expired about 21.8 ms into frame 153's 54.38 ms Present. The observed hold lengths ranged from 3.63 to 22.10 ms. The ideal monotonic deadline can be checked late because of Windows timer and scheduling delays. The correction makes expiry independent of the renderer and bounds the requested wait. No source request records were lost and no rows were torn in either arm.

This was one controlled pair. D still missed the original wall-time FPS threshold, and the physical qualification remains the separate uninstrumented MSI series. No change was made to the completion observer or the wall-time denominator.


### Final MSI identity

The final package was built from `b42e37630810e880a38dda2b111168b9bd5d11f9` with native source digest `9e6bf0b5004e074e02cfca62aa154e2c5d251b4eb646ba87e1c8586d62d7df99`. The packaged checks use a fresh administrative image, leaving the existing user installation out of the run.

| Artifact | SHA-256 |
|---|---|
| Development MSI | `8047cde8308fe394abc2fa2c6543d6c02f8b5dd2dc6ed7accfdb34e76daa0cf5` |
| Extracted host | `fd0fcbca279f3ce20e1bcd5d33e212e1cba88b2025c806003b39b9e9922ce4ed` |
| Native playback worker | `152866b9a0ba6d9b4722e7e567ad1299d8a10a2cba6cd7b3160117c1178452f3` |

### Uninstrumented short-gate results

All protected attempts used the unchanged 356 × 200 physical preview, three simultaneous UHD60 picture and audio layers, the original source offsets and the protected wall-time denominator. The ordinary preview was 958 × 539. The workstation held 2880 × 1800 at 120 Hz and 175% DPI, with foreground visibility and AC. All runs below completed their exact PCM and final picture endpoints and cleaned up their owned processes.

| Package and fixture | Distinct FPS | Skips | Maximum active gap | Gate |
|---|---:|---:|---:|---|
| Final MSI, protected A | 58.884 | 60 | 502.94 ms | FPS, skips and gap fail |
| Final MSI, protected B | 56.455 | 200 | 435.87 ms | FPS, skips and gap fail |
| Final MSI, protected C | 59.214 | 3 | 86.87 ms | FPS fail |
| Final MSI, ordinary editor | 58.142 | 95 | 1,192.66 ms | FPS, skips and gap fail |
| Immediately preceding MSI, fresh ordinary control | 56.982 | 164 | 1,368.44 ms | FPS, skips and gap fail |
| Earlier `cand1` ordinary control, retained | 59.817 | 0 | 32.58 ms | Pass |
| Final MSI, 125-second rapid cuts | 59.760 | 0 | 30.90 ms | Pass |

Protected median/worst values were 58.884/56.455 FPS, 60/200 skips and 435.87/502.94 ms. The previous published package's historical protected skip median/worst was 11/29. The current sensitivity to active stalls remains. In the final ordinary run, the 1,192.66 ms gap and 804 source-wait iterations represent playback disruption. The matched prior package reproduced a 1,368.44 ms gap in the same new campaign despite its better earlier published observation. The final ordinary comparison improved by 69 skips and 175.78 ms in this pair. Both failed and the older passing control remains a separate artifact.

The historical end-of-playback observer delay remains documented separately. The missed FPS floor on the three-skip run included a 60.7293 s wall interval. The large gaps in the other attempts are active presentation delays even when the terminal observer returns close to 60 seconds. The 600-second playback, editing smoke and 30-minute editing tests did not run because the final package failed the short timing screens.

The paired evidence established a genuine unlimited-hold failure, so the single additional comparison evaluated the bounded variant. The isolation of source-first/combined polling is carried forward. The final worker still needs matched editor-size captures that distinguish post-expiry decode/driver contention from blocking completion checks. The next session can run a narrow same-worker comparison with the bounded refill policy fixed. If that still leaves all three sources starved, use the handoff to correlate D3D lock wait/hold, decoder progress, and scheduling without increasing queue or in-flight limits. [Windows reproduction commands](STUDIO_3_6_0_PHASE3B_HANDOFF.md).

### Packaged correctness, recovery and export

- Rapid cuts delivered all 7,500 pictures and 6,000,000 PCM samples with frame 7499 complete. The 499.5 ms VFR boundary, backward cuts and 23 physical VFR checks passed. Active handoff used 115,200 PCM samples with zero underruns. The pending-rewind fixture compared 120 layer/frame pairs, completed an exact seek and closed during another rewind in 16 ms.
- Controlled seek p50/p95 were 457.77/623.25 ms. Paused ruler release median was 482.30 ms and playing release was 500.40 ms. Each commit used one PCM fetch and one recovery checkpoint. Native failure recovery, resize/modal visibility, reference fallback, cancellation and process cleanup passed.
- Both WebView fault cases recovered the exact 80 undo entries, project output, unsaved draft, paused position and undo/redo. Renderer recovery took 7.05 s and browser recovery took 7.32 s.
- Scoped first export reached terminal success in 44.41 s. Independent validation confirmed 48 decoded pictures, exact PTS, 38,400 PCM samples, static HDR and all 48 dynamic metadata associations with 55.63 dB PQ PSNR. Active export cancellation and confirmed shutdown passed. FFmpeg remains the default and whole-project fallback.
- The loopback-only Python suite passed 202 tests with one skip. WARP/export passed 9/9, JavaScript passed 33/33 and the extracted MSI passed all 48 bundle comparisons including the approved icon. The three private originals retained their recorded hashes and modification times. Raw traces remain local.

The publication stays in [draft PR #21](https://github.com/JakubSoltysiak/VlogCraft/pull/21). The 226-to-268-character cache publication error, 149.75-second mixed-preview cold preparation, physical GPU recovery, calibrated HDR display and representative 60-second mixed UHD60 HDR10+ export remain separate tasks.

## Polling order and continuous-cut rollback

The November 24 follow-up keeps source-first polling and independent refill expiry. Two opposite-order comparisons failed to establish a consistent benefit from eager polling. One captured stall exposed a separate, avoidable decoder reset. The corrected worker passed its decoded-floor regression and missed the ordinary playback gap limit by 4.604 ms. The latest physically tested MSI remains the package identified above.

All rows used fresh editor processes with the three simultaneous UHD60 picture and audio layers, original source offsets and synchronized cuts, 958 × 539 physical preview, visible foreground, AC, 120 Hz, 175% scaling and unmanaged file caches. The four C/D rows used the same worker built from `2e6b218` on the extracted `cand4` host. Runtime status confirmed each requested polling policy and bounded refill through drain. The matched diagnostic pairs included the native recorder and a bounded Windows DxgKrnl event session. The ordinary pair used neither. All six completed frame 3599 and 2,880,000 PCM samples with zero underruns and no surviving owned processes.

| Attempt in execution order | Wall seconds | Distinct FPS | Skips | Maximum active gap | Active source retries |
|---|---:|---:|---:|---:|---:|
| C eager, first pair | 60.231 | 59.753 | 0 | 42.30 ms | 0 |
| D source-first, first pair | 60.063 | 59.554 | 22 | 214.14 ms | 136 |
| D source-first, reverse pair | 60.107 | 58.563 | 78 | 988.95 ms | 659 |
| C eager, reverse pair | 60.339 | 57.525 | 128 | 1,613.83 ms | 1,045 |
| Frozen MSI, ordinary control | 60.200 | 59.120 | 40 | 505.27 ms | 307 |
| Corrected worker, ordinary | 60.084 | 59.766 | 5 | 104.60 ms | 3 |

Across its two attempts C had median/worst FPS 58.639/57.525, skips 64/128 and active gap 828.07/1,613.83 ms. D measured 59.058/58.563, 50/78 and 601.55/988.95 ms. Each ordinary arm has one observation. The protected wall-time denominator remains intact. These runs did not enable the separate terminal-observer tracer. The measured active gaps occur during playback.

### Following the missing pictures

In the first D run, frame 15 requested source tick 3840. Floors were 3072/3328/3072, all successors were absent and all holds were clear. Before that request, a 92.14 ms Present overlapped at least 78.91 ms in which one decoder held the shared device inside packet submission while both peers waited. The owner had two queued pictures and the peers had three and two. No ready producer with a large surplus dominated this interval.

Source-first skipped checks on pending work during 70 and 153 source-wait iterations in its two runs. A free compositor slot can bypass `available()`, selection can fail, and the status path can refresh `lastReport` without testing a query. In the first D episode, three slots remained pending for about 107 ms. In reverse D, a source still had no successor 745.29 ms after the final slot released. Across the 989 ms gap all three decoders advanced by 64–65 received pictures. They still had to catch up with the moving target.

The worker measured 35 physical array slices per decoder. In reverse D the observed application-owned union peaked at eight per source, with one held exclusively by GPU slots. In the longest C gap, 100 of 102 coherent renderer samples had zero pending slots. Peak observed ownership was 8/8/9 slices with zero held exclusively by slots. Counts deduplicate current, queue, warm, rewind tail, decoder output, partial selection and pending AVFrames by pool and slice. Cached shader-resource views retain COM references to the texture array. Codec-internal references and intervening unsampled transitions remain outside the observed union. A successful D3D event query still precedes every slot release.

The private DxgKrnl traces bracketed the selected intervals with zero lost buffers or events. All 440 decoder-issued queue packets observed in reverse D's long gap had matched stops. Their maximum lifetimes were 222/227/215 ms by lane. The corresponding 376 packets in C reached 342/339/341 ms. Matching used context, submission sequence and packet identity. No DMA execution span could be linked by the recorded identities. Packet lifetimes include queuing. Windows rejected kernel context-switch collection under this account, so the trace cannot apportion the full intervals between execution, runnable time and driver waits.

### Three unnecessary decoder resets

During C's 1.614 s gap, requests 832–834 were for sequence frames 840→839→840. Frame 813 was the last submitted. The transport generation stayed at 2 and the cut joined the same source continuously at tick 7680. All three decoders had a floor at 2816. When the playing audio estimate moved back to target 7424, all three lost their floors, advanced decode epoch 9→10 and decoded again from PTS zero. Each replayed twelve pictures and submitted fifteen packets to regain its old floor, taking 437–471 ms. The later 876→875 correction inside a clip retained its floors. These durations measure replay to the old floor and do not predict the number of frames the fix saves.

Implementation `d247b6a615ae115296ff834e4214f71b186a5b64` permits reuse across that reversed continuous boundary when the decoder still has a floor at or before the corrected source target. It lowers the producer's target under its existing guard, so a concurrently received successor goes into the queue. The original source-interval selection still decides readiness. A genuine seek, discontinuity, pending rewind, stale epoch, cancellation, failure or floor beyond the target follows the existing reset path. The correction takes no device lock and adds no surface, queue or timing allowance.

The recorder-off candidate used native input digest `57048db155e2d2325ecc4e58842e9ed4ef90c82562d618060bdee10e123e1f04` and worker `3c2651afa4c611b81ae11f3e6b56a859e55f8716e40f3f793e69bac6314c9f1b`. The control and candidate both recorded 40 seeks per source. This pair does not establish a performance gain from avoiding a reset. Four candidate skips appeared between status samples at frames 77 and 115, with three source retries. One later skip appeared across frames 1795–1819 without a source retry. The native maximum Present was 89.88 ms. The ordinary observer lacks the per-call timestamps needed to assign the 104.604 ms gap to one precise call.

The predeclared candidate gate failed. The ordinary reversal, new MSI qualification, 600-second playback, editing smoke and 30-minute editing did not run. Previous protected and packaged results retain their original identities and qualification scope.

### Direct3D decoder input and physical correctness

Two additional fixed-policy source-first attribution runs included both Direct3D11 video API and DxgKrnl events. The pre-correction worker measured 59.675 FPS, 10 skips and 94.51 ms. The corrected worker measured 58.897 FPS, 32 skips and 220.29 ms. Both held the same controls and exact audio and picture endpoints. In the first trace a decoder spent 42.52 ms acquiring a compressed bitstream input buffer. During that call, 15.60 ms of consecutive samples bracketed the same shared-device hold while both peers and the renderer waited. In the corrected trace a picture-parameter input buffer acquisition took 65.95 ms before the first missing request. Its two peer decoders each waited at least 46.18 ms, and the renderer at least 30.92 ms, within that call. These intervals overlap. The corrected trace had one torn sample and zero lost source requests. Both ETLs reported zero lost buffers and events and bracketed the measured intervals.

In both slow calls the same decoder and buffer type had previously returned the same recorded address. The most recent fence-bearing queue packet issued by the same decoder thread stopped 4.73 ms before the bitstream call began and 2.83 ms into the 65.95 ms picture-parameter call. No DxgKrnl CPU synchronization wait event was emitted on the calling thread during either call. The API trace did not expose a unique physical input-buffer-to-fence association. Neither the repeated address nor those two packet lifetimes establish why the calls remained open. A kernel scheduling trace covering those exact calls could distinguish waiting from descheduling; the current Windows token denied that trace.

This locates a dependency inside D3D11's decoder input-buffer acquisition under the FFmpeg device lock. The 220 ms episode also included ongoing decoded-picture progress and shorter buffer-submission/end-frame calls. The traces establish the wall time of those API calls, while the reason the driver delayed returning the buffers remains unresolved. Additional app-level polling cannot release a driver-owned input buffer. The next investigation should correlate the preceding submission's fence or buffer reuse with these exact calls, before changing shared-device synchronization.

The corrected worker also passed the real producer test for independent refill expiry and guarded retargeting. The 499.5, 500 and 500.5 ms VFR positions matched independent decoded PTS and physical red/blue readback. A genuine backward cut selected PTS 300 for target 400. The pending-rewind test checked 120 layer/frame pairs, sought to the exact new generation and closed during another rewind in 31 ms. All three original recordings retained their hashes and modification times. Raw ETLs, thread identities and private paths stay local. [Reproduction and next investigation](STUDIO_3_6_0_PHASE3B_HANDOFF.md#decoder-input-buffer-investigation).

Follow-up source `4313b88d33b2f362e547d1834dcb895d7a669ed0` rechecks whether the selected picture is still wanted after acquiring the decoder context and before enqueuing a copy. The two-slot trial above belongs to `57309c1`. Its sample windows cannot establish the exact cause of the 40 presentation gaps over 100 ms. There were 39 genuine backward cuts at 90-picture intervals, and 19 of 41 windows with increased skip counters spanned a backward cut. The ordinary measurement does not identify which layer lacked a source interval or a completed copy at those deadlines.
