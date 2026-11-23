# Architecture and continuation

## 3.6.0 Phase 3B editing transport

The playback worker owns up to three decoders. After acknowledging an exact paused picture it can prepare an upcoming source within two sequence seconds. At most two inactive decoders share a 896 MiB budget for decoded texture arrays. Only one unopened source starts preparation at a time. A compatible source returning at the same media boundary can continue from its queued pictures. A discontinuous source resets to its requested timestamp. The compositor retains submitted pictures until its GPU queries complete. The presentation loop services every active layer while waiting for an exact picture.

The opt-in local trace records monotonic decoder, D3D11 lock and presentation intervals above 2 ms. Its fixed storage retains recent events, the longest calls and the neighborhoods of three large missed-frame events. A source number identifies a stream within the test session. Concurrent call durations can overlap. The active GPU allocation, estimated standby texture payload, and OS working set measure different resources.

Ruler movement paints the playhead at the animation-frame cadence. Transient native seeks keep the latest target, pace decoder resets while a target is in flight, and hold the target while awaiting its generation. Only the committed position prepares PCM and writes recovery. A release on the same frame reuses its seek generation. The worker reports the first completed paused target and fences obsolete GPU submissions. The full playback clock and existing FFmpeg fallback remain available. Windows background proxy encoding runs at below-normal process priority with its existing output and cancellation contract. [Phase 3B measurements](docs/STUDIO_3_6_0_PHASE3B_PLAYBACK.md).

On three-layer backward cuts the worker may begin a source rewind up to three sequence frames early when each remaining outgoing selection has a decoded PTS bracket. The old tail and incoming queue share the four-picture budget. A generation change drops the pending handoff. The ordinary seek path handles unproven intervals. This preserves continuous playback timing and limits extra ownership to references to already allocated surfaces.


## 3.6.0 Phase 3A GPU export verification

The full-master path can rebuild one bounded failed GOP with the managed graph, reuse the remaining closed segments, reauthor from decoded pictures and rerun the complete acceptance gate. The first-export path has independent software source-clock checks, a separately rendered audio graph and selected managed PQ picture checks. The optional Radeon runtime limits that policy to short straight-cut projects using the qualified output profile. [Phase 3A architecture and measurements](docs/STUDIO_3_6_0_PHASE3A_EXPORT.md).

## 3.6.0 Phase 2D saved-project GPU export

`native_project_plan.py` compiles the validated saved timeline, managed span boundaries and original presentation clocks into a private D3D11 worker program. `native_project_render.py` supplies only the video spans to the existing segment exporter. Managed audio, x265 settings, output timing and final-picture HDR10+ authoring stay shared. The optional Windows development runtime verifies every delivered picture and exact decoded PCM against a prior reference master before publication. A rejected native attempt retries the entire project with the managed renderer. Project serialization, reference presets, original media and preview use their existing paths. [Phase 2D architecture and results](docs/STUDIO_3_6_0_RENDERING_PHASE2D.md).

## 3.6.0 Phase 2C HDR delivery

The optional authoring path enlarges the Windows pipe and uses a native exact MaxRGB histogram with bounded, ordered workers. The existing PQ ranks, payload serializer and verification still operate on final decoded pictures. The resident decoder experiment uses the compositor device for libav D3D11VA, validates original PTS and normalizes tested NV12/P010 sources through compute into reusable linear slots. Driver or admission failure retries the software input, and delivery requires independent output validation. [Phase 2C evidence](docs/STUDIO_3_6_0_RENDERING_PHASE2C.md).

## 3.6.0 Phase 2B HDR delivery

The render lab compares the frozen zimg converter, bounded independent zimg workers and a D3D11 compute conversion from FP32 Rec.2020 to packed limited-range PQ 4:2:0. The CPU branch preserves error diffusion and emits in frame order. The GPU path uses ordered dithering and reads back one quarter of the former float payload. The live test admits H.264 SDR and HEVC PQ with verified original PTS and updates only changed texture slots. A separate opt-in saved-project tool may replace the final managed HDR stage with the exact CPU conversion. It retains the existing project graph, audio, metadata and reference fallback. [Phase 2B evidence](docs/STUDIO_3_6_0_RENDERING_PHASE2B.md).

