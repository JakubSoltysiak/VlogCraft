# Professional editing capability matrix

Tested means the specific check in VERIFICATION.md passed. Implemented means code is available with further acceptance coverage needed. Partial identifies implemented behavior with material gaps. Missing identifies an unavailable capability. A test result qualifies its fixture and environment.

3.4.9 is a focused reliability development candidate. Bounded renderer/browser view recovery and acknowledged draft/undo restoration have installed fault tests; repeated-seek AudioWorklet retention has a measured ownership fix. Historical target-loss causes and broader production reliability remain open. [Scope and measurements](docs/RELIABILITY_MEMORY_3_4_9.md).

3.4.8 is a scoped consistency checkpoint. [The report](docs/PERFORMANCE_CONSISTENCY_3_4_8.md) and VERIFICATION.md distinguish passing tests from remaining acceptance gates.

| Current 3.4.9 capability | Status | Verified scope / remaining limits |
|---|---|---|
| Compressed durable recovery history | Tested subset | Installed renderer/browser fault tests compare canonical content of all 80 undo snapshots and project tracks/output; unpublished draft, undo/redo and paused point survive. Matched 1,500-clip checkpoint 40.47 → 4.27 MiB; edit/save median 1.321 s versus unchanged 3.4.8 at 1.202 s. All final180editing batches retain80entries; full long-session memory acceptance remains open. |
| Natural Windows presentation tests | Implemented, tested subset | Real 175% DPI and independently checked child geometry; focus emulation disabled, physical visibility and actual browser/Windows focus recorded separately. Ten alternating visible pairs completed; covered and unfocused controls remain separate. No physical scanout/acoustic-sync claim. |
| Playback consistency preservation | Partial; acceptance incomplete | Final measured348/349 medians59.821/59.798FPS, worst59.701/59.734; all20exact audio/0underruns, but window gate9/10 and7/10. Skips maxima18/22 exceed archived16. Final349600s57.980FPS/1203skips/4.629s gap with lost focus/coverage. All failures retained. |
| Long-session memory and export preservation | Partial; memory/audio blocked | Final600s diagnostic has657underruns despite held sampled visibility and~81.2MiB/min WebView growth. Final30min180batches/80undo/0underruns but one coverage failure, late10.976MiB/min growth; no plateau. Matched exports preserve output, median5.971→4.990s. |
| Persistent offline QA progress | Tested subset | Atomic local status, stable retry IDs, dynamic/unknown totals, retained failures, heartbeat/activity/controller state; 15 focused tests and the no-console GUI refresh/close smoke pass. [Open the viewer](docs/QA_PROGRESS.md). No editor/frame-thread work. |
| QA process ownership | Tested subset | Eight ownership and three production launch tests; hidden suspended-child Jobs, bounded normal shutdown, retained logs and exception/timeout cleanup. Final steps0owned survivors/new terminals. No unowned process-name kills. Historical dozens lack full attribution. |

The following 3.4.8 table retains the earlier qualification and the first scoped 3.4.9 recovery findings; current acceptance is defined by the report above.

| 3.4.8 capability | Status | Verified scope / remaining limits |
|---|---|---|
| WebView failure recovery | Partial | Renderer reload/browser-control recreation preserve acknowledged draft, undo/redo and paused position in installed fault tests; epoch fencing, bounded automatic retry/manual path, observer-only disconnect discrimination and authorized export continuity. Historical lost-target causes, GPU loss, abrupt host death and broad runtime deployment remain unqualified. |
| Memory ownership | Partial | Replaced AudioWorklet processor/PCM/port release verified with paired20-seek object/graph diagnostics; Full clock replies retained after a compact-response experiment failed stress qualification; effective caches remain unchanged. Separate RSS/private commit/heap/role diagnostics and extended-session slope analysis; no general leak-free or physical RAM claim. |
| Repeated native playback | Tested subset | Packaged 10/10 at least59.5 FPS, worst59.637, skips2–16, zero underruns; three original4K + three audio at540p. No sustained full-size4K/zero-skip claim. |
| Browser layout and meter efficiency | Implemented, tested | Compositor playhead, cached monitor geometry, duplicate-paint suppression,30Hz accumulated-peak display. Audio sampling and picture requirements retained. |
| Multicore UHD CPU export | Tested subset | Bounded8 libx264 workers on16+ logical CPUs with4GiB free; other cases retain4. Alternating short export median6.409→4.748s, all180frames decoded; longer/mixed-codec scaling open. |
| Endurance and memory | Partial | Completed600s/7,200clips,59.886FPS,59skips,exact28.8M samples,zero underruns. Prior attempt lost WebView target; WebView memory growth and191.8ms tail remain investigated gates. |
| Failure diagnostics / regression gates | Implemented, tested subset | Partial-trial retention, browser/window events, anonymous thread/core/commit traces, median+worst contracts, source-bound evidence. Automatic browser recovery and true GPU reset remain missing qualification. |
| Original-camera / precision | Tested subset | Three full originals,zero skips/underruns;9PTS seeks,FP16/PQ and decode-sideHDR10+ retention. Explicit SDR exports decoded; calibrated HDR/dynamic metadata mastering unavailable. |
| Windows/offline/icon | Tested subset | Installed two independent>5GiB originals,84decoded4K60frames,undo/recovery/offline approval; MSI lifecycle and seven-size approved icon. Clean-machine/signing/physical Explorer gesture remain open. |

