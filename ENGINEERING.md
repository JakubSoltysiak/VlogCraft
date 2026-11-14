# Architecture and continuation

## 3.4.7 workstation refinement — current continuation

See [workstation report](docs/WORKSTATION_OPTIMIZATION_3_4_7.md). The scheduler uses an owned high-resolution waitable timer and input event, bounded timing histograms/GPU timestamps, a memory-budgeted 3–6 slot completion ring and a 0–6 frame original-PTS prefix cache per active source. Decoder surface allowance includes retained cache frames. Cached selection requires a measured next PTS; no fabricated VFR intervals or interpolated frames. Forward playback holds through small clock rewinds; raw submissions and distinct sequence submissions are separate.

Immediate-context locks remain shared with FFmpeg. The rejected DXGI one/two-frame admission experiments are not enabled. Native clock polling has one request in flight. Manual resolution participates in snapshot invalidation so a 1440p/2160p change actually recreates the monitor. The local diagnostic worker whitelists hardware fields and uses a bounded temporary direct-I/O test; it never changes project/export quality or scans media. Automatic dynamic-quality/worker tuning remains partial.

benchmarks/performance_suite.py and performance_gate.py define repeatable regression levels and strict comparison contracts. Actual CPU topology, power, display mode, GPU/driver, memory and storage are measured; no affinity, power-plan or desktop/HDR setting is forced.

## 3.4.6 native integration — historical checkpoint

See [native contract, ownership, privacy and acceptance](docs/NATIVE_PLAYBACK_3_4_6.md). native_plan.py conservatively admits a supported whole program; native_playback.py owns the child/panel and cancellable raw-PCM producers; native/player.cpp schedules original PTS into a bounded float16 ring. web/native_preview.js coordinates generations, coalesced seeks and the sample-counted AudioWorklet. Shared compiler audio now preserves initial PTS via aresample first_pts=0 and uses anull at 1×. Program preview dependency format 3.4.6/1 invalidates older cached audio.

Actual stream orientation is probed and evaluated; the opaque reference optimization excludes rotated pictures. The D3D sampler clamps each plane to visible bounds to avoid padded chroma edges. Unsupported effects/layout/color contracts fail explicitly into the existing complete SDR renderer; PQ needs an explicit user SDR choice if HDR display is unavailable. Optional packaging includes the already-built native runtime with DLL/license hashes; no schema, cloud or live API change.

The 3.4.6 sustained test reached 125 seconds / 1,500 clips without audio count drift or queue growth beyond fixed bounds, while ~57.2 FPS presentation and skipped frames keep adoption gates open. See VERIFICATION.md for current final package/regression status.

## 3.4.5 investigation — historical checkpoint

The dedicated feature/architecture-investigation branch starts at the existing 3.4 development tip and merges the owner's canonical main roadmap without rewriting history. PR #1 stays draft and unmerged. Read the full [module/ownership audit](docs/ARCHITECTURE_AUDIT.md), [benchmarks](docs/ENGINE_BENCHMARKS.md), [architecture decision](docs/ARCHITECTURE_DECISION.md) and [gates](docs/PERFORMANCE_ROADMAP.md).

Production changes are deliberately narrow: render_engine._opaque_base conservatively bypasses background/alpha composition only with proven source and geometry metadata; preview_dependencies fingerprints actual range/nested/source/proxy/LUT dependencies; preview_cache owns one bounded worker and restart-verified manifests; source_frames atomically registers processes and closes/cancels/reaps them under desktop ownership. The independent video/PCM drains remain. Schema, editing commands and live API behavior are preserved.

The native C++ experiment directly samples NV12/P010 D3D11 decoder textures into float16 and can display an SDR child swapchain beside WebView2. Software/download controls preserve ten-bit ramps. MLT 7.41 CPU image pull, RGBA64 and six-channel PCM were actually exercised. Neither engine is integrated with the project scheduler/effect/audio contract. New MLT 7.42 GPU behavior, D3D12 and Rust performance are unqualified. A continuous FFmpeg raw-frame canvas path is measured but video-only. No experimental dependencies enter the packaged editor.

Final endurance evidence covers a full 600-second generated sequence across 32 files, a 36,000-frame/28,800,000-sample low-resolution export and two independent >5 GiB native imports/exports. The 51.76 callback/s playback result remains below target. Cold original4K range preparation remains seconds despite 29–49 ms cached seeks. Tests and public sanitized records distinguish these scopes; no further engine migration or installer rebuild is part of finalization.

The records below describe the retained 3.4.4 implementation and historical work; newer scoped results and remaining blockers are in the linked investigation and VERIFICATION.md.

The 3.4 work continues from ddb8b55 and studio-3.3-verified on feature/studio-3.4-playback, reviewed in GitHub pull request 1. Public main preserves the verified baseline plus the publication audit. Historical development started from the 3.2 source snapshot, preserved at studio-3.2-source. The 3.1 Windows qualification remains at studio-3.1-verified. The extracted archive is at studio-3.0-original.

## Retained architecture