## 3.6.0 Phase 2 rendering lab

`experiments/render_phase2` implements a shared premultiplied linear float compositor for scalar C++, SSE2 with reusable worker rows, and D3D11 compute with reusable surfaces. Both processors use the same row coverage intervals to preserve hard half-pixel boundaries. In the export lab, one staged D3D11 picture is packed to planar float in a reused buffer and sent over a bounded pipe to the existing FFmpeg/zimg and x265 Main10 delivery path. Both processes are joined on failure. Clock normalization, muxing and HDR10+ authoring use existing code. Renderer selection in the installed editor remains on the Phase 1 implementation. [Phase 2 report](docs/STUDIO_3_6_0_RENDERING_PHASE2.md).

## 3.6.0 managed rendering

The managed compositor bounds FFmpeg picture-filter slicing at four workers. zimg conversions, resizing and error diffusion keep the reference single slice. Motion expressions reuse per-row values while retaining float32 premultiplied bilinear sampling. Static still frames are prepared before repetition. Opacity keys and fades can vary the coverage independently of prepared RGB. Direct RGB and alpha maps avoid intermediate grayscale RGB copies. Source cadence, PCM, encoder settings and HDR10+ authoring keep their existing contracts. [Rendering evidence](docs/STUDIO_3_6_0_RENDERING.md).

## 3.5.7 HDR creative layers and cuts

`hdr_layers.py` decodes sRGB color separately from coverage, then combines float32 planes. Premultiplied geometry keeps RGB and coverage aligned. Direct plane extraction avoids the RGB format conversion that clipped linear values above reference white. Existing compatible opaque video uses the prior path. Title glyphs are an app-owned temporary raster. Existing project clip keys and an optional title font drive the same Reference, Composited and export paths.

`timeline_transitions.py` validates adjacent cut IDs, frame counts, actual source handles and conflicts before deriving temporary playback ranges. Managed dissolves blend whole composited alternatives in linear light. PCM envelopes use absolute 48 kHz sample positions mapped from the sequence frame clock. Boundary state stays in the project and undo snapshots. Preview uses the same geometry and envelopes and subdivides video composition at transition limits. Native and Live Layers use Composited fallback when required.

`export_scratch.py` records a scratch folder identity and takes an exclusive OS lease before a render starts. Known artifacts are removed on normal completion, cancellation or failure. The manual Storage action requires a valid stale ownership record and checks source references, path identity, contents and live media workers. [Development report](docs/STUDIO_3_5_7_HDR_EDITING.md).

## 3.5.6 edited HDR10+

The managed reference path still composites in float32 linear Rec.2020, then delivers HEVC Main10 PQ. Short independently encoded GOPs can have different decode delays. The final managed HDR mux validates exact CFR presentation coverage and establishes a continuous decode clock while retaining original presentation timestamps and compressed pictures. The AAC path is unchanged for standard delivery.

Edited Master independently decodes the final PQ encode in presentation order, computes whole-frame linear maxRGB statistics and records compact Profile A payloads on disk. The transport matches generated single-picture MP4 fragments to original packets, uses PTS to select each payload in decode order, and remuxes with the original AAC. Exact packet timing, compressed picture bytes with the intended SEI and AAC hashes gate atomic publication. Playback and recovery structures remain unchanged. [Engineering decision, tests and scope](docs/STUDIO_3_5_6_HDR10PLUS.md).

## 3.5.5 HDR10+ preservation and project editing

`hdr10plus_bitstream.py` independently reads registered SEI from original length-prefixed HEVC samples. FFprobe supplies packet offsets and rational timestamps. The local comparison matches decoded cached fields against the original integers by presentation time. `hdr10plus_export.py` gates the explicit complete-source copy path on matching video/audio/project properties, frame timestamps and conforming frame-associated metadata. It probes the temporary remux and compares compressed packet hashes, PTS/DTS/durations and stream configuration before publishing. The existing renderer remains responsible for configured SDR and HDR10 delivery. Edited HDR10+ needs output-picture analysis and validation.