3.4.7 refines the opt-in native preview. [Workstation and performance framework scope](docs/WORKSTATION_OPTIMIZATION_3_4_7.md) documents the candidate and its qualification limits. The 3.4.6 matrix below is a historical checkpoint. The existing full FFmpeg renderer/exporter remains. [Current native scope and fallback matrix](docs/NATIVE_PLAYBACK_3_4_6.md), [verification](VERIFICATION.md) and historical [3.4.5 benchmarks](docs/ENGINE_BENCHMARKS.md) distinguish working behavior from remaining acceptance gates.

| 3.4.7 capability | Status | Verified scope / remaining limits |
|---|---|---|
| Deadline scheduler and original-frame cache | Tested subset | 61 Python +11 JS, exact cached PTS, 600 s /7,200 clips; 59.87 distinct FPS and62 skips at 540p. Native remains experimental. |
| Hardware diagnostics | Tested subset | Actual whitelisted CPU/GPU/memory/storage/DPI/power, bounded128MiB storage, owned process cancellation and reversible preview suggestion. Thermals/NPU inference and other machines unqualified. |
| Native monitor quality / DPI | Partial | Manual540p–2160p and175% measured-client layout; dimensions/source mode explicit. Seamless adaptive resolution/upscaling not adopted. |
| Performance regression framework | Implemented, tested locally | QUICK/STANDARD/FULL, compatible repeated comparisons and CI source-evidence fingerprint. Hosted CI cannot qualify GPU execution. |
| Real source/end timing | Tested subset | Two complete Galaxy-owner-identified HDR recordings and full Google Earth animation; exact sample budgets, zero underruns, bounded VFR/cached PTS checks. Acoustic/calibrated HDR/mixed working spaces remain open. |
| Frame interpolation | Missing in product | Isolated CPU360p MCI ~22FPS; rejected. No generated frames in preview/inspection/export. |

| Native 3.4.6 checkpoint capability | Status | Verification / gap |
|---|---|---|
| Continuous D3D11 preview | Partial, tested subset | Async original H.264/HEVC decode; queues 4/source, GPU ring 3, max 3 active decoders. 125 s / 1,500 clips completed, ~57.2 presented FPS at 540p, 345 skipped frames; no 60 FPS qualification. |
| PCM/audio clock | Tested subset | Exact 6,000,000 samples in 125 s, zero underruns; mono/stereo only, source offsets retained. Acoustic/hour-long/device-change drift pending. |
| PTS/VFR/rational seek | Tested subset | Real-camera bounded PTS seeks and 60000/1001 transport; pause/resume/cancel. Full corpus/long VFR pending. |
| Transforms/keys/nests | Partial | Position/scale/opacity/rotation and supported source-time keys; flatten existing nests. Reference fallback for unsupported visual operations. |
| FP16/PQ/HDR10+ | Partial | Native877-level precision and PQ/scRGB are retained. P0 adds a managed float32 reference/HDR10 slice below. Mixed color is reference-only; HLG/Log, calibrated monitoring and HDR10+ mastering remain unqualified. |
| Native GPU export | Missing | Existing original-media FFmpeg CPU/hardware fallback remains the delivery engine. |
| Actual device reset / calibrated HDR | Missing qualification | Owned-child kill/fallback/retry differs from GPU removal; no physical HDR scanout claim. |