Each WebView2 window owns a loopback service, project cache and exclusive Windows file lock. Native drop paths link originals. Browser upload streams bounded chunks with 64-bit offsets. Local workers create thumbnails, waveforms, proxies and preview audio. FFmpeg processes render and encode original sources. Existing project commands, media relinking, offline review and explicit AI approval remain the product entry points.

The archive's decimal timeline, unvalidated recovery, independent media clocks and fragmented browser playback needed repair before further interface expansion. Replacing the host would introduce unrelated compatibility work. A continuous native producer/compositor remains the next major transport change, with MLT as one candidate requiring a Windows packaging and color/timestamp parity prototype.

## 3.4 buffered program transport

The buffered transport composes an eight-second window with a continuous video graph and a separate audio graph, then muxes the completed streams. Clip visibility, title timing, source-time animation and sample-delayed mixed audio are evaluated on the sequence clock. Matching source/seek/speed inputs share a decoder within each media type. Decoded comparisons match the segmented export reference across cuts, titles, animated geometry and delayed audio.

preview_cache.py owns a single render worker, two pending ranges, range dependency and renderer-format invalidation, cancellation, atomic publication and a twelve-file/512 MiB complete-file cache budget. Renderer format version participates in the cache key. Shutdown joins cancellation. Obsolete ranges never replace a newer monitor revision.

The browser plays one combined H.264/AAC stream at a time, with a prepared next range. Its clock drives the playhead and remains bounded by the exact range end. The default 540p trades cache preparation time for presentation load. A single AAC/video stream removes independent audio-element synchronization during that mode. Range handoff remains a buffered transport with possible gaps. MSE/native uninterrupted playback and hour-long audio qualification remain future work.

The existing FFmpeg backend was selected for this prototype because its render/reference effects already have acceptance tests. MLT service architecture was reviewed as another candidate, but was not integrated or performance-qualified. D3D11 decoding with hardware download was prototyped on the installed AMD system. It completed but was slower than software on the tested fixture, so production preview decode remains software. GPU composition is outstanding.

## Timing and edit transactions

timing.py stores exact Fraction rates. Schema 4 includes integer sequence-frame positions and source ticks with per-asset time bases. Readable seconds remain for API compatibility. Versions 2 and 3 migrate in memory. The first rational save preserves .v3.bak, while normal .bak publication retains recovery behavior.

source_frames.py streams original presentation timestamps into an atomic disk index and binary-searches it through mmap. Source frame stepping uses original ticks, including held VFR frames. Out marks use the following PTS. Rendering retains a held picture at a non-frame boundary, evaluates output cadence before effects, and budgets 48 kHz audio samples at absolute sequence-frame boundaries.

web/edit_ops.js clones, validates and commits a whole command. Locks, source handles and linked partners constrain operations. Roll, slip, slide, source insertion, overwrite, multiselection and linked camera audio share these primitives. Nested trees project into namespaced playback/render tracks. Expand restores child tracks for editing. Inline pass-through nesting preserves track order and gain but lacks a reusable sequence-reference graph.

## Playback and shared reference

The interactive transport uses AudioContext as its clock, soft rate correction for small media drift and hard seeks for larger drift. Original-media reference frames and paused scopes use the same segment compositor as export.

3.3 adds four pooled video elements and up to four prepared upcoming clips. Eviction disconnects audio nodes and releases media sources. The timeline uses interval indices and viewport culling. Independent audio tracks select a lossless stereo FLAC preview cache, avoiding redundant full-video reads. Cache extraction streams through FFmpeg and publishes by rename. Shutdown cancels active cache processes. Export always reads originals.

Browser playback remains the architectural performance limit. The installed rapid-cut run averaged 57.6 presentation callbacks/s over 70 seconds. Original 4K60 drops frames and multiple original-media layers can stall. Live CSS color/geometry and WebAudio processors differ from the FFmpeg reference. Preview caches do not alter export settings. Sample locking, uninterrupted short-cut decoding and managed display color require a shared continuous transport.

## Compositing, color and motion

Animation expressions share source-time coordinates across trims, speed changes and render segments. Animated alpha, rotation, scale and primary controls, chroma key, ellipse masks and directional wipes run through video_effects.py. grading.py embeds validated SDR cube assets and compiles RGB/master curves and tonal-wheel balance into an FFmpeg LUT. The live monitor samples the same table at reduced spatial resolution. Paused scopes measure the composited reference image.

Motion analysis uses reduced original frames, forward/backward flow validation and feature consensus. Optional robust partial-affine estimation adds camera roll. The application stores source-time correction keys and zoom compensation. Synthetic tests establish known-displacement/roll behavior. Field footage and complex occlusion remain unqualified.

## Rendering and hardware

FFmpeg composites segments on CPU and encodes using a tested local backend. Hosted regression exposed an intermittent FFmpeg 9 drain stall even with a single complex-filter worker. render_range now drains video-only and audio-only jobs independently, then muxes completed files. Each input decodes only its needed media type, and matching inputs share decoding within that type. Intermediate PCM avoids repeated AAC priming. Export concatenates complete segments, encodes final AAC once and atomically replaces the requested destination. Original media paths are protected from export replacement.