Motion presets generate regular source-time keys with an optional preset marker, which lets replacement/clear preserve manual edits. The project output snapshot keeps new-clip defaults with undo and on-disk state. The same snapshot holds IDs hidden by library removal, with validation against referenced clips including nested sequences. The archive retains original asset records and supports undo, relink and restore. Storage cleanup deletes only eligible app-owned removed-asset thumbnail paths after confirmation and guards active sharing, media paths and symlinks. [Qualification](docs/STUDIO_3_5_5.md).

## 3.4.9 recovery and resource ownership

`desktop_recovery.py` owns a bounded event-driven WebView recovery controller and one coalescing atomic checkpoint writer. Renderer failure reloads the view; browser failure recreates its control. The host/backend/project lock survive. Epoch-fenced saves reject late obsolete-view requests; a completed newer save outranks an older draft. Startup drafts must match the published project digest. `web/recovery.js` captures acknowledged draft/UI/undo changes without credentials/media or periodic polling. Recovery stops native preview/PCM, restores paused, and limits automatic retries. Storage failures are observable and do not prevent remaining shutdown cleanup.

History checkpoints capture immutable JSON before asynchronous native gzip compression, with a raw JSON fallback and compatibility with earlier undo/redo checkpoints. The backend stores the encoded history without expanding all 80 snapshots on every edit; restoration validates/decompresses it. UI-only coalescing preserves pending document/history work. Failed submissions retain the newest work and retry only at the next checkpoint. The atomic writer acknowledges publication, not queue admission. Per-owner cleanup begin/end/failure events identify shutdown ownership without introducing hot-path polling.

Native-clock commands and full responses retain the baseline transport. A compact unchanged-status response experiment was reverted after a 600-second diagnostic and controlled arms exposed audio/timing regressions; byte-allocation savings do not justify that tradeoff. Replacement audio worklets receive explicit dispose, return false, clear PCM/handlers and close ports; pause retains the current node. Stop releases the backend snapshot and joins its status reader. Native C++, frame cache, GPU pools, preview resolution and encoder-worker policy are unchanged.

[The evidence report](docs/RELIABILITY_MEMORY_3_4_9.md) defines the tested boundaries. QUICK remains deterministic correctness/precision; STANDARD adds transport, recovery, worklet ownership, seeking, short playback/export; FULL adds ten consistency runs, preview tiers, ten-minute endurance, lifecycle/pressure/background recovery and separate ten-minute memory/thirty-minute editing diagnostics. The memory observer uses actual timestamps, separate RSS/private commit/heap/role counters and approximate HAC slope intervals; GC is diagnostic after stop only. FULL measurements require equivalent power/runtime/workload and investigation of every failure/outlier. Hosted CI validates correctness/build/install, not hardware timing or a memory plateau.

Windows sessions clear DevTools device-metric emulation by default. A forced DPR1 viewport at 175% Windows scaling misplaces the native child and is reserved behind `legacy_viewport` for historical timing reproduction. `benchmarks/window_geometry.py` independently compares HWND/client coordinates against DOM bounds at actual window DPI. Protected timing retains the declared 356 × 200 physical surface through DPI-aware CSS; it does not reduce composition resolution. Resize/recovery checks use actual physical geometry.

Playwright 1.65.1 also enables artificial page focus unless CDP is attached with `no_defaults=True`. The default Windows session and 3.4.9 recovery reattachments now use that option. The legacy focus override remains explicit for reproduction. Physical coverage, Windows foreground ownership and actual `document.hasFocus()` are distinct recorded conditions; successful CDP attachment or a topmost style alone proves none of them. The QA helper can temporarily join its input queue to the foreground thread to focus only its owned test window, detaching immediately. Visible and local opaque-cover modes are measured separately. Root progress reads use existing files without opening new console windows during presentation measurements.

Protected wall-time FPS remains unchanged and includes endpoint observation latency. Mean active Present interval, active one/ten-second windows and all skipped frames are additional evidence, not substitute passing scores. The earlier 1.3-second active presentation gap remains a real outlier. A failed visibility fixture is retained as unqualified; it must not be relabelled a failed application or silently omitted. New natural-focus paired trials use identical conditions in both frozen 3.4.8 and current 3.4.9.

