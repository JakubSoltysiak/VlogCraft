# Architecture audit — 3.4.5 development, 13 November 2026

This investigation continues 3.4.4 and preserves the 3.3 baseline. The experimental engines do not replace the editor. [Measurements](ENGINE_BENCHMARKS.md), [decision](ARCHITECTURE_DECISION.md), [implementation gates](PERFORMANCE_ROADMAP.md) and the canonical [roadmap](../TODO.md) define the scope.

## Execution map

~~~mermaid
flowchart TD
    W[desktop.py: native drop, project window, lock] --> S[server.py: loopback API and project state]
    UI[WebView2: timeline, inspector, monitor] <--> S
    UI --> LIVE[interactive video elements / WebAudio clock]
    UI --> PROGRAM[rendered_preview.js: one buffered A/V stream]
    S --> PC[preview_cache.py: one worker, bounded pending requests]
    PC --> PD[preview_dependencies.py: range and source identity]
    PC --> R[render_engine.py: original/project effect compiler]
    S --> R
    R --> V[FFmpeg video-only graph / CPU filters]
    R --> A[FFmpeg audio-only graph / PCM]
    V --> M[mux / atomic delivery]
    A --> M
    M --> PROGRAM
    S --> INDEX[source_frames.py: original PTS disk index / mmap]
    S --> BG[thumbnail / waveform / proxy / FLAC workers]
    S --> STORE[project_store.py: validate, atomic replace, backups]
    S --> AI[offline review and proposal approval]
~~~

The UI and loopback service run locally. Native Explorer drop passes paths; it does not serialize whole recordings. Browser upload streams chunks. Media HTTP responses support byte ranges. Source originals remain linked; final exports read originals. A proxy can support editing when its original is offline; export still requires the source. There is no application file-size ceiling.

## Component inventory and ownership

| Component | Execution and responsibilities | Limits / audit outcome |
|---|---|---|
| desktop.py | Windows .NET/pywebview window, drop bridge, project lock, host lifetime | Now closes the PTS indexing service and reaps its child before returning. Native DPI/clean-image deployment still needs qualification. |
| server.py | Threaded loopback API, validation, import, job scheduling, render endpoints, bounded chunk upload | Probe records actual pixel format, SAR, color tags, audio layout/rate. Ordinary probes remain synchronous; huge/corrupt camera probes need timeout/cancel acceptance. |
| project_store.py | Validated atomic project publication, recovery, backup retention | Crash-before-replace regression retained. General edit history is not persistent across sessions. |
| timing.py / web/timebase.js | Fraction rates; frame/tick migration, source time bases, sample budgeting | Preserve schema 4 and older-format backup. Drop-frame display and native-prototype VFR parity remain. |
| source_frames.py / web/source_frames.js | ffprobe PTS scan to disk, mmap/binary-search lookup, exclusive out marks | Full initial scan delays first exact source step. Launch/cancel race and shutdown ownership fixed; lazy GOP indexing remains a design task. |
| sequences.py / web/nesting.js | Pass-through nested track expansion and namespaced playback | Not a reusable independent sequence DAG with tabs and parent effects. |
| web/edit_ops.js / edit_commands.js | Clone/validate/commit commands, locks, handles, linked partners, roll/slip/slide/insert/overwrite | Existing six JS suites retained. Cross-track ripple policy and broader command histories remain. |
| animation.py / video_effects.py | Source-time expressions, transforms, alpha, wipes, key/mask parameters | CPU FFmpeg filters; ellipse mask confirmed expensive. Native prototype has static geometry/alpha only. |
| grading.py / web/grade.js | Validated SDR LUTs, curves/wheels, sampled live LUT, paused scopes | Current grading/export has an 8-bit SDR boundary. Not a managed HDR pipeline. |
| motion.py / web/motion.js | Reduced-resolution optical flow, forward/backward checks, partial-affine correction keys | Synthetic displacement/roll tests; difficult field occlusion and gyro/rolling shutter unqualified. |
| audio_edit.py / web/audio.js | EQ/compression/gain/pan/ducking; AudioContext transport/meter | Interactive WebAudio approximates FFmpeg effects. Production routing/cache/export is stereo, not multichannel preservation. |
| audio_cache.py / waveform.py | Separate streamed FLAC extraction and waveform jobs | No evidence that duplicate waveform reads dominate this corpus; do not replace from that hypothesis alone. |
| render_engine.py / encoders.py | Shared reference/export graph, per-media-type decoder reuse, original export, tested hardware-encode fallback | CPU composition dominates. Video and PCM audio MUST drain independently before mux. |
| preview_cache.py / preview_dependencies.py | One worker, at most two pending snapshots, range dependencies, persistent verified manifests, global complete-file budget | New restart/stale/corrupt/eviction tests. A running render plus temporary outputs can exceed the complete-file budget; not a whole-cache-volume quota. |
| web/rendered_preview.js | Eight-second H.264/AAC windows, prepared next range, revision-aware publication | Correct shared composition, but startup and range handoffs can stall. Not gap-free transport. |
| web/playback_cache.js / monitor.js | Pooled video elements, decoder lookahead, hard/soft synchronization; original paused reference | Interactive effects differ from export; video-element callbacks do not prove the whole multilayer program was composed. |
| web/timeline.js / studio.js / app.js | Interval indexing, viewport culling, selection, scroll, library and inspector | Measured UI synchronous work is below the 60 Hz frame budget on the tested 1,500-clip/32-asset scene. |
| review_packet.py / timeline_proposal.py / ai_bridge.py | Offline multitrack manifests and exact-state explicit proposal approval | Offline approval/undo/redo/reload retained. Legacy optional online main-track connector is unchanged; no paid requests used. |
| packaging / tests / GitHub Actions | Bundled per-user MSI, lifecycle retention, native automation, regression | Local hardware tests and hosted CPU checks have distinct scopes. No public binary redistribution is approved by a passing build. |