| Capability | Status | Available behavior and remaining gaps |
|---|---|---|
| Approved application icon | Tested on owner workstation | Seven exact icon sizes; EXE/MSI/shortcuts/live window/taskbar/favicon/web checks and lifecycle passed. Original artwork retained; [asset report](docs/ICON_UPDATE.md). |
| Windows desktop and MSI | Tested | Per-user installation, native WebView2, bundled codecs, Start menu and optional desktop shortcut. Release lifecycle evidence is in VERIFICATION.md. Code signing, clean Windows images, WebView2 deployment and DPI/accessibility qualification remain. |
| Large native imports | Tested | Two independent 5,972,550,422-byte (>5 GiB), six-second 4K60 raw MOVs passed the installed 3.4.6 regression as well as the earlier 3.4.5 workflow and 84-frame original export. Earlier allocated 4,977,125,566-byte MOV checks retain their 24-frame scope. Native drop bridge, linked paths, frame beyond 4 GiB, proxy, split, trim, undo, original export. Multi-file tests use two independently allocated MOVs with different picture and audio content, exposed through separate NTFS paths. Structural HTTP/chunk offsets exceed 4 GiB. Physical Explorer gestures and a complete multi-GB browser upload remain unqualified. |
| Media formats | Partial | H.264 MP4, HEVC MOV, raw MOV, FFV1 MOV/MKV, images and audio fixtures. Unknown extensions can be classified from detected media metadata. MTS/M2TS, rotated phone media, long-GOP camera collections, 6K, broad 8K camera-media coverage and corrupt-media fuzzing remain. |
| Rational sequence and source timing | Tested | 3.4 adds 100, 120 and 120000/1001 with 10–400% constant-speed editing. Decoded short 4K120/119.88 and trimmed 8K59.94 H.264 tests pass.  Exact integer and NTSC rational rates, schema-4 sequence frames and source ticks, original VFR PTS index, exclusive out-points, reordered single-frame edits and decoded identifiers. Integer audio sample budgeting avoids join drift. SMPTE drop-frame timecode and frame-exact interactive playback remain. |
| Track and clip editing | Partial | Track controls, snapping, trim, split, move, duplicate/delete, track-local ripple, Ctrl-click multiselection, roll, slip, slide, insert/overwrite and linked camera audio. Commands validate before publishing. Cross-track ripple policy, markers, persistent general edit history, configurable shortcuts and timeline clipboard remain. |
| Nested sequences | Partial | Nested track trees, move/duplicate/delete as a unit, expand for editing, inherited visibility/gain and rendered equivalence checks. Independent nested tabs, reusable sequence references and parent-sequence effects are missing. |
| Playback | Partial | Optional single-stream composited preview uses eight-second continuous FFmpeg ranges, matched-source decoder reuse, render-ahead, cancellation, 540p default and a bounded disk cache. Installed 3.4.4 measurements and initial buffering are recorded in VERIFICATION.md.  Audio-context clock, drift correction, viewport culling and active interval index, bounded video pool and upcoming-cut preloading, lossless audio cache, automatic proxies. Installed decoded-media benchmarks cover 1080p60, 4K30/60, layered effects/audio and 70 seconds of a 1,500-clip sequence. Heavy original-media layers remain slow. No continuous native playback compositor or hour-long sync qualification. |
| Reference monitor | Tested | Paused original-media frame from the export compositor, capped for display. Decoded export/reference comparisons cover animated transforms, mask and chroma. Live CSS/WebAudio processing remains approximate. |
| Keyframes | Partial | Source-time position, gain, rotation, scale, opacity, ellipse radius, brightness, contrast and saturation curves. Linear/hold/Bézier editing and curve clipboard. Anchor point, arbitrary crop, mask-path, wheel/LUT and every-effect automation remain. |
| Transitions and compositing | Partial | Layered alpha, titles, fades, overlap dissolves, directional entrance wipes, chroma key and feathered ellipse. Decoded checks cover visible geometry and wipe direction. Transition handles, arbitrary masks, blend modes, spill suppression and motion-blurred transitions remain. |
| Motion and stabilization | Partial | Feature consensus with forward/backward optical flow checks, translation stabilization, robust affine camera-roll estimation, smoothing, zoom compensation and editable keys. Synthetic encoded translation and roll checks pass. Wildlife occlusion, corrective anchors, planar tracking, rolling shutter and perspective stabilization remain. |
| SDR grading and scopes | Partial | RGB/master five-point curves, three tonal wheels, validated embedded 3D cube LUTs, shared trilinear transforms, paused luma histogram/waveform/vectorscope from the reference. Imported LUT and curve tests pass. Color management, calibrated scopes, skin targets, secondary qualifiers and external monitoring remain. |
| HDR | Partial | Explicit managed PQ/Rec.709 working/output choices and tested HDR10 subset below. Legacy SDR tone mapping remains. Complete metadata indexing, HDR effects, gamut management and mastering acceptance remain open. |
| Audio | Partial | Multitrack mixing, gain, pan, shelves, compressor, peak meter, peak normalization, dialogue-energy ducking and editable gain curves. Original-audio decoded tests cover pan, normalization and ducking. Interactive processors differ from FFmpeg. Loudness/LUFS, noise reduction, sample-locked transport, buses and WAV delivery remain. |
| Offline AI Director | Tested | All-track/nested review manifest, actual composited selected or sampled frames, track-addressed properties, curves, locks and parent checks, approval token bound to exact state, undo and redo. Original media stays local. Creative quality depends on the review assistant and material supplied. |
| Optional online AI | Partial | Existing opt-in legacy main-track request preserved, with no required credential for the editor. Live requests and full multitrack online analysis are unqualified. Speech recognition and autonomous motion-job proposals remain missing. |
| Rendering and GPU | Partial | Original-media 4K60 MP4/AAC, exact NTSC rates, H.264/HEVC/AV1, encoder runtime probes, AMD AMF output validation and software retry after hardware failure. Independent video/audio draining passed 100 decoded repetitions of the previously stalled scene and the complete regression. All six CPU/AMD H.264/HEVC/AV1 smoke paths decode after the repair; the 4K60 export benchmark records its throughput cost. The guarded single opaque base avoids redundant background/alpha work; composition/effects otherwise remain CPU-based. GPU occupancy counters are recorded with driver limitations. NVENC/QSV require other hardware. |
| Background jobs and recovery | Partial | Bounded transfer buffers, asynchronous thumbnails/audio caches/waveforms, proxy progress, queue cancellation/retry, atomic save/export, permanent migration copy, validated fallback revision and actual process-death test. Source-index shutdown now cancels/reaps children; complete program previews have dependency manifests and a restart-aware budget. Current-file import probe interruption, restartable analyses, quotas for other caches, full host/power-loss operation replay and restartable job journals remain. |
| Interface | Partial | Media/source/program monitors, responsive inspector, resizable timeline, culling, curve graph, track settings, grouped audio/color controls, scopes, status and errors. Window scaling and control-image checks are automated. Docking, screen-reader and full high-DPI qualification remain. |
| GitHub and CI | Tested | Public main and preserved tags, account-verified push, secret/history audit, feature branch and draft PR. Hosted Windows regression, build and installer lifecycle pass. Public bundled binary distribution needs corresponding-source review. |
| Experimental engine alternatives | Partial | Real FFmpeg raw-frame canvas, MLT 7.41 image/audio pull and libav/D3D11 GPU-resident float16 composition were benchmarked. Native child surface coexists with WebView2. High-bit ramps and isolated six-channel PCM passed. These are opt-in lab programs; no full effect/VFR/audio/HDR/native-export parity or production integration. |
| High-resolution qualification | Partial | Native 4K120/119.88 source import, slow motion and HFR export, and short 8K59.94 import/trim/export have decoded checks. Long 4K120/8K60, 10-bit combinations, all codec/rate combinations and real-time native-resolution HFR playback remain unqualified. |
| Professional finishing | Missing | Multicam, AAF/OTIO/XML, ProRes/DNxHR intermediates, batch/range delivery, collaborative editing and managed external monitoring. |