`tools/performance_record.py` binds evidence to both application sources and the benchmark driver/observer sources. Changing viewport, focus handling, sampling, workload generation or qualification profiles therefore invalidates the protocol binding even when application code is unchanged. Focused tests verify rejection of a changed quality driver and stable bindings across LF/CRLF checkouts. A matching fingerprint establishes provenance, not a passing hardware-performance result.

Use `python benchmarks/run_qa.py --results build/qa/<run>/supervisor -- <command> <arguments>` for supervised background qualification. `benchmarks/owned_process.py` creates each Windows child suspended, assigns it to a kill-on-job-close Job Object, then resumes its sole primary thread. Nested jobs contain the app and its descendants before they can escape during startup. The test supervisor owns the handle; disconnecting its Codex/CDP observer does not close it. Normal app shutdown runs first. Required forced cleanup remains a failed release result, with logs preserved. No process-name/global-terminal termination is used. Before/after visible-console counts exclude titles and command lines; headless console hosts are distinguished from visible terminal windows.

`tests/qa_guard/sitecustomize.py` explicitly enables hidden console subprocesses only for QA Python drivers and composes with the existing loopback-only network guard. The packager explicitly excludes both `sitecustomize` and `benchmarks`, and bundle verification checks that exclusion. Eight Windows ownership tests cover descendants, timeout, exceptions, abrupt supervisor exit, unrelated-process preservation, diagnostic failures, standard Windows environment recovery, log retention and continued execution after an observation pipe disconnects.

The frozen GUI also needed an independent production correction: metadata probes, thumbnail FFmpeg and the default render CLI now use `CREATE_NO_WINDOW`. A reproduced close left three, then six console-host members; forced cleanup left empty Windows Terminal windows. The corrected installed application closes normally without these survivors. Command arguments, encoder settings and rendering policy are unchanged. Three focused launch tests include a real `pythonw` parent without the QA subprocess shim. Historical terminal windows without ownership records remain unattributed.

Background QA launched from a host missing `APPDATA` restores absent standard profile folders using Windows known-folder APIs, preserving supplied values and logging only restored key names. The observer readiness predicate guards an undeclared `state` before optional chaining. Earlier ReferenceError attempts never reached playback and remain in the ledger; additional numbered attempts complete the workload count. A real playback failure or poor score is never replaced automatically.

The attached 30-minute editing diagnostic remains a failed visibility attempt even though all 180 batches and its audio gate completed. A disappearing native child between enumeration and rectangle lookup is now recorded as a surface-replacement transition, while genuine API failures and focus changes remain failures. `benchmarks/detached_editing.py` provides a separate bounded attribution fixture: it runs editing commands in the view and fully detaches DevTools during active measurement. Its autonomous timer exists only in the test fixture. Heap/GC observations occur after active editing and an idle period; they do not establish a plateau on their own or add a periodic collector to the product.

## 3.4.7 workstation foundation — retained

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

The persistent QA tracker is isolated in `benchmarks/qa_progress.py`: atomic cross-process status, immutable attempt history, stable case IDs, dynamic/unknown totals, two-second supervisor CPU/I/O activity and stale/dead-controller detection. It has no editor/frame callback. QUICK/STANDARD/FULL register leaf cases without counting the parent twice. The offline no-console viewer and commands are documented in [QA_PROGRESS](docs/QA_PROGRESS.md). Status remains ignored at build/qa/status.json.

3.4.10 observer diagnostics use a monotonic deadline, separate reconnect/query tail and natural idle before post-stop GC. Offline extraction separates counter jumps from uncalibrated visibility timestamps; it cannot identify allocation stacks or individual Present event times.

The subsequent 3.4.10 PCM correction retains the immutable published snapshot under Controller.guard, then copies/compiles outside the guard. Launch registration rechecks closed state, generation, snapshot identity and the two-process budget under the guard. Stop/seek invalidate pending preparation before launch; preparation exceptions remove temporary files. Process startup remains under the registration guard. Full clock response, PCM accounting and capacities remain unchanged. Four compiler-barrier/race tests exercise these invariants.

## P0 managed color foundation