Adding output shortest termination lost fractional-rate frames, while bounded input duration damaged seek preroll. Serial decoding and separate demux inputs alone still stalled. Those experiments were rejected. The independent-drain implementation passed 100 repeated renders with all expected frames decoded, the full regression and hosted Windows packaging. This qualifies the reproduced scene and current corpus, with arbitrary long-form/camera-media stress still open. Preview cancellation covers every render/mux stage; its cache format version changed to invalidate prior files.

Runtime probes exercise actual encoders. AMD AMF output is decoded and checked. QSV and NVENC appear only when their probes pass. A failing hardware export retries once with the corresponding CPU codec while retaining project settings and destination atomicity. Tests inject device failure and verify fallback. Complete hardware decoding/filtering is outstanding.

Windows PDH counters collect process-tree GPU engine utilization alongside CPU, working set and I/O. Near-zero driver counters do not establish a GPU-free processing path. Actual selected encoder, valid output and throughput are reported separately. CPU composition remains explicit.

## Approved visual assets

The owner-approved RGBA source stays unmodified in assets/branding. tools/build_branding.py generates premultiplied-alpha Lanczos icons; tests/icon_assets.py and tests/windows_icons.py verify actual PE/MSI/shell/live resources. Web asset routes are explicitly allowlisted. This is a separate asset checkpoint; native scheduling and export are unchanged.

## GitHub and automated checks

Git Credential Manager and the connector were independently verified as JakubSoltysiak before writes. main and all baseline tags were pushed without rewriting. A fresh bare clone passed fsck. Future commits use the requested account name and email. tools/audit_repository.py scans reachable blob, commit and tag objects without exposing credential contents.

Windows Actions pins current official action commits, verifies the FFmpeg archive checksum, checks dependency compatibility and syntax, runs regression and builds/installs/removes the MSI. It does not publish bundled binaries as stable releases. The first hosted run exposed 8.3 short-path assumptions in two tests. Comparing canonical paths corrected those assertions. A later run reproduced the renderer drain stall and drove the independent-stream repair. Hosted regression, packaging and installer lifecycle passed after that repair.

## Offline AI and consent

review_packet.py exports a complete nested manifest and original-media program frames. The user can select the playhead frame. timeline_proposal.py resolves explicit sequence paths and track/clip IDs, validates properties and protects locked ancestors. A digest binds approval to the exact project and proposal. Applying saves a durable undo record. Approved edits also enter ordinary undo/redo.

The optional legacy online connector is preserved at the user's request. Its main-track scope is stated in README and the feature matrix. No live or paid request is part of qualification. Migrating that connector requires a separate integration change.

## Verification and remaining work

VERIFICATION.md is the release report. Test tools preserve logs and measurement JSON under build/qa. Windows lifecycle tests hash project/settings documents through upgrade, removal and reinstall. A subprocess deliberately exits before project replacement to check crash recovery. Large native tests use actual allocated media and additional NTFS paths into two independently allocated large sources.

Priority work is a continuous playback prototype, a real camera acceptance corpus, one-hour synchronization, cache eviction, cancellable probing, clean-Windows and multiple-GPU validation, then HDR/interchange and professional finishing. The current release retains these blockers in FEATURES.md.

## 3.4.8 consistency checkpoint

The measured hot path included WebView DOM/layout and clock IPC, while GPU composition was roughly .7–.8ms. Playhead translation, duplicate-frame/text suppression, accumulated30Hz meter paints and invalidation-driven monitor geometry reduce this work. Meter sampling remains at every animation callback. The native scheduler/PTS selection and PCM clock algorithm are retained; instrumentation adds bounded missed-event traces, playback-only p99, clock/source/Present/lock distinctions and texture-pool estimates. Do not infer GPU occupancy or thread/core placement from these counters.

libx264 uses eight encoder workers only for3840×2160 at most60FPS on16+ logical processors with4GiB available RAM. Other cases retain four; decoder/filter worker defaults remain one. Decoder2/4 and filter-thread experiments were not adopted. The independent video/audio drain and hardware/software fallback paths remain intact.

FULL now runs ten125s trials, five resolutions and600s endurance. Whole-run FPS retains historical end polling. Raw counter windows remain alongside separately labeled active windows excluding terminal holds. Baseline p99 and per-frame variance were not collected; run-mean variance is explicitly distinct. Failure retention must preserve incomplete attempts. windows_session records observer disconnects separately from host status, including intentional diagnostic detach; page-closed state after automation shutdown is not evidence of a physical window closure.

The packaged candidate passed initial repeated targets, but lost WebView targets and longer WebView commit growth remain open. Further work should classify/reproduce those failures, verify recovery/save integrity, diagnose presentation/clock tails, and establish longer heap/physical-sync/full-size gates before HDR integration. See docs/PERFORMANCE_CONSISTENCY_3_4_8.md and canonical TODO.md. No global power/affinity/timer changes or default-native switch were made.