## Next development priorities

The owner authorized the independent P0 color slice while the stabilization gates stay open. The next color work follows the measured scope below; it does not close those gates.

1. Incrementally develop the measured native GPU candidate behind parity/fallback gates (docs/ARCHITECTURE_DECISION.md). Replace browser cut scheduling with a continuous decoder/compositor transport behind the current project and command model. Qualify one-hour A/V drift, VFR/B-frame boundaries, proxies and managed color.
2. Add a repeatable camera-media corpus and clean Windows/driver tests. Qualify independent large originals, MTS/HEVC/AV1, DPI, long renders, cancellation and storage failures.
3. Add cache budgets, cancellable probes, resumable background analysis, persistent timeline history and operational diagnostic bundles.
4. Extend the optional API path to the same selected-frame multitrack contract when requested, preserving explicit consent. Add native structural proposal commands with linked timing invariants.
5. Develop HDR/color management, arbitrary animated masks, planar tracking, sample-accurate audio and interchange on the measured continuous engine.

3.4.10 status ([measurements](docs/ROOT_CAUSE_3_4_10.md)):

| Capability | Status | Verification boundary |
|---|---|---|
| PCM graph preparation independent of clock delivery | Implemented, tested | Compiler-barrier clock/Stop/seek and concurrent two-stream budget tests pass; installed PCM/fallback/seek checks pass. Process registration/startup still takes the guard. |
| Reduced meter allocation churn | Implemented, tested | Same peak arithmetic and cadence; two meter tests pass. Matched 90s sampled profiles attribute 62,655,300 bytes before and no samples after to updateMeter. This is not a zero-allocation or retained-memory claim. |
| Recovery and exact checkpoint/history preservation | Implemented, tested subset | Installed renderer/browser fault injection preserves all 80 undo states, draft, tracks/output and paused position. |
| Consistent long-session playback and bounded active memory | Partial, acceptance blocked | Two short matched pairs and one old-host 420s diagnostic do not qualify full-size 4K60 or explain historical 4.629s stalls/657 underruns. Active memory plateau remains unproven. |