color_management.py defines the version1 optional output.color contract and per-clip technical inputColor overrides. Assets retain bounded, whitelisted colorMetadata sampled from streams/first decoded HDR frame; source timing and immutable original-bitstream associations remain. Unknown/inconsistent tags require interpretation rather than filename/device guesses. HLG and Samsung Log identifiers are reserved and persisted without claiming implemented transforms. Existing project version4 and legacy SDR semantics remain; optional color fields are not a promise that older binaries understand HDR projects.

hdr_render.py is opt-in through render_engine.segment_command for managed video. Working RGB is float32 linear Rec.2020,1.0=100nits. PQ is display-referred; SDR Rec.709 uses the pinned zimg ideal-black BT.1886 policy and an explicit reference-white value. Independent mid-gray tests distinguish this from inverse camera OETF. Managed zscale stages explicitly disable approximate gamma. Source and output primaries/matrix/transfer/range are specified, and automatic intermediate format conversion is disabled. Native FP16 scRGB uses1.0=80nits; that unit distinction is deliberate. Native canvas follows project aspect with even dimensions;16:9 dimensions remain unchanged.

Supported reference operations retain full-canvas float32 through orientation/resize/linear alpha and exposure. Unqualified effects/geometry/HLG/Log raise explicit errors. The failed float32 pad negotiation is retained; no8-bit padding workaround is inserted. HDR10 output is CPU HEVC Main10/yuv420p10le/PQ2020 with optional validated declarations of mastering/content-light data. All source frame side data is removed before fresh output signalling. User declarations are not measured/recomputed light levels. HDR10+ output is rejected; source samples and original associations remain for later indexing/regeneration. HDR10's representable10000nit ceiling and absent gamut/clipping scopes remain operator/qualification limits.

Managed PNG/composited/review monitoring applies an explicit SDR Hable transform from the same composition. Native all-PQ/scRGB remains opt-in and requires an actual active HDR output; it does not apply HDR10+ display metadata or provide calibration. Mixed source/technical transforms use reference monitoring. No GPU HDR export or NPU dependency is introduced. The first CPU float32 path is deliberately correctness-focused and slow; the UHD result is reported without a realtime claim.

Color state is included in existing project/undo/checkpoint objects. A new save-failure test reproduced live-view rollback disagreeing with the newer recovery draft; Apply Color now retains the unsaved edit and undo state consistently on publication failure. No checkpoint format,80-state history limit, frame/audio cache capacity, clock-response schema, PCM generation guard or original-source path protection is reduced. [Methods, precision, performance and deployment evidence](docs/HDR_COLOR_FOUNDATION.md).

QA flight recording is opt-in and absent from the shipping bundle: a fixed 256-row numeric ring, at most 16 events, five-second post-context, existing main-view audio acknowledgements and the existing native missed-event trace. View performance time, AudioContext time and native wall time have independent origins; asynchronously received tuples cannot timestamp execution exactly. Flight runs detach CDP and omit PDH. Heap allocation sampling runs separately, includes collected objects and never forces GC. Its indexed-meter correction reduces measured allocation churn; it does not establish ownership of browser private commit. Source/protocol fingerprints and binary hashes bind the scoped evidence in docs/ROOT_CAUSE_3_4_10.md.

## Real-world export and editing

The Windows Save dialog uses a codec-neutral MP4 filter. The local export API validates canonical paths and existing file identity, then atomically publishes complete output with a no-clobber mode. The UI asks for replacement consent. The independent video and PCM drains remain. PNG and JPEG are opened through image2 with a literal filename, decoded and resized once per segment, then held before animation and composition. Export progress consumes FFmpeg progress records rather than dividing the work by scene count.

The HDR10+ index streams FFprobe XML into a SQLite cache keyed to original file identity. A cancellable low-priority worker owns the decoder and publishes the index after success. Repeated metadata fields and original PTS survive parsing. A structural or distribution-conformance failure blocks frame reuse. The timeline mapper uses rational clip timing and holds. It does not drive HDR10+ output. The supported float32 HDR10 and legacy render paths remain separate.

The timeline guide and live trim labels update individual elements while the existing edit command validates and commits changes. Ruler seeks are coalesced in the animation frame and deduplicated by sequence frame. Sequence aspect presets change width and height through the ordinary project history, preserving clip framing properties. See [verification and remaining gates](docs/HDR10PLUS_EDITING.md).
