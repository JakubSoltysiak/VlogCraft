# VlogCraft Studio 3.4 development qualification

12 November 2026. Local Windows build **3.4.1**, delivered as release/VlogCraft-Studio-3.4-x64.msi. SHA-256 **33F010F973F8472272B80DCA984F64CF2930972CB15E27A619CFE8003A040F0F**. The installed application passed the native workflow. This remains a development build with an experimental buffered playback mode.

## GitHub integration and publication audit

The public repository is [JakubSoltysiak/VlogCraft](https://github.com/JakubSoltysiak/VlogCraft). Git Credential Manager and the connector both verified JakubSoltysiak before writes. Future commits use JakubSoltysiak and 255693@edu.p.lodz.pl.

main preserves the verified 3.3 history plus the publication audit at 3db1d2d85a9911cc1710b08368f9cea9acee3811. All four baseline tags were published with their original hashes. studio-3.3-verified remains ddb8b553da3223337691f6ac25cae95430cbbc93. A fresh mirror clone passed full Git fsck. The 3.4 work is on feature/studio-3.4-playback in [draft pull request 1](https://github.com/JakubSoltysiak/VlogCraft/pull/1).

The initial audit inspected all 11 commits and 154 distinct file-content versions, including archived images. There were no credential-pattern hits, tracked editing projects, personal footage, installers or dependency binaries. Ignore rules now cover local credentials, environments, projects and media. PUBLICATION_AUDIT.md and THIRD_PARTY.md document scope and provenance. No new project license was granted. Corresponding-source review for bundled dependencies remains a public binary-distribution task.

## Implemented and tested changes

- Exact 100, 120/1 and 120000/1001 sequence rates, including the 119.88 alias, use the existing rational frame/tick model.
- Constant-speed editing extends to 10% speed, supporting 20% 120→24 slow motion. Speed ramps and synthesized optical-flow interpolation remain missing.
- 8K UHD is available in the project and export presets.
- A continuous FFmpeg range graph composes the visible clips and mixed audio in one process over an eight-second window. Matching source/seek/speed inputs share decoding.
- The optional Composited preview monitor plays one combined audio/video stream, prepares the next range, reports progress and supports cancellation, obsolete-state invalidation and selectable preview resolutions.
- The new mode defaults to 540p. Live layers stays the initial interactive mode. Complete preview files have a twelve-file/512 MiB cache budget. Crash remnants and full cache-management tooling need more work.
- Decoded range/export comparisons cover clip appearance/disappearance, title fades, animated rotation, shared source inputs and delayed audio. A cache regression checks reuse, edit invalidation and cancellation.

**All 33 Python regression tests passed in 49.209 seconds, and all six JavaScript timeline tests passed.** Evidence is build/qa/regression34-shared.log and build/qa/node34-shared.log. The packaged render_engine, preview_cache, server and timing code were structurally compared to compiled current source and matched. build/qa/bundled-source34.json records those checks.

## Installed 4K60 editing and endurance measurements

The tested 4K60 sources are real decoded H.264/AAC moving test patterns. They are generated stress fixtures. The layered scene contains three video layers with animated transforms and three independent audio tracks. The endurance sequence has 1,500 clips across 600 seconds and was played for 70 seconds.

Both cases below use 720p source proxies and the 540p continuous-range compositor. The monitor presents the fully composed result through one video element. These are proxy-assisted, reduced-resolution figures.

| Installed scene | Measured s | Presented composite FPS | Dropped / decoded frames | Buffering s | Initial preparation s | Three seek latencies ms, range | Peak summed working set MiB | Peak process GPU memory MiB, dedicated / shared |
|---|---|---|---|---|---|---|---|---|
| 4k60-3video-3audio-proxy | 9 | 58.44 | 1 / 537 | 0.019 | 8.469 | 62–125 | 1051.0 | 3.34 / 368.86 |
| 4k60-1500clips-proxy | 70 | 59.54 | 8 / 4164 | 0.119 | 3.985 | 62–203 | 2023.4 | 3.56 / 292.96 |

The endurance playhead advanced 69.928 seconds during 70 seconds of measurement. Its UI animation rate was 60.00 callbacks/s and p95 video callback gap was 17.00 ms. The layered run averaged 4.63% of machine CPU, and endurance averaged 5.06%. Process I/O and GPU counter samples are in build/qa/composited34-installed/playback.json and build/qa/endurance34-installed/playback.json.

FPS counts presentation callbacks, while decoded frames and drops come from browser counters accumulated across player replacement. Audio meter activity was observed in both cases. The media clock owns this combined stream, so an independent HTML audio-element drift figure is inapplicable. Container A/V duration and delayed audio placement have decoded tests. Physical output latency, sample-locked range handoff and one-hour drift remain unqualified.

An earlier 720p buffered prototype waited until four seconds remained to prepare the next range. It paused at the boundary and averaged 47.6 callbacks/s. Preparation now starts earlier, the default render size is 540p, and matching inputs share decoding. The source prototype then reached 59.8 composite FPS with one drop and no measured buffering over nine seconds. Installed results above qualify the delivered build. Initial preparation remains several seconds.

The 3.3 native-layer benchmarks are retained below. Native-resolution original-media multitrack performance has not been newly qualified as real time. The new figures establish buffered presentation and parity for this fixture, with explicit preparation cost. They do not guarantee real-time performance for arbitrary masks, LUTs, layers or codecs.

## 4K120 support

The test creates a real 3840×2160 H.264/AAC source at 120000/1001. Import metadata is checked. Native-resolution output is then encoded at 120000/1001 and 120/1, with slower playback into 60, 30 and 24 fps timelines. Every output is decoded, and frame counts and rate metadata are verified. Rational project serialization/reopen and sample arithmetic are checked at 100, 120 and 119.88.

The source is approximately 0.1001 seconds. This proves the tested short import/edit/export path and constant slow motion. Long 4K120 footage, native real-time 120 fps presentation, variable-speed ramps, interpolation, and every hardware/codec combination remain unqualified.

## 8K60 support

The test creates a real 7680×4320 H.264 source at 60000/1001, verifies native import dimensions, trims the middle four frames and exports them at the original resolution and rational rate. It decodes the result, checks frame count/dimensions/rate and compares the first delivered picture against its selected original.

This is a six-frame source and four-frame delivery. Longer 8K60 tests, a 60/1 native-resolution acceptance case, HEVC/AV1 and 10-bit combinations, camera footage, storage stress and hardware encode limits remain open. A selected resolution in the interface is not counted as qualification.

## GPU acceleration and architecture selection

A local D3D11VA prototype decoded 360 original 4K60 H.264 frames and explicitly downloaded GPU surfaces to NV12 for the CPU path. It completed successfully. The software comparison took 0.969 seconds wall time, versus 1.843 seconds for D3D11VA plus download. FFmpeg reported 0.906/1.230 seconds internal runtime and about 154/474 MiB peak RSS respectively. D3D11VA used less CPU time. This single short fixture favored software for the current CPU-composited pipeline, so automatic hardware decoding has not been enabled.

Actual GPU encoding through AMD AMF is preserved, with software fallback on failure. The 3.3 six-encoder matrix is retained below. GPU composition and a native zero-copy decoder/render path remain missing. NVIDIA and Intel driver qualification remains open.

PDH now records dedicated/shared GPU process-memory counters. Those sums can count shared allocations across processes. The integrated Radeon uses shared system memory, so these figures are not a complete physical VRAM inventory. Video/3D utilization counters still report near zero in cases where AMF/D3D11VA completed. Their occupancy interpretation remains unqualified. Raw decode diagnostics are in ignored build/qa/decode34.json.

MLT's service architecture was reviewed as a candidate. The measured prototype reuses the existing FFmpeg effect and audio evaluator to preserve reference/export behavior. MLT was not integrated or performance-qualified.

## Windows installer, large files and recovery

The 3.3→3.4.0 upgrade passed, followed by 3.4.0→3.4.1. The final installer upgrade, uninstall and reinstall each returned zero. Shortcuts were removed and restored correctly, and the controlled project-retention sentinel survived. That profile had no pre-existing user project/settings documents in the scanned directory. A populated long-lived profile still needs qualification.

The final installed app passed the complete native workflow with two independently allocated 4,977,125,566-byte MOVs exposed through native paths. It linked originals without populating its media-copy folder, sought beyond 4 GiB, split/trimmed/moved and exercised undo/redo. Its delivery contains 24 frames at 3840×2160/60 with 0.400000-second audio/video. First-frame RGB error against the selected original was 0.891 levels at 96×54.

That workflow also passed original-frame stepping, proxy cancellation/retry, source monitor, grading/reference/scopes, linked audio, nesting/expand/undo, selected-frame multitrack review, motion apply/undo, AI approval/undo/redo, project reload and the single-stream composited monitor. Browser errors were empty and the host exited normally. build/qa/lifecycle34-final/lifecycle.json and build/qa/installed34-final/windows-workflow.json retain the results.

Recovery and previous-format compatibility passed the complete existing regressions. Native high-DPI changes remain unqualified. The earlier WebView2 DPI-emulation attempt timed out. No manual user test is being counted as acceptance.

## GitHub CI/CD

Windows Actions checks all reachable history for credential patterns and forbidden generated files, dependency compatibility, Python/JavaScript syntax, Python regressions, JavaScript commands, application packaging and MSI lifecycle. Official action revisions are pinned and the FFmpeg archive checksum is verified.

The initial hosted run found two assertions that compared an 8.3 temporary path with its canonical Windows spelling. Those assertions now compare resolved paths. Subsequent hosted Windows regression and packaging passed, including the [compositor CI run](https://github.com/JakubSoltysiak/VlogCraft/actions/runs/43294828178). Final branch checks may run again after report commits. Their live status is shown on pull request 1.

CI does not publish a stable GitHub release or bundled installer artifact. Exact dependency source/redistribution material still needs review for public binaries. The local development installer remains available.

## Known limitations and next priorities

The buffered mode has startup/cache-miss latency and range handoff overhead. It is an experimental transport, and live-layer preview remains available. Full continuous native/MSE playback, sample-locked audio, hour-long endurance, high-DPI changes, camera acceptance media, GPU composition and broad HFR/8K qualification remain production blockers.

Offline review/proposals remain multitrack-aware and consent-bound. The optional online AI connector retains its existing legacy scope. No paid call was required and no footage was sent to an external service. Public GitHub publication includes source and reviewed demonstration images.

The next work is to remove range handoff gaps with an uninterrupted transport, reduce first-play preparation, qualify longer HFR/8K camera material and mixed codecs, and add a measured zero-copy GPU path. Professional masks, managed HDR, corrective tracking, audio mastering, multicam and interchange gaps remain listed in FEATURES.md.

---

# VlogCraft Studio 3.3 release qualification

12 November 2026. Private Windows development release. The qualified MSI is release/VlogCraft-Studio-3.3-x64.msi, 206,409,324 bytes. SHA-256 is **566D077D2FFD2972B59DCA6B03D77C3A845E35C4F844FE2333FFBA15A93D0AA2**. Version 3.3 remains installed with Start menu and desktop shortcuts.

Qualification used Windows 11 Pro build 26300, AMD Ryzen AI 9 HX 370, Radeon 890M, Python 3.11.9, FFmpeg 9.0.2 and WebView2. This is one live workstation. Core tests used local generated media. Production readiness remains open because full-quality layered playback, long-session synchronization, camera-media diversity, managed color and broader Windows qualification remain incomplete.

## 1. Implemented features

The current 3.2 source was preserved in commit 9c37e27 and tag studio-3.2-source. The 3.3 implementation is preserved in commit 4fc1ea4. The existing 3.1 rollback tag and installers remain available.

3.3 adds bounded video-element reuse and upcoming-cut preparation, streamed stereo FLAC preview audio, proxy-queue cancellation and retry, software retry after a hardware encoder failure, permanent prior-format project backups, selected-program-frame review exports, ordinary undo/redo for approved AI edits and expanded release automation. Existing rational/VFR editing, linking, nesting, curves, wheels, LUTs, masks, chroma, wipes, keyframes, tracking and stabilization remain available.

The FFmpeg complex graph uses one worker after a reproducible mixed-audio/title graph stalled with four workers. CPU composition and a separate encoder remain the rendering architecture.

## 2. Independently tested behavior

| Area | Verification |
|---|---|
| Rational timing | Reordered one-frame joins at 24000/1001, 30000/1001 and 60000/1001, decoded frame identifiers, output frame count/rate/duration and audio timing. An 18-hour clock calculation checks integer frame/sample arithmetic. |
| VFR | Original presentation-time index, stepping, exclusive out mark and a cut inside a held source frame. |
| Timeline | Six JavaScript tests cover roll/slip/slide, insert/overwrite tails, linked movement/split/delete, atomic lock/handle rejection, link/unlink and nest/move/expand. |
| Picture | Decoded animated geometry/alpha, feathered mask and chroma, four wipe directions, title/audio layers, LUT color-channel mapping, curves/wheels and reference/export comparisons. |
| Motion | Encoded-original point displacement and stabilization jitter reduction, plus known camera roll and corrective smoothing. |
| Audio | Decoded pan, measured normalization, dialogue-energy ducking, and sample-equivalent FLAC caching for the 16-bit fixture. |
| Recovery | Atomic publication, injected disk-full behavior, validation of previous revisions, actual child-process death before replacement and retained prior-format backup. |
| AI | Nested manifest/proposals, parent locks, exact-state approval tokens, stale approval rejection, undo, installed-app redo and selected composited frame ZIP. |
| Windows workflow | Actual installed application, native drop payload, source-frame stepping, grading/reference/scope, linked audio, nesting/expand/undo, motion apply/undo, proposals, reopen and normal host exit. |

## 3. Regression results and diagnosed failures

**28 Python tests passed in 36.651 seconds. Six JavaScript tests passed with zero failures.** Logs are build/qa/regression33-fixed.log and build/qa/node33-fixed.log.

The first complete run stalled in the FFmpeg mixed-video/title/two-audio graph. A diagnostic reproduction also timed out. The stalled child was terminated, and that run is recorded as failed in build/qa/regression33.log. Using one complex-filter worker resolved the reproduced graph. The fixed complete suite passed. The affected regression now imposes a 20-second subprocess deadline.

A benchmark counter initially followed the first video element across an edit and missed replacement/reused elements. The counter now attaches to each active player, retires it on removal and uses subscription tokens when reusing it. The installed results below use the corrected counter. Earlier source callback figures are unsuitable for a direct video-FPS comparison.

A startup race in the benchmark harness was fixed by waiting for the native page to navigate after attaching CDP. An audio fixture initially used a duration spelling rejected by FFmpeg and was corrected to 0.4. Its sample-equality test passed.

The WebView2 device-pixel-ratio emulation check timed out. Actual high-DPI qualification remains open. The native workflow passed at the machine's current scaling and at 1024- and 1440-pixel viewport widths. Three recorded control-image comparisons had zero mean RGB difference.

PyInstaller reported missing optional pycparser lextab/yacctab modules. The packaged application launched and passed the installed editing workflow.

## 4. Playback, encoding and large-file measurements

The playback corpus contains decoded H.264/AAC moving test-pattern clips at 1080p60, 4K30 and 4K60. Each source lasts 12 seconds. Layered cases use three video and three audio tracks with animated rotation/translation. The stabilization case uses actual analysis-generated correction keys. The long sequence contains 1,500 clips spanning 600 seconds and was played for 70 seconds. These fixtures exercise real decoding and composition. Camera footage and an uninterrupted full-length film remain outside this corpus.

| Installed scenario | Measured s | Mean presented FPS per video layer | Dropped / decoded frames | Three seeks ms, range | Peak summed working set MiB | Mean machine CPU |
|---|---|---|---|---|---|---|
| 1080p60 | 7 | 58.43 | 0 / 418 | 94–172 | 1067.4 | 3.67% |
| 4k30 | 7 | 27.86 | 0 / 211 | 140–641 | 1420.4 | 4.04% |
| 4k60 | 7 | 49.57 | 71 / 420 | 390–594 | 1742.2 | 4.53% |
| 4k60-3video-3audio-effects | 9 | 3.41 | 35 / 137 | 828–1703 | 2706.0 | 4.13% |
| 1080p60-stabilized | 7 | 50.57 | 67 / 420 | 109–157 | 2287.6 | 4.14% |
| 10minute-1500clips | 70 | 57.57 | 29 / 4203 | 141–156 | 2257.4 | 4.67% |
| 4k60-3video-3audio-proxy | 9 | 56.00 | 103 / 1615 | 15–62 | 1017.3 | 3.73% |

Raw records are build/qa/playback-installed33/playback.json and build/qa/playback-proxy33/playback.json. Multiple-layer frame totals sum all layers. FPS is based on browser presentation callbacks. CPU is process-tree CPU time divided by elapsed time and logical CPU count. Memory sums working sets and can count shared pages more than once. Process I/O counters describe logical I/O.

The 70-second rapid-cut run maintained about 60 UI animation callbacks/s. Its media-clock drift p95 was 34.8 ms. The layered original-media run had video/audio clock drift p95 of 31.8/30.1 ms, while the proxy run had 29.9/31.4 ms. These measure browser clocks against the transport. Acoustic latency and hour-long A/V drift remain unmeasured.

Original 4K60 and original layered playback missed their nominal rates. Automatic proxies reduced layered working set from 2706.0 to 1017.3 MiB and substantially improved presentation and seeking. Exports read originals.

A complete three-second 3840×2160/60 export at a 35 Mb/s target produced and decoded 180 video frames on both backends.

| Encoder | Export s | Encoded FPS | Sampled process-tree CPU s | Peak summed working set MiB |
|---|---|---|---|---|
| libx264 | 6.797 | 26.48 | 22.69 | 1666.2 |
| h264_amf | 6.672 | 26.98 | 11.00 | 958.0 |

The final render settings produced similar end-to-end throughput on CPU and AMF. AMF used less CPU time and working set. Earlier measurements with four filter workers showed a larger AMF speed advantage, and those settings encountered the scheduling stall. The final software graph limits end-to-end acceleration. Logs and JSON are in build/qa/encode33-qualified.

H.264, HEVC and AV1 exports passed decoding with CPU and AMD AMF encoders at 640×360/60. build/qa/encoders33-final.log records all six successful paths. Hardware-device failure and automatic software retry passed an injected regression. NVIDIA and Intel hardware were unavailable for qualification.

Windows PDH sampled process-tree GPU engine counters. The driver reported near-zero video/3D utilization, including during successful AMF encoding, with some Copy activity. Those values are preserved in the JSON but cannot establish reliable GPU occupancy. Encoder selection and valid output are verified. Composition, effects and this renderer's decoding remain CPU-based.

### Large-file installed workflow

Two independently allocated MOVs each contain **4,977,125,566 bytes** with different generated picture and audio content. The batch native drop exposes both through distinct NTFS paths, including a hard-link alias of the first fixture. The editor links them and leaves its media-copy directory empty. Cache/proxy files are expected local derivatives. Physical Explorer mouse gestures and a complete multi-GB browser copy remain unqualified.

The first exported source packet begins at **4,578,951,204**, beyond 4 GiB. The installed test seeks, splits, trims, moves, undoes/redoes and renders **24 frames at 3840×2160, 60/1**, with both video and audio lasting **0.400000 s**. At 96×54 the first output frame's RGB mean absolute error against the selected original is **0.891** levels.

That run measured 0.562 s from native drop to timeline insertion, 3.640 s through proxy readiness, 0.860 s for the selected seek and 1.922 s for delivery. Whole-workflow peak summed working set was 2065.7 MiB. The additional large-file batch peaked at 1814.6 MiB. These short tests establish measured memory behavior for this corpus. They do not prove a constant-memory bound for arbitrary track counts.

The installed workflow also passed proxy cancellation, queue clearing and retry, source stepping, selected-frame multitrack review, curve/reference/scopes, linked audio/nesting/expand/undo, motion apply/undo, AI approval/undo/redo and project reopen. Browser errors were empty and the native host exited with code 0. Evidence is build/qa/installed33-independent/windows-workflow.json.

## 5. Windows installer validation

3.1 → 3.2 upgrade passed with MSI exit 0 and explicit removal of version 3.1 recorded in build/qa/upgrade32.log. The installed 3.2 workflow passed before continuing.

3.2 → 3.3 upgrade, 3.3 uninstall and 3.3 reinstall each returned **0**. Uninstall removed the executable and shortcuts. Reinstall restored Start menu and desktop shortcuts targeting the installed executable. Project/settings inventory hashes survived each operation. This profile contained a controlled retention sentinel and no pre-existing user project/settings documents in the scanned directory. The test establishes retention for that sentinel and installer layout. A populated long-lived profile still needs qualification.

Evidence is build/qa/lifecycle33/lifecycle.json with upgrade/uninstall/reinstall MSI logs. The final installed copy passed the editing workflow and playback benchmarks.

## 6. Known limitations and production blockers

- Original-media layered 4K60 playback is slow and variable. Automatic proxies help substantially. A continuous native decoder/compositor and sample-locked transport remain priority architectural work.
- Seventy seconds of a ten-minute rapid-cut sequence is qualified. One-hour uninterrupted synchronization, full-film stress export and long-session memory growth remain unmeasured.
- The optional online AI connector retains legacy main-track analysis as requested. Offline review/proposals cover all tracks and nests. Full multitrack online analysis and paid/live endpoint behavior remain unqualified.
- No camera acceptance corpus, clean Windows image, second GPU vendor, native high-DPI change, code signing or calibrated external monitor was available in this run.
- Live CSS/WebAudio and the reference compositor differ. HDR mastering, calibrated scopes, arbitrary masks, advanced tracking, LUFS/mastering and professional interchange remain incomplete.
- Background audio/proxy caches need disk budgets and eviction. Current-file probing, persistent general edit history, restartable analyses and a full recovery journal need further development.
- The serial complex graph trades parallel filter throughput for a verified resolution to the reproduced stall. Other long/complex FFmpeg scheduling cases require stress coverage.

## 7. Remaining Premiere-class differences

FEATURES.md records the detailed matrix. Major gaps include multicam, reusable sequence references and sequence tabs, global ripple policies, markers and custom shortcuts, arbitrary animated masks, managed SDR/HDR, calibrated secondary grading, corrective planar tracking, sample-accurate audio buses, AAF/OTIO/XML, professional intermediate codecs, batch/range delivery and dockable workspaces.

## 8. Next development priorities

1. Prototype a continuous native transport behind the current rational project and transactional command model. Compare VFR cuts, reference effects, color, audio and proxies against the existing exporter.
2. Add independent camera fixtures, one-hour sync and full-length renders, clean Windows/driver tests and real high-DPI qualification.
3. Add cache budgets/eviction, cancellable probing, durable analysis recovery and persistent edit history.
4. Extend the optional online connector to the multitrack contract when requested, while retaining selected material, explicit consent and exact-state approval.
5. Build professional color/HDR, masks, audio mastering and interchange on the verified shared transport.

No paid endpoint was invoked and no media was sent to an external service during qualification. Generated test media and binaries remain local under build, dist and release.

---

# Windows verification

## 3.1 baseline, 12 November 2026

The 3.1 x64 MSI installed on Windows 11 Pro build 26300 with an AMD Ryzen AI 9 HX 370 and Radeon 890M. The Start menu and optional desktop shortcut targeted the installed executable. An earlier private build was uninstalled and its executable and shortcut disappeared. The final 3.1 MSI SHA-256 was C195327F9344DFF74A2AE7324B13BE8003D5C7430887C2B702678686DE00F880.

The 11-test offline regression suite passed in 26.044 seconds. It covered NTFS sparse ranges and chunk offsets, HTTP ingestion, multitrack audio/video/title export, HEVC MOV, monochrome grading, silence on a muted track, approval/undo, missing media and relinking, crash-style recovery, injected disk-full failure, optical-flow tracking, decoded stabilization and 104 tracks with 1,500 clips.

The installed desktop test supplied a native WebView2 drop payload for a fully allocated 4,977,125,566-byte synthetic MOV. It linked the original without copying it, sought to 4.6 seconds in a proxy, split the timeline, exercised undo/redo and exported from packet offset 4,578,951,204. The H.264 export contained 24 frames at 3840×2160, 60/1, and 0.400 seconds of AAC. The first decoded frame differed from the corresponding source frame by a mean 0.891 RGB levels at 96×54. The installed app also applied/undid motion and a multitrack approval, reloaded the project and closed normally.

A single installed run measured 1.047 s from drop to clip insertion, 4.344 s through proxy readiness, 0.781 s for a seek check including automation polling and 1.719 s for the 24-frame export. The process tree's peak summed working set was 2,075.5 MiB, sampled CPU time 21.48 s and process I/O 5,045.9 MiB read / 12.2 MiB written. These are whole-workflow measurements on a short synthetic source. GPU utilization, physical disk I/O and sustained real-time playback were unmeasured. Three control-image comparisons matched the reference, with the inspector visible at two viewport widths.

The encoder smoke matrix exported and decoded H.264, HEVC and AV1 on both CPU and AMD AMF at 640×360/60. NVENC and Quick Sync could not be qualified on this hardware. No paid endpoint was invoked and no camera footage was supplied.
