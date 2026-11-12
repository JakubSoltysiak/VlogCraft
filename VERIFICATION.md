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