## P0 HDR color foundation — 16 November 2026

| Capability | Status | Actual boundary |
|---|---|---|
| Versioned technical color/project contract | Implemented, tested subset | Legacy projects retain SDR behavior. Explicit input profile/range/pixel-aspect overrides, float32 working space and output/metadata decisions survive save/reopen, undo/redo and80-state renderer/browser recovery. |
| High-precision managed composition | Implemented, tested subset | PQ + display-referred Rec.709/BT.1886 to linear Rec.2020; gamma approximation disabled. Full-frame resize, exact right-angle source orientation, trims, rational timing, VFR holds/2× speed, nested tracks, opacity keys/fades and exposure. No8-bit image intermediate in this graph. |
| HDR10 delivery | Implemented, tested subset | Software HEVC Main10,10-bit4:2:0/PQ/Rec.2020, static reference metadata and actual decoded image checks. Full-resolution portrait2160×3840/60 tested for12frames; not a sustained throughput or broad mastering qualification. CPU path is slow. |
| HDR monitoring | Partial | Actual short native PQ/FP16/scRGB display/PCM check on the local active HDR output; uncalibrated and limited native effect subset. Explicit SDR tone-mapped reference/composited monitoring uses the same linear composition. |
| HDR10+ input metadata | Partial | Actual first-frame ST2094-40 detection/sample preservation and original-bitstream association, including private PQ originals. Native decode retention remains. Full frame-indexed extraction/retiming is missing. |
| HDR10+ authoring | Missing | Explicit requests fail; no automatic HDR10 downgrade. Regeneration after picture changes and standards-level decoded validation remain required. |
| HDR masks/LUTs/titles/arbitrary spatial effects | Missing in managed reference/export | Existing SDR tools and the experimental native transform subset remain functional. Unsupported HDR operations fail explicitly rather than silently using SDR maths. |
| HLG / Samsung Log /12-bit corpus | Representation only / unqualified | Future input identifiers persist; HLG/Log rendering fails clearly. Verified input corpus is8/10-bit; native P010 upload does not establish preservation above10-bit. |
| Full production adoption | Blocked | Historical playback/audio/memory gates, HDR parity, gamut/clipping/nits scopes, calibrated external monitoring, long-form sync, hardware/device breadth and release obligations remain open. |

[Detailed results, retained failures and references](docs/HDR_COLOR_FOUNDATION.md).

## P0 real-world editing

| Capability | Status | Verified scope or limit |
|---|---|---|
| Native export path and mixed stills | Tested subset | Installed Save As, Unicode path, cancellation and AMD AMF UHD60. PNG eXIf, transparency, JPEG orientation and camera audio pass generated checks. |
| Export progress and settings | Implemented, tested subset | In-segment FFmpeg frames with audio/mux stage changes. CPU controls match selected encoder. General mixed-scene ETA remains open. |
| HDR10+ per-frame source index | Partial | Bounded local source samples and VFR mapping pass. Full-original timing and present-day decoder coverage remain open. Nonconforming metadata is fenced from reuse. |
| HDR10+ export | Missing | No output mode. Valid preservation and regeneration require independent decoded acceptance. |
| Timeline precision and Project aspect ratio | Implemented, tested subset | Real trim at 600 frames, visible snap guide, undo/redo, zoom anchor, portrait preview and saved canvas settings on a 32-asset fixture. Follow and cursor zoom have narrower coverage. |
| Batch animation, library/audio and storage UX | Open | Existing individual controls remain. Requested batch presets, accessible separation, safe asset removal, icon occupancy and storage management are tracked. |
| Long-form performance and memory | Open | Short export and edit runs do not close the historical playback, audio and active-memory issues. |

[Report and retained attempts](docs/HDR10PLUS_EDITING.md).
