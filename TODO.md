# VlogCraft Studio — Master To-Do List & Product Roadmap

**Canonical living document for the owner, ChatGPT, and Codex.**  
**Project:** [JakubSoltysiak/VlogCraft](https://github.com/JakubSoltysiak/VlogCraft)  
**Last consolidated:** 2026-11-13\
**Source of requirements:** discussions about VlogCraft Studio, the Kenya travel vlog, Samsung Galaxy footage, the 3.0–3.4 development history, and GitHub PR #1.  
**Current development state:** 3.3 verified baseline on main; **3.4.6 native integration is a new stacked development draft**, based on the unmerged **3.4.5 architecture investigation / PR #2** and existing **3.4.4 unmerged DRAFT** on [PR #1](https://github.com/JakubSoltysiak/VlogCraft/pull/1), tagged studio-3.4-development. Do **not** treat draft functionality as a stable release.

> **Mission:** A free, private, offline-first, genuinely capable Windows filmmaking editor. Give one person Premiere-like creative freedom and professional picture/audio quality without cloud processing, subscriptions, arbitrary source-size limits, or unnecessary complexity. Prioritize editing actual travel/wildlife footage over collecting features. It should be delightful for a casual annual vlog yet powerful when needed.

## How to use and maintain this file

- This is the **shared product backlog**, not a declaration that every item is implemented.
- **[x]** means implemented AND adequately verified for the stated scope; **[ ]** means planned, partially done, experimental, unverified, or still needs work. State those nuances in text.
- Priority: **P0** foundational/non-negotiable; **P1** next major feature; **P2** professional upgrades; **P3** interesting long-term ideas; **HOLD** consciously deprioritized.
- Each task has a stable **VC-...** identifier. Keep identifiers when changing its scope or status; update this document in the same PR as the relevant implementation. Link related tests, issues, reports, benchmarks, and commit/PR references.
- Do not mark a feature done because an export preset appears, a function exists, or a tiny synthetic fixture passed. Record hardware, source format, resolution, duration, preview quality, export codec, and evidence.
- The user is the final decision-maker. ChatGPT and Codex can propose changes, add issues, update priorities, and improve descriptions, but must not silently remove requirements or merge a draft PR.
- **Git workflow:** Default-branch TODO.md is canonical. Codex working on feature/studio-3.4-playback should fetch/sync main (or explicitly read main:TODO.md); do not maintain competing independent copies. Never overwrite other people's uncommitted changes. Keep studio-3.3-verified and other verified tags untouched.
- The linked public GitHub repository is a code-sharing choice, **not** permission to upload the owner's camera media, projects, GPS logs, accounts, secrets, or private files.
- Verify hardware/device specifications from authoritative documentation and actual sample files; never fabricate camera calibration, sensor metadata, HDR support, or benchmark results.
- Useful references: [README](README.md), [FEATURES](FEATURES.md), [ENGINEERING](ENGINEERING.md), [VERIFICATION](VERIFICATION.md), [third-party obligations](THIRD_PARTY.md), [PR #1](https://github.com/JakubSoltysiak/VlogCraft/pull/1).

## Quick status snapshot (2026-11-13)

- **3.3 baseline:** native Windows desktop MSI, local media import, multiple video/audio tracks, basic nonlinear editing, nested tracks, keyframes, SDR grading, audio tools, recovery, AI review/proposals, and original-resolution exports. These have specific regression coverage, not blanket professional qualification.
- **3.4.4 draft / PR #1:** buffered FFmpeg composited preview; exact 100/120/120000/1001 rates and 10% constant speed; 8K preset and short real decode/encode tests; independently drained video/audio render fix; hosted Windows CI passed **33 Python + 6 JavaScript tests** and MSI lifecycle. Two independently allocated ~4.98 GB sources passed the reported installed workflow.
- **3.4.4 measured preview:** ~59.67 presented FPS for three video + three audio tracks **with 720p proxies and a 540p composited monitor**. Initial preparation **8.625 s**. This is *not* native 4K60 real-time compositing.
- **3.4.4 measured 4K60 export:** ~16.27 encoded FPS on libx264, ~19.52 on AMD AMF in a three-second synthetic case. These numbers are too slow to call optimized.
- **Current limitations:** CPU composition, eight-second pre-rendered preview ranges, cache-miss stalls and handoff gaps, unreliable GPU-utilization metrics, no verified hour-long sync, only short real-camera qualification, limited HDR tone-mapping/SDR export, stereo-oriented audio, no native HDR10+ authoring.
- The current source is a **standalone VlogCraft codebase**, not a fork containing an ArtCraft editor engine; residual historical ArtCraft text in old README files is background only. Keep investigating real bottlenecks rather than deleting unrelated code.

## Architecture investigation checkpoint (3.4.5 development)

The owner added this canonical roadmap on main; the investigation branch merged that revision before editing it. Existing requirements and stable identifiers remain. See [audit](docs/ARCHITECTURE_AUDIT.md), [benchmarks and raw results](docs/ENGINE_BENCHMARKS.md), [decision](docs/ARCHITECTURE_DECISION.md) and [engineering gates](docs/PERFORMANCE_ROADMAP.md). Broad P0 requirements remain unchecked where camera/long-form/parity acceptance is incomplete.

- [x] **VC-ARCH-001 — Scoped competing-engine experiment.** Real moving images through FFmpeg software, MLT 7.41 CPU C ABI and C++ libav/D3D11 resident/download/software controls; 20 matched configurations × 3 repetitions at 540p/4K, static scale/position/alpha, original4K60 H.264. Not full editor/effect/audio parity or MLT 7.42 GPU qualification.
- [x] **VC-ARCH-002 — Conservative opaque-base fastpath.** Actual format/SAR metadata gates the optimization; unknown/alpha/transformed cases retain fallback. Decoded test passed. Three-second original4K60 single-stream export median 7.326 → 6.101 s, unchanged bitrate/preset, three repeats/version; not a generalized layered throughput claim.
- [x] **VC-ARCH-003 — Range-dependent persistent program cache.** Relevant nested clips, source/proxy identity, solo context, LUTs and renderer version; restart/corruption/budget tests; bounded two pending snapshots. Unrelated caption trial 12.717 s rebuild → .001731 s hit, identical MP4 bytes. Complete-file limit 12/512 MiB excludes in-flight outputs and other cache families.
- [x] **VC-ARCH-004 — Source-index shutdown ownership.** Atomic process registration, cancel/terminate/wait/reap, native before/after reproduction and deterministic race/owned-child tests. Does not solve cancellable import probing or all background-job lifetimes.
- [x] **VC-ARCH-005 — Narrow precision/channel capability proofs.** Native P010/float16 and MLT RGBA64 retain 877 ramp levels; isolated MLT six-channel 48 kHz PCM is bit-exact for 2 s. Not product HDR, managed color, multichannel routing or Atmos.
- [ ] **VC-ARCH-006 — Continuous native engine integration.** Preferred next slice, with WebView2 retained. 3.4.6 opt-in preview now has bounded asynchronous queues, source PTS/VFR, PCM audio master, supported transforms/keys and whole-program SDR fallback. 125 s / 1,500 clips completed at ~57.2 presented FPS (540p from three originals4K); full effect/HDR/device-reset and sustained 60 FPS acceptance remain open.
- [x] **VC-ARCH-008 — Scoped final synthetic endurance and large-file checks.** Installed 600-second/1,500-clip sequence across 32 distinct 720p sources reached its end; 51.76 callbacks/s remains below target. The full 320×180/60 export decoded 36,000 video and 28,800,000 stereo sample frames without accumulated count error. Two independent 5,972,550,422-byte originals passed installed native editing/export. This is not hour-long, real-camera, acoustic-sync or long4K qualification.
- [ ] **VC-ARCH-007 — Complete architecture acceptance matrix.** Three private recordings now have bounded PTS/precision/orientation checks and scoped GUI/audio tests; long camera sessions, MLT 7.42 GPU, D3D12, native complex effects, long original4K/HEVC/VFR, acoustic drift, GPU occupancy, physical presentation/disk I/O and other GPU vendors remain unqualified. Partial synthetic coverage is documented rather than marking these complete.

## Native integration checkpoint (3.4.6 development)

Review: [draft PR #3](https://github.com/JakubSoltysiak/VlogCraft/pull/3), stacked on PR #2. [Hosted checks](https://github.com/JakubSoltysiak/VlogCraft/pull/3/checks) compile/package only; local GPU evidence has separate scope.

See [implementation and capability matrix](docs/NATIVE_PLAYBACK_3_4_6.md) and [measured verification](VERIFICATION.md). The three private originals are ignored and used read-only; technical public reports contain aliases only. All raw media, private metadata, images and source identifiers stay local. Prior PRs remain unmerged and historical tags remain intact.

- [x] **VC-NATIVE-001 — Opt-in bounded scheduler.** Three active original H.264/HEVC decoders, four queued frames/source, three FP16 GPU slots, async completion, rational sequence/source units, held-PTS seek, adjacent-cut decoder reuse and owned cancellation. Scope: tests/report; not full-corpus acceptance.
- [x] **VC-NATIVE-002 — Shared stereo PCM transport.** Existing audio compiler over local raw PCM, fixed ring/backpressure, source offsets and identity speed, generation cancellation and coalesced seeking. Exact 6,000,000 sample count / zero underruns over 125 s; acoustic/hour-long/multichannel gates remain.
- [x] **VC-NATIVE-003 — Conservative parity admission.** Supported transforms/keys/nests; explicit whole-program reference fallback for unsupported effects/color/layout. P010/PQ ramp and scoped layered reference comparison pass. No silent skipped effects or forced HDR-to-SDR native display.
- [ ] **VC-NATIVE-004 — Production adoption.** ~57.2 presented FPS and 345 skipped frames in the 125 s test miss 60 FPS. Actual device reset, calibrated HDR/mixed working spaces, complex effects and 10–60 min real-camera/independent long-source sessions are unqualified. Keep existing renderer/default.
- [ ] **VC-NATIVE-005 — Full high precision delivery.** Native decode/FP16/PQ/scRGB is partial; HDR10+ side data retained at decode only. HLG/Log/APV, dynamic-metadata mastering, HDR export and multichannel routing remain missing. Existing export stays explicit SDR/stereo.

## P0 — Make the editor usable, fast, safe, and truly offline

### Real editing experience and acceptance
- [ ] **VC-P0-001 — Real-world 4K60 is the primary optimization target.** Optimize for Galaxy S25 Ultra HEVC 10-bit / Samsung Log / HDR footage, long Kenya travel recordings, mixed footage, music, titles, 3+ video layers and 3+ audio tracks. Nominal 60 FPS requires measuring *fully composited presentation*, not only video-element callbacks.
- [ ] **VC-P0-002 — Immediate first frame and responsive seeking.** Measured current-range/cached-file original4K→540p seeks 29–49 ms, but uncached ranges 2.4–10 s and first range 12.476 s in one trial. Aim for under ~1 s first preview frame and under ~250 ms typical proxy seeks as **aspirational benchmarks**, with cold/warm/cache-miss measurements. Correct playback matters more than artificially hitting targets.
- [ ] **VC-P0-003 — Gap-free continuous transport.** Remove audible/visible stalls at cuts and eight-second preview range boundaries, including frequent seeking, mixed framerates, VFR, B-frames, titles, effects, transitions, nested sequences and changes while playing.
- [ ] **VC-P0-004 — Reduce export cost without reviving deadlocks.** Profile video-only, audio-only, mux, scratch-file, concat and process-launch overhead. Preserve the repaired FFmpeg drain fix and exact frame/sample output. Benchmark throughput, CPU/RAM, file size and visual integrity.
- [ ] **VC-P0-005 — Large-file/no-copy workflow.** Preserve native Explorer drag/drop and linked originals above 4.5 GiB (test multiple independent >5 GiB files), 64-bit offsets, seek beyond 4 GiB, proxy/resume/relink, and original-quality export. No app-side file-size cap or loading an entire recording into RAM.
- [ ] **VC-P0-006 — Extended real-session validation.** Include 10–60 min uninterrupted sessions, 1,500+ cuts (including **independent** files), long audio synchronization, VFR and damaged files, arbitrary effects, interruption/restart, SSD/RAM pressure, disk-full, and cancellation. Synthetic 6-frame/12-second tests are not substitutes.
- [ ] **VC-P0-007 — Restore correctness for every change.** Preview-versus-export tests for colors, keyframes, compositing, masks, transitions, crop/orientation, nested clips, audio phase/layout, timebase and output frame count; compare decoded pictures/audio, not just metadata.

### Architecture study before committing to a rewrite
- [ ] **VC-P0-008 — Whole-repository profiler audit.** Measure local input probes, FFmpeg process starts, demux/decode, CPU filters, GPU surfaces/transfers, graphics, WebView2, audio, cache hashing/eviction, filesystem I/O, export, UI re-render, and long-term memory/handle leaks. Classify confirmed bottlenecks vs guesses.
- [ ] **VC-P0-009 — Fair competing prototypes.** Benchmark **(A)** optimized existing FFmpeg transport, **(B)** MLT-based continuous engine, and **(C)** native FFmpeg/libav + D3D11/D3D12 GPU-resident decoding/compositing. Evaluate licensing, Windows packaging, color/timestamp correctness, maintenance cost and testing. Choose from data, not fashion.
- [ ] **VC-P0-010 — No wasteful preview encode→mux→decode loop.** Investigate direct decoded-frame presentation and native/GPU rendering surface, avoiding intermediate H.264 MP4 where practical; keep an accurate fallback until validated.
- [ ] **VC-P0-011 — GPU end-to-end, not encoder-only.** Detect AMD Radeon 890M first, plus Intel/NVIDIA as available. Test zero/low-copy decode→GPU effect→composite→display; quantify CPU↔GPU transfer. Preserve software fallbacks and do not assume D3D11VA helps if frames are immediately downloaded to CPU.
- [ ] **VC-P0-012 — Preserve editor compatibility.** Retain the existing schema (including prior v2/v3 migrations), exact rational timing, command model, track edits, projects, AI approvals, recovery, Windows MSI and keyboard shortcuts during any engine migration. Feature flags and parity tests before switching defaults.
- [ ] **VC-P0-013 — Single coherent image/audio pipeline.** Interactive preview, paused reference, composited preview and final export should evaluate the same effects/clock semantics at selectable quality. Eliminate CSS/WebAudio versus FFmpeg discrepancies rather than merely hiding them.

### Caching, responsive UI and background work
- [ ] **VC-P0-014 — Dependency-aware cache invalidation.** Key by source, ranges, effects, proxy resolution and relevant processing parameters; changing a caption at 02:15 should not discard unrelated preview regions. Bound memory/disk; handle corruption, orphan files, crashes and revision changes.
- [ ] **VC-P0-015 — Adaptive proxy and preview strategy.** Choose efficient codecs/resolutions based on media format, machine capability, SSD usage and effect load; adjust preview to 540p/720p/1080p/4K as needed, never change export-quality originals. Offer user override and clearly show proxy/native mode.
- [ ] **VC-P0-016 — Predictive cache and seamless prefetch.** Prepare next cuts, likely seek destinations, thumbnails, waveforms and audio asynchronously; prioritize foreground interactions; cancel obsolete work; avoid monopolizing CPU/SSD during playback.
- [ ] **VC-P0-017 — Performance diagnostics panel.** Present actual decode/composite/present FPS, dropped frames, seek latency, cache hit/miss, prepare time, RAM/VRAM/shared GPU memory, CPU/GPU encode/decode and disk throughput with evidence-safe metrics, plus optional redacted diagnostic bundles.
- [ ] **VC-P0-018 — Robust job queue and recovery.** Restartable proxies, cancellable metadata probes/motion analysis, progress, safe temp file cleanup, autosave, crash recovery, validated backups, offline project relinking and useful errors.

### Non-negotiable privacy and Windows delivery
- [ ] **VC-P0-019 — Fully offline-first core.** Editing/import/preview, metadata detection, proxies, tracking/stabilization, HDR handling, rendering, export and project operations must work with network blocked, without sign-in, activation, subscription, cloud compute, telemetry or background media upload. Localhost (127.0.0.1) UI server is **local**, not cloud.
- [ ] **VC-P0-020 — Explicit network-consent boundary.** Only user-triggered optional OpenAI/API/chat actions may contact the internet. List exactly what frames/manifest are sent; no originals unless separately and explicitly approved. Keep credentials out of projects/logs/repository.
- [ ] **VC-P0-021 — Clean Windows 11 installer.** Complete MSI install/launch/upgrade/uninstall, no-internet installation path including WebView2 runtime strategy, DPI/scaling, OLED/high-DPI UI, Windows Defender/smart screen considerations, accessible input, shortcuts, optional code signing and rollback protection.
- [ ] **VC-P0-022 — GitHub discipline.** Public repo with no private footage, license/provenance/FFmpeg GPL or LGPL compliance before binary redistribution, pinned dependencies, security audit, reproducible Windows CI, test artifacts, release channels, no premature stable tag; keep 3.4 PR #1 draft until reviewed.
- [ ] **VC-P0-023 — Personal-first UX.** Big-media import should lead quickly to **watch the full raw footage**, organize shots, cut a travel vlog, add music/photos and export. Easy mode without restricting an advanced inspector. No mandatory enterprise/collaboration setup.

## P1 — HDR-first professional picture and Galaxy-native workflows

### Real HDR, not just an HDR-labelled file
- [ ] **VC-HDR-001 — True high-bit-depth processing.** Plan 10-bit/12-bit input and suitable 16-bit float or other high-precision internal linear/light/color representation; avoid forcing 8-bit yuv420p in the HDR path. Validate transforms, effects, alpha and gamut integrity.
- [ ] **VC-HDR-002 — Correctly identify color.** Parse primaries, transfer function, matrix, range, bit depth, mastering display/CLL/FALL, ICC/other applicable metadata and HLG vs PQ vs Log; distinguish missing/contradictory metadata and allow manual overrides.
- [ ] **VC-HDR-003 — HDR10 end-to-end.** Import, calibrated preview, trim/grade/effects, 10-bit HEVC/appropriate codec export, Rec.2020 + PQ signalling and valid static HDR metadata. Preserve legitimate input metadata where applicable; test transformed clips with test patterns and a real TV.
- [ ] **VC-HDR-004 — HDR10+ dynamic metadata.** Detect SMPTE ST 2094-40 and associated Samsung HDR10+ signalling; map metadata across trim, speed changes and joins. Pass through **only when still valid**; after grading/compositing/scaling, require validated recomputation or clearly degrade to HDR10 with an explicit warning. No fake HDR10+ labels.
- [ ] **VC-HDR-005 — Samsung Log.** Recognize Samsung's documented Log encoding on supported models/modes; integrate official/referenced transforms or validated math with licensing checked. Offer Log→Rec.709, Log→HDR/PQ, technical transform vs creative look, and an optional user LUT. Never automatically bake a look into original files.
- [ ] **VC-HDR-006 — HLG workflows.** Handle HDR HLG capture, correct transfer and color metadata, HLG→PQ/SDR as user chooses, correct export tags and mixed HLG/PQ sequences.
- [ ] **VC-HDR-007 — Managed display/reference.** Accurate SDR/HDR preview on Windows HDR displays (including user's OLED and HDR-capable Samsung TV), calibration/brightness guidance, tone-mapped SDR fallback for SDR screens; evaluate whether WebView2 is sufficient or native HDR swapchain required.
- [ ] **VC-HDR-008 — SDR conversion and mixed media.** High-quality tone mapping with predictable highlight roll-off, gamut compression and skin tones; let SDR titles/photos/music coexist with HDR footage; never silently convert whole HDR projects to SDR.
- [ ] **VC-HDR-009 — HDR grading and scopes.** Exposure in stops, white balance, correct scene/display-referred transforms, curves/wheels, 3D LUTs, qualifiers, shot matching, nits-labelled waveform/parade/vectorscope, clipping and out-of-gamut warnings.
- [ ] **VC-HDR-010 — Validation corpus.** Test actual Galaxy S25 Ultra SDR/HLG/HDR10+/Samsung Log clips across different lenses, lighting, orientation, 4K60, VFR/HEVC and 10-bit; compare known references, metadata parsing and visual output. No sample = no claim of verified mode.

### Samsung / general camera profile library — user-requested major feature
- [ ] **VC-CAM-001 — Bundled offline camera-profile library.** Root-level selectable **Camera Profiles** UI (manufacturer→product→camera/lens→recording mode), with search, favorites and one-click user profile for **Galaxy S25 Ultra**. Data stored locally, versioned and editable; no cloud lookup needed at import time.
- [ ] **VC-CAM-002 — Expand Samsung devices systematically.** Start with Galaxy S23/S24/S25/S26 families incl. Plus/Ultra, then Galaxy Z Fold/Flip generations, limited to *real, verified released devices* and region/firmware variants; add Galaxy Book/other cameras only when useful. Do not blindly fill unknown fields. Design schema to add DJI, Sony, Canon, GoPro, etc.
- [ ] **VC-CAM-003 — Per-lens verified optical data.** Main/ultrawide/telephoto/front camera, sensor/crop when documented, actual and 35mm-equivalent focal length, aperture, OIS/EIS, autofocus, video capability, lens identity, digital zoom/crop modes, and confidence/provenance. Separate still-photo specs from video capture paths.
- [ ] **VC-CAM-004 — Distortion correction, never guess.** Use official or measured lens/calibration data only when available. Detect whether Samsung already corrected ultrawide distortion in-camera; avoid double correction. Give user override and calibration wizard; store device/firmware/resolution-specific coefficients plus verification.
- [ ] **VC-CAM-005 — Recording-mode matrix.** Verified supported codecs/containers, 4K60/120, 8K30/60 (only where actually available), 8/10-bit, Samsung Log, HLG, HDR10+, stabilization, zoom/lens restrictions, bitrate/profile, VFR and external storage restrictions.
- [ ] **VC-CAM-006 — Camera microphone and audio profile.** Microphone number/location, beamforming/zoom-in mic and stereo/spatial capabilities **only if documented or measured**; identify recording codec, sample rate, channel layout, orientation, any 360/binaural content and external mic source. Don't infer microphone calibration from model name.
- [ ] **VC-CAM-007 — Exhaustive, privacy-aware metadata inspector.** Parse via ffprobe, ExifTool (if suitable/licensable) and format-specific parsers: make/model, lens, 35mm/physical focal length, f-number, ISO, shutter/exposure, timestamp, duration, resolution/aspect, rotation/orientation, codec/profile, bit depth, chroma, HDR tags, frame-rate rational and VFR, bitrate, color space, audio codec/channels and GPS **when present**. Show unavailable/unknown, not fabricated defaults.
- [ ] **VC-CAM-008 — Automatic device/recording recognition.** Identify Galaxy model/mode from reliable make/model/QuickTime metadata and stream characteristics. Show confidence, conflicts and explainable evidence; fall back to generic codec-based profile. Allow manual camera/lens override per asset or batch.
- [ ] **VC-CAM-009 — Actually use metadata.** Correct rotation, sequence frame rate, conform/VFR handling, color management, Log transform, HDR mode, proxy strategy, audio channel mapping, stabilization parameters if compatible motion samples exist, and default export settings. Do not alter original files or secretly bake irreversible corrections.
- [ ] **VC-CAM-010 — Useful media organization.** Search/filter/sort footage by camera, lens, date, location (opt-in), FPS, HDR/Log mode, orientation, focal length, resolution and codec; multi-select edits, bins, duplicates and smart collections.
- [ ] **VC-CAM-011 — Profiles must be maintainable.** Define a validated JSON/YAML schema, per-field sources/URLs, documentation revision dates, confidence level, testing method, device firmware, camera app/mode, and change log. Add unknown fields as null, not approximations. Include user-created and imported/exported profiles.
- [ ] **VC-CAM-012 — Privacy controls.** Make GPS and other identifiable metadata local-only; user-selectable strip/copy/retain policy on export, with warning if location or device identifiers would leak.
- [ ] **VC-CAM-013 — Samsung Studio handoff (research).** Investigate whether Galaxy mobile Studio project files can be exported/transferred and whether lawful documented/open formats permit conversion; offer a lossless timeline interchange only if feasible. Do not claim it exists before testing.
- [ ] **VC-CAM-014 — Easy Galaxy-to-PC ingest.** Support Windows file picker/Explorer, USB/media folder import, and optionally OS-native phone transfer workflows where available; do not depend on a Galaxy Book or Samsung cloud service.
- [ ] **VC-CAM-015 — Camera-aware export profiles.** Simple outputs for Galaxy playback, HDR10+ Samsung television compatibility when genuine metadata is valid, standard YouTube/SDR/HDR and archival masters; avoid claiming every Samsung device accepts every codec.

### Modern codecs, resolution, speed
- [ ] **VC-VID-001 — 4K60 best-in-class.** Main reference target 3840×2160 60/1 and 60000/1001 across 10-bit HEVC, H.264, HDR/Log, multiple layers, long source durations, audio/music, stabilization and export.
- [ ] **VC-VID-002 — Genuine 4K120.** Support 120/1 and 120000/1001 import/trim/slow-motion/edit/export; long real-camera checks and precise 24/30/60/120 timeline conforming. 3.4.4 only qualified short samples.
- [ ] **VC-VID-003 — Genuine 8K60.** 7680×4320, 60/1 and 60000/1001, high-bit-depth imports, correct storage/memory handling, proxy edit and valid long-form export; distinguish compatibility from live 8K preview. 3.4.4 only qualified a tiny H.264 sample.
- [ ] **VC-VID-004 — Samsung APV codec.** Verify contemporary Samsung device support per generation (do not assume S25 Ultra records APV). Test FFmpeg APV decode, pixel format, 4:2:2, metadata, audio and reliability; research APV encode/intermediate options and licensing/hardware limits. Use HEVC where APV isn't available.
- [ ] **VC-VID-005 — Broader camera media.** H.264, HEVC, AV1, APV, MOV, MP4, MKV, WebM, MTS/M2TS, portrait/orientation, VFR, 8/10/12-bit and mixed camera sources; unsupported assets give diagnostics.
- [ ] **VC-VID-006 — Professional export controls.** HEVC/AV1/H.264 selectable encoders and hardware fallback, CRF/bitrate/profile, resolution/rational FPS, proper HDR signalling, multi-audio-track options, progress/cancel/resume where possible, inspect/validate final media.
- [ ] **VC-VID-007 — Future intermediates.** Evaluate ProRes/DNxHR/APV mezzanine/proxy codecs, user-selectable lossless/high-quality intermediate workflow and realistic SSD footprint; not required for simple import.
- [ ] **VC-VID-008 — Speed ramping.** Smooth keyframed speed curves, reverse playback, native HFR slow motion, and frame interpolation/optical flow when justified; avoid false claims of motion fidelity on difficult wildlife shots.

## P2 — Audio and cinematic post-production

- [ ] **VC-AUD-001 — Preserve source sound.** Support stereo and standard 5.1/7.1 channel-layout identification and sensible routing; do not fold multichannel to stereo unexpectedly. Document source format and downstream container/codec limitations.
- [ ] **VC-AUD-002 — Stream-copy passthrough when technically safe.** If the soundtrack is completely unmodified and container/timebase/cut structure allows it, preserve original multichannel/Atmos-encoded or other compatible audio bitstream without re-encoding. Any mixing, cuts, effects or tempo edits may preclude simple bitstream passthrough. Never pretend copied metadata survives destructive audio changes automatically.
- [ ] **VC-AUD-003 — Multichannel editing/export.** Proper 5.1/7.1 tracks, channel assignment, monitoring/downmix, peak/LUFS loudness, routing and sample-accurate A/V transport. Stereo mode stays simple by default.
- [ ] **VC-AUD-004 — Samsung 360 Audio and binaural recordings.** Examine real recordings and identify whether stored sound is binaural stereo, multichannel, or another format; preserve it, monitor appropriately and avoid fake channel mapping. Don't assume Galaxy Buds capture 5.1.2.
- [ ] **VC-AUD-005 — Spatial/height audio research.** Investigate 5.1.2/7.1.2 monitoring and 3D positioning using lawful, free/open Windows audio capabilities. Clarify that a speaker layout is **not** a Dolby Atmos bitstream.
- [ ] **VC-AUD-006 — Dolby Atmos is optional, not mandatory.** Research legitimate toolchain/licensing and passthrough paths. Avoid subscription/licensing costs unless the user explicitly approves. Genuine Atmos object mastering/export is lower priority than preservation and standard multichannel support.
- [ ] **VC-AUD-007 — Basic audio polish for travel videos.** Simple dialogue/wildlife sound level controls, music under narration, clip gain/fades, pan, ducking, EQ/compression, loudness normalization and limiter; clear headphone/TV downmix options.
- [ ] **VC-AUD-008 — Advanced noise cleanup.** Optional offline noise reduction for wind/hiss and voice clarity, with conservative settings to protect bird/insect/ambient wildlife sounds. Galaxy AI Audio Eraser-like source separation is **LOW priority** and not a requirement.
- [ ] **VC-AUD-009 — Music/photo montage workflow.** Easy photo duration, Ken Burns pans/zooms, beat-aware timing/markers (optional), orchestral soundtrack fading/ducking, intentional ambient sound preservation, licensed/user-provided music. No automatic copyrighted music downloading.
- [ ] **VC-AUD-010 — Pro audio masters (later).** WAV/PCM multichannel delivery, stems, buses, metering/limiting, optional spatial mastering interchange, sample-accurate edit/export validation.

## P2 — Remaining professional editing functions (not at the expense of 4K60)

- [ ] **VC-EDIT-001 — Timeline quality-of-life.** Persistent cross-session undo history, markers, named sequences, configurable shortcuts, clip clipboard, full cross-track ripple rules, precision frame stepping, edit-point navigation, keyboard-driven trimming and timeline snapping.
- [ ] **VC-EDIT-002 — Professional nesting.** Reusable independent nested sequences/tabs, proper parent effects, nesting round trips and reliable linked source audio behavior.
- [ ] **VC-EDIT-003 — Keyframes and effects.** Better graph editor, anchors, crop and arbitrary/Bezier masks, mask paths/tracking, blend modes, alpha matte, chroma spill removal, blur and motion blur, transform interpolation, sophisticated wipes/transitions and editable effect presets.
- [ ] **VC-EDIT-004 — Advanced motion and stabilization.** Better optical flow, robust planar/perspective tracking, auto horizon/camera roll, occluded wildlife handling, rolling shutter correction and optional metadata-based gyro stabilization **only when compatible motion metadata exists**.
- [ ] **VC-EDIT-005 — Creative grading and matching.** Shot-match tools, color management, camera LUT presets, skin-tone vectors, secondary qualifiers and mask-based corrections; never silently flatten Log/HDR.
- [ ] **VC-EDIT-006 — Multicam.** Synchronize multiple camera angles and audio, angle monitor and live cuts; useful for future productions, not essential to the original Kenya vlog.
- [ ] **VC-EDIT-007 — Automatic subtitles/transcription.** Offline-first speech-to-text where licensed/feasible; SRT/VTT import/export, captions styling and burnt-in vs selectable subtitles.
- [ ] **VC-EDIT-008 — Image and motion graphics.** High-res still/photo library, Ken Burns movement, PNG alpha, SVG/titles where safe, text animation, credits, graphic templates and photo slideshow creation.
- [ ] **VC-EDIT-009 — Professional interchange.** OTIO, FCPXML/XML, EDL, AAF where feasible/licensable; verify round trips and clearly explain unsupported effects. Collaboration tooling remains low priority.
- [ ] **VC-EDIT-010 — Batch/range export.** Queue multiple versions, render marked ranges, export horizontal/vertical crops, social/TV presets and preserve export reports. No cloud accounts.
- [ ] **VC-EDIT-011 — Polish interface.** Attractive coherent native Windows UI, docking/multiple panels, source/program monitor, comprehensive inspector, timeline tracks, effects search, clear feedback, accessibility, OLED/high-DPI and shortcut discovery without clutter.
- [ ] **VC-EDIT-012 — Quality/reliability extras.** Automatic scene detection and optional shot tagging, smart reframing, proxy relink, progress estimates, optional media integrity checks, missing codecs/error explanations, local diagnostics and selective cache cleanup.
- [ ] **VC-EDIT-013 — Advanced visual AI (later).** Optional offline object removal or content-aware fills, face/object tracking, auto reframing and highlight suggestions; benchmark quality and privacy, not placeholders.

## P2 — AI-assisted editing (explicit consent, offline core)

- [x] **VC-AI-001 — Offline review/proposal foundation.** Existing review MP4/frame packs and multitrack/nested timeline manifests can be manually shared, with exact-state proposal approval and undo/redo; bounded by existing implementation and tests.
- [ ] **VC-AI-002 — Unified all-track online API contract.** The optional direct API path is legacy main-track; migrate it to the same multitrack/nested proposal schema, with explicit upload preview and user approval. Never apply AI suggestions automatically.
- [ ] **VC-AI-003 — Intelligent editing suggestions.** Pacing, best wildlife moments, shaky clips, overexposed/HDR mismatches, soundtrack cues, speech sections and duplicate takes; give rationale and previewable reversible actions, not autonomous destructive editing.
- [ ] **VC-AI-004 — Offline assistant where feasible.** Local heuristic/media analysis without paid models; optional downloadable local models only with explicit user action, transparent disk/RAM usage and no hidden network dependency.
- [ ] **VC-AI-005 — Privacy, cost and safety.** No need for API credentials to edit; ChatGPT subscription is **not** an OpenAI API credit. If calling paid API, estimate/declare cost and exactly what frames/metadata leave the computer. No hidden uploads, secrets in project files, or automatic publication.

## P3 — Device experience, finishing, and research backlog

- [ ] **VC-FUT-001 — Cross-device workflows.** Evaluate Samsung phone→Windows transfer, Samsung Studio project migration only if project format is genuinely accessible, and Galaxy-friendly export presets without Galaxy Book restriction.
- [ ] **VC-FUT-002 — HDR10+ and spatial playback QA on real Samsung TV.** Test actual playback compatibility, correct HDR banners/transfer/metadata, 5.1/7.1 audio/channel downmix, 16:9 4K display and any device-specific limitations. Don't assume TV Atmos/HDMI behavior without testing.
- [ ] **VC-FUT-003 — 4K120/8K60 long-term performance.** GPU capability-aware proxy preview, realistic storage/scratch limits and long encode tests; don't promise real-time 8K on integrated graphics.
- [ ] **VC-FUT-004 — Advanced restoration.** Better denoise/deblur/super-resolution, de-flicker, rolling shutter, motion interpolation; optional offline processing and explicit original preservation.
- [ ] **VC-FUT-005 — Extensible but controlled architecture.** Plugin/effect ABI, tested version upgrades, reproducible benchmark corpus and stable contracts between UI/timeline/media engine; don't create a huge plugin system before core performance is solid.
- [ ] **VC-FUT-006 — Open-source/community readiness.** Decide project license separately after provenance review; clear contributing/build docs and security policy; public releases only when compliant. Private-first product requirements survive public source.
- [ ] **VC-FUT-007 — Other hardware support.** Windows AMD priority, eventually NVIDIA/Intel decode/render/encode validation; cross-platform Linux/macOS is optional and must not delay the owner's Windows workflow.
- [ ] **VC-FUT-008 — Efficient editing presets.** One-click **Galaxy 4K60 SDR**, **Galaxy 4K60 Samsung Log**, **Galaxy HDR10+**, **Travel vlog**, **Wildlife ambience**, **Photo montage**, and **Samsung TV master**, each transparently showing what it changes; presets are helpful defaults, never forced irreversible processing.

## Explicitly deprioritized / avoid scope creep (HOLD)

- [ ] **VC-HOLD-001 — Cloud editing/render farms.** Do not pursue. VlogCraft must remain local.
- [ ] **VC-HOLD-002 — Subscriptions, account login, telemetry, commercial SaaS integrations.** Do not add as core requirements.
- [ ] **VC-HOLD-003 — Team collaboration, shared cloud workspaces, concurrent co-editing, enterprise permissions.** Not needed for the owner's personal filmmaking; GitHub public source is not product collaboration.
- [ ] **VC-HOLD-004 — Full Atmos object mastering and elaborate 3D sound editing.** Only revisit if there is demonstrated interest and a legitimate practical toolchain; first support straightforward preservation and multichannel playback.
- [ ] **VC-HOLD-005 — Galaxy AI Audio Eraser clone.** Low value to the owner; simple offline noise cleanup suffices initially.
- [ ] **VC-HOLD-006 — Rewrite every component into Rust/C++ solely for modernity.** Use profiling and measured experiments; preserve working Python/UI/project layers until a replacement is justified.
- [ ] **VC-HOLD-007 — Invented Samsung features or fabricated calibration numbers.** Never extrapolate device/lens capability from another model or claim Samsung-specific processing without evidence.
- [ ] **VC-HOLD-008 — Declare full Premiere parity or production readiness prematurely.** Keep a candid feature matrix and acceptance criteria.

## Proposed implementation order (flexible, not a promise of release dates)

1. **Architecture study now has measured prototypes and safe production fixes** on a separate architecture-investigation draft. Continue with the native scheduler/parity milestone in docs/PERFORMANCE_ROADMAP.md; retain PR #1 and all fallbacks.
2. **Continuous local 4K60 editing engine**, quick preview/cache, no cut gaps, responsive projects, and long-form real-camera testing.
3. **HDR-first color architecture** with high-precision precision-preserving frames and proper Windows/TV preview.
4. **Full HDR10, HDR10+, HLG and Samsung Log workflows**, 10-bit HEVC exports, dynamic metadata correctness, and camera sample acceptance.
5. **Bundled Galaxy Camera Profiles + automatic recognition + metadata inspector**, starting with S25 Ultra, then verified S/Z families; one-click presets and privacy controls.
6. **APV and broader camera codecs**, reliable 4K120 and 8K60 import/export using proxies as needed.
7. **Surround/audio preservation, 360 Audio where documented**, easy music/photo workflows; spatial authoring optional.
8. **Premiere-style finishing** — speed ramps, advanced masks, color tools, multicam, subtitles, interchange, batch export, etc.
9. **Release hardening:** accurate docs, offline firewall tests, Windows CI/installer, long-duration recovery, appropriate project and dependency licenses.

## Acceptance scenarios that matter to the owner

- **Kenya-vlog scenario:** Import many large phone/camera originals with no copies; watch the entire raw shoot, scrub comfortably, select wildlife highlights, insert still photos, add orchestral soundtrack while preserving ambient animal calls, export a reliable 4K60 film offline.
- **Samsung Log/HDR scenario:** Import S25 Ultra mixed SDR/Log/HLG/HDR10+ clips, auto-identify what is *actually* present, make technically correct color transforms, grade without destructive conversion, and explicitly choose valid HDR10+/HDR10/SDR delivery.
- **Galaxy profile scenario:** Choose **S25 Ultra** or automatically detect it. Show lens/aperture/focal length/ISO/shutter/codec/rotation/HDR/GPS **only where embedded or reliably derivable**, and distinguish camera capabilities from clip evidence. Allow confident manual correction.
- **Home theater scenario:** Correctly recognize input audio layout, preserve the original spatial/multichannel stream when possible, or produce a clearly labelled suitable downmix/remix; no fake Atmos claim. Deliver video compatible with a Samsung 4K HDR TV.
- **Offline scenario:** Disconnect internet after installation; all media/library/timeline/audio/color/proxy/export/project functions continue to work. Only an explicit online ChatGPT/OpenAI action fails gracefully or asks for connectivity.
- **Stress scenario:** Multiple independent >4.5 GB recordings, mixed VFR/4K60 and one long sequence with numerous cuts/effects; no memory blow-up, hang, data loss or silent export frame/metadata corruption.

## Definition of done for each item

1. Implemented functionality (not a non-working UI stub) and applicable legal/licensing constraints checked.
2. Automated unit/integration tests, and native Windows packaged smoke/lifecycle tests for affected paths.
3. Representative real footage and metadata fixtures where feasible, with source provenance and privacy protection.
4. Measured performance/quality, exact hardware and configuration, and regression comparison against baseline.
5. Failure behavior and recovery tested; originals and older projects remain intact.
6. README, FEATURES.md, ENGINEERING.md, VERIFICATION.md and **this TODO.md** updated in the same PR.
7. The owner explicitly chooses when to accept/merge a major development milestone.

---

**Maintainer note:** This document deliberately captures both essential requirements and future ideas so none are lost. It is a roadmap and a prioritization aid, **not** a promise to build everything or a claim that incomplete Samsung/HDR/Atmos capabilities already work.