## Confirmed costs and dispositions

All times below are generated fixtures on the owner's workstation, not field-camera guarantees. Full methods and raw records are linked in the benchmark report.

| Path / issue | Measured cost | Cause and improvement | Risk and verification |
|---|---|---|---|
| render_engine.segment_command opaque base | 3 s 4K60 export median 7.326 → 6.101 s | Previously composited a known full-frame opaque picture over black through RGBA. Conservative metadata/geometry/alpha guard now bypasses redundant background overlay. | Low/medium: unknown metadata and alpha/geometry cases retain old path. Decoded-picture and guard tests, exact 180-frame export. Bitrate/preset unchanged. |
| preview range identity | Unrelated edit previously 12.717 s rebuild; now 0.001731 s hit on the same three-original-4K scene | Whole-project fingerprints discarded unaffected regions. Dependencies now include relevant nested clips, actual sources/proxies/LUTs, global solo semantics and renderer version. | Medium: hidden dependency omission could show stale pixels. Tests cover nested/range changes, solo, source mutation, stale/offline proxy, restart and corruption; cache experiment produced identical bytes. |
| preview scheduling/retention | Unbounded executor snapshots were possible behind “two pending” bookkeeping | Replaced executor queue with one owned condition/worker; at most two pending snapshots. Restored files enter the same 12-file/512 MiB complete-file budget. | Medium: cancellation/publish race. Existing cancellation plus persistence/budget tests pass. Temporary in-flight files are separately scoped. |
| source_frames launch/close | Native close reproduced a surviving ffprobe indexing child | Process construction and registration now atomic under guard; close marks cancellation, terminates, waits, kills if needed and reaps. Desktop finally owns close. | Medium: lifecycle race; deterministic close-before-launch test, real owned-child test, actual native import/index/close before/after. |
| CPU mask graph | 120 original 4K frames → 540p: ellipse mask 20.973 s vs scale 1.747 s | Per-pixel GEQ mask evaluation dominates this fixture. Next: cached analytic GPU coverage, preserving source-time animation. | High parity risk: no production mask rewrite in this change. Compare alpha edges and animated mask/export images first. |
| full original video render | Video ~6.57–6.89 s of historical ~7.3 s export; audio/mux/concat much smaller | Decode + CPU composition + encode; AMF only accelerates encoding. Native-resident decode/composite avoids a download/reupload path. | High migration risk: isolated native prototype only; retain production fallback. |
| preview startup / encoded windows | Raw-pipe first canvas frame 0.284–0.309 s; three-layer throughput only 29.35–29.98 FPS | Removing intermediate encode/mux gives fast first pixels but CPU graph remains limiting and RGBA transport copies heavily. | Video-only throughput experiment. No A/V clock, pacing or production replacement. |
| cold vs cached program seek | First range 12.476 s; uncached seeks 2.420/10.007 s versus current/reopened cache .029–.0495 s | Pre-rendering full ranges and launching fresh producers dominate cache misses. Continuous GPU/audio scheduler is the next slice. | High timing/effect parity risk: measured paused media readiness, not panel display. Keep full renderer fallback. |
| exact source step | Initial HEVC index 5.122 s; warm lookup median 0.0003155 s | One complete streamed PTS scan then mmap search. | Lazy seeking must preserve reordered/VFR PTS correctness; current exact path retained. |
| subprocess / metadata | Start median 0.04035 s; probe 0.06772 s | Repeated process/decoder initialization matters at many cuts. | Persistent producer requires generation/cancellation ownership and bounded queues; unimplemented. |
| original audio / waveform | 4.977 GB source FLAC extraction 0.074 s; waveform original 0.07039 s vs FLAC 0.06631 s | Container seeking avoids reading all video. Waveform outputs were not byte-identical. | This fixture does not justify a waveform-cache rewrite; long compressed audio remains unqualified. |
| serialization / save | 1,500 clips: encode 0.03159 s; durable save median 0.14154 s, range 0.0719–0.2742 | JSON validation/serialization plus filesystem publication | Not the dominant transport cost. Preserve recovery; defer format replacement. |
| UI redraw | Timeline synchronous median 4.9 ms/p95 9.7 ms; selection 1.9/2.4 ms | Interval/culling strategy is useful. 32 library assets ≠ 1,500 asset library. | Retain UI. High DPI/accessibility, larger libraries and 120 Hz budgets still need tests. |

## Hypotheses and remaining ownership gaps

Decoder reuse currently exists within a graph/media type and the live pool, not across independently launched rendered windows. Eight-second lookahead is cancellation-aware but not a persistent decoded-frame scheduler. It can compete with foreground jobs. Cache sizing is not yet adaptive to free SSD space, GPU memory, source HDR/codec, or timeline complexity. Thumbnail/waveform/proxy/audio caches need unified lifetime, disk-pressure and cancellation stress testing. Peak working set alone does not establish absence of a slow leak.

No field-camera path has been provided yet. Real VFR/Log/HDR10+/orientation/long-GOP media, acoustic synchronization, one-hour sessions, thermal behavior, low disk space, driver resets, clean Windows and NVIDIA/Intel remain qualification gaps. Two independently allocated >5 GiB native fixtures and a complete ten-minute synthetic playback/render now have scoped results; hour-long and original4K endurance remain open. The sustained synthetic test reports its actual drops rather than treating nominal 60 FPS as achieved.

## Preservation

The existing independent video/audio drain fix, original-source export, rational project migration, undo/recovery, all editing/effect/AI tests, offline core and native no-size-limit imports remain. The only shipped performance changes are the guarded opaque fastpath and range cache; the resource fix adds deterministic index shutdown. Experimental code is opt-in and not imported by the packaged editor.
