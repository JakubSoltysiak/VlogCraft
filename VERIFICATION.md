# VlogCraft Studio 3.4 development qualification

The approved icon asset checkpoint passed installed EXE/MSI/shortcut/window/taskbar/favicon/web and retained-data lifecycle checks. The unmodified source and exact seven-size results are documented separately in [ICON_UPDATE.md](docs/ICON_UPDATE.md). Performance results below still describe the 3.4.7 engine; 3.4.8 engine work is not yet qualified.

## 3.4.7 workstation refinement — 13 November 2026

Continues PR #3 / 48f4d4e on feature/studio-3.4.7-workstation; canonical main requirements VC-P0-024–031 are preserved. PRs #1–#3 remain unmerged drafts. [Workstation report](docs/WORKSTATION_OPTIMIZATION_3_4_7.md), [curated measurements](docs/benchmarks/2026-11-13-native347) and [source-bound performance record](docs/benchmarks/studio-3.4.7-performance.json) state exact scopes. **Native remains experimental.**

The first 3.4.7 hosted CI run failed before loading the diagnostics tests because psutil was present locally but missing from packaging/requirements.txt. The dependency is now explicitly pinned to the locally qualified 7.2.2 version. The failed run remains visible. A clean requirements install, pip check and all four diagnostics tests passed in a new isolated environment; the updated commit is then requalified by exact-head Windows CI. This changes dependency declaration, not the qualified application/native source or installer contents.

**Environment:** locally verified ASUS Zenbook S16 UM5606WA, Ryzen AI 9 HX 370 (12 cores/24 logical), Radeon 890M driver 32.0.32015.7029,32 GiB firmware memory configured 7500 MT/s, MTFDKBA1T0QFM-1BD1AABGB NVMe SSD. Initial battery/60 Hz runs were separated; the owner connected AC and Windows automatically exposed nominal 120 Hz/10-bit HDR. No desktop/HDR/power-plan settings were changed. Public thermal sensors and reliable PDH GPU occupancy were unavailable; zero video/3D counter values do not mean no GPU work.

**Matched 125-second /1,500-clip results:** three independent original 3840×2160 H.264 sources plus three audio tracks, 960×540 composition, 356×200 surface, no proxies/encoded intermediate video. Baseline Present rates 57.829/56.768/57.715 FPS; candidate raw **and distinct** rates 59.796/59.666/57.832 FPS. Median **57.715→59.666** (+3.38%); median skips **279→28** (89.96% reduction). Candidate skips 12/28/262 retain the poor trial. Each ended with exactly 6,000,000 stereo sample frames and zero underruns. Native first-ready medians .998→.934 s; frozen process-ready medians 2.153→2.278 s, caches unmanaged. Installed functional first-native-ready had a 1.65 s cold outlier; startup is not guaranteed below 1 s.

**FULL endurance:**600 seconds /7,200 clips, three original 4K sources and three audio tracks at 540p completed with **28,800,000 sample frames, zero underruns, 59.872 distinct FPS, 62 skipped sequence frames**. Three skips followed source waits; none followed GPU-slot starvation. P95 CPU Present interval18.1 ms. Remaining clock/driver/presentation/host scheduling tails are not physical-scanout causality proof. The benchmark's wall window includes up to one250 ms end-observation poll. GPU completion, Present calls, DXGI counts, distinct sequence submissions, source holds and clock-rewind holds are separate; generated frames are zero.

**Resource tradeoff:** matched median peak summed working set **2496.5→3437.3 MiB**; matched machine CPU medians **9.02→8.91%**, within variation. Historical lower CPU numbers used different power/display conditions. Ten-minute summed working set rose3256→3616 MiB, peak3703 MiB. Source queues≤4, completion slots≤6 and prefix cache≤6 original frames/source remained bounded. This is not proof of general heap/leak stability. GPU shared-memory peak medians~2018→2283 MiB can overlap UMA/process mappings; PDH occupancy was unreliable. No energy/thermal efficiency claim.

**Scheduling investigations:** measured Sleep(1) p50/p95=15.803/16.000 ms. An owned interruptible high-resolution deadline wait reduced p95 wake overshoot to~.7 ms. One/two-frame DXGI admission experiments reduced completion age but worsened short throughput (~55.1/~54.8 FPS) and were rejected. Ring expansion removed GPU-slot starvation; a bounded original-frame prefix cache removed recurring-cut source starvation. Cached selection requires actual adjacent PTS, retains HDR side data and includes its pool allowance. A native black-box proof matched all three sources at sequence0/90/91/93 to exact decoded source PTS;15 additional private cached/VFR cut checks matched.

**Quality/display:** all five540p/720p/1080p/1440p/2160p30-second cases reached their ends with exact1,440,000 samples and zero underruns. The short4K small-surface case had zero sequence skips; it is not long native-size qualification. Corrected175% /168 DPI geometry used a2880×1676 native client and **2545×1432** presentation surface:3840×2160 composition, 30 seconds, 59.393 distinct FPS, 3 skips, zero underruns. An earlier high-DPI benchmark overlay was resized by normal layout and became portrait; it was rejected and the harness gained a strict aspect check. No renderer picture tolerance was relaxed. Manual dimensions/source mode are explicit; seamless adaptive resolution/upscaling was not adopted because the measured matrix did not establish a resolution bottleneck.

**Timing and exports:** strict same-UI/native-runtime ABBA seek controls (2 runs×12 destinations/arm) have median-of-trial p50 **494.7→522.9 ms**, p95 **697.5→671.3 ms**; overlapping ranges do not establish a speedup or reproducible>10% regression. Initial export medians 6.035→7.673 s triggered investigation. The reference renderer is byte-identical to3.4.6; alternating executions of the same compiler ranged 6.860–8.907 s (arm medians 7.451/7.004 s). This is condition variation, not an implementation improvement. Export remains unoptimized. All six CPU/AMD AMF H.264/HEVC/AV1 smoke exports fully decoded.

**Real originals:** owner identifies A/B as Galaxy S25 Ultra and C as a Google Earth animation; device model/Log are not independently embedded-metadata verified. Nine bounded direct PTS seeks and15cache/cut checks passed; Main10/PQ high-precision and decode-side HDR10+ retention remain. All complete recordings played on native runtime fe2f6ee1…:81.683/49.267/18.017 s, **3,920,800/2,364,800/864,800 samples**, zero underruns. C has no audio, so its clock uses generated silence. Calibrated HDR/dynamic metadata and acoustic sync remain unqualified. All three before/after SHA256/mtime comparisons match; original folder exactly 3 files, zero generated additions. No footage, images, original names/hashes/paths/GPS/private metadata are published.

**Automated regression:**61 Python tests passed offline socket/DNS guard in 24.694 s;11 JavaScript tests passed114.466 ms; historical drain **20/20 decoded, zero timeouts**. Major scheduler/cache changes repeatedly passed QUICK Python/JS/precision checks. P010/PQ retains 877levels, PQ max 125scRGB, normalized error.0001831; layered rotation/key/reference first-frame RGB MAE.008322 unchanged. Tests cover recovery/compatibility/undo, linked/nested edits, offline AI approval, source PTS, source offsets, hardware/software export fallback, owned cancellation and reference fallback. New diagnostics close test terminates/reaps a real child process; profile/source whitelisting and strict performance-contract rejection also pass.

**Windows final package:**3.4.7 MSI SHA256 **F22E8907CBA6FDE11174315E3070C763D08177ADB4E585A8AF8D338A6D54B4F9**. Upgrade/uninstall/reinstall each returned0 with retained project/settings bytes and shortcut removal/restoration. The earlier same-version pilot was removed and the preserved qualified3.4.6 installation restored before rebuilding, avoiding ambiguous same-version product replacement. Final23 Python modules, web files, installed executable, native runtime/probes and hash manifest match. Owned renderer termination→full SDR fallback→retry, unsupported effect fallback, resizing/modal visibility, manual1440p, original-source labeling and reversible diagnostic preview suggestions passed in the final installed build.

Final installed large-source workflow passed **two independent5,972,550,422-byte originals**, linked native drop, source packet offset4,578,951,204, proxy cancel/retry, source review, grade/scopes, linked/nested undo, motion apply/undo, explicit offline AI approval/redo, reopen and normal close. Output fully decoded84 frames at 3840×2160/60 plus matching1.4 s audio;RGB MAE.052, no browser errors. One selected seek .641 s/export5.235 s; this is not a matched throughput claim. Installed external browser fetch was blocked; frozen Python guard remains false and no OS-firewall/physical-disconnect claim is made.

**Rejected interpolation:** isolated CPU640×36030→60 MCI generated116decoded frames in 5.213 s (~22.25 FPS), versus120repeated frames in.190 s. Lookahead truncated the end; perceptual/wildlife/artifact/energy acceptance was not run. No model/runtime or GPU/NPU acceleration was qualified, and no interpolation was added to preview/inspection/export.

**Remaining blockers:** sustained zero-skip60 across workloads, more native-source/mixed-color cases, longer process-memory analysis, physical scanout/acoustic sync, actual GPU removal/reset, display/HDR/power transitions, multi-monitor/multi-vendor/DPI/accessibility, full native effects/working-color parity, HDR10+ mastering, HLG/Log, native GPU export, multichannel, clean-machine deployment/signing and corresponding-source/license review. Existing default and full FFmpeg renderer remain. No stable release or dependency binary publication.

## 3.4.6 experimental native integration — 13 November 2026

Continues the verified 3.4.5 tip without merging PR #1 or PR #2. [Implementation, capability/fallback matrix, privacy, baseline and blockers](docs/NATIVE_PLAYBACK_3_4_6.md) and canonical TODO.md are current; all older results below retain their historical scope.

**Source regression:** 51 Python tests passed in **29.870 s** with the opt-in external socket/DNS guard active; **11 JavaScript tests** passed in **147.483 ms**. Historical render-drain reproduction decoded **20/20**, zero timeouts. Pip dependency check, 80 Python source compilations, web JavaScript syntax and diff checks passed. Earlier substantial-change runs passed 50 Python/10 JS before the final generation regression was added.

**Native Windows source:** initial ready **.687 s**, paused seeks **.2156–.4344 s**. Rational 60000/1001, three original4K sources plus three audio tracks, animated rotation, pause/resume, repeated/coalesced same-frame seeks, seek while playing, complete sequence end, resize, modal hide/show, owned-child kill→full SDR fallback→retry, and unsupported mask→full reference fallback all passed without browser errors. Post-final-seek audio was exactly 86,486 samples, zero underruns; final video reached sequence frame 239 in the correct generation. This is functional transport coverage, not an FPS benchmark or physical GPU-removal test.

**Sustained native:** 125 seconds / **1,500 clips**, .5-second cuts, three original 3840×2160 H.264 sources and three audio tracks, **960×540 composition**, no proxies and no intermediate encoded program video. Reached its end in **125.089 s**, **6,000,000 samples**, **zero underruns**. Composited **57.184 FPS**, Present calls **57.200/s**, DXGI present-count delta **57.160/s**; **345 skipped sequence frames**. Native child display size was 356×200 physical pixels in this fixture. First ready .988 s; summed process peak working set **2,060 MiB**; first/last 5-second history samples 1,994/1,949 MiB; average machine CPU 6.65%. Queues stayed at four/source, GPU ring three, active decoders three. Shared GPU-memory counters measure process residency, not a discrete VRAM allocation guarantee. This two-minute test is not a leak proof, physical scanout/tearing measurement, native4K output or sustained 60 FPS success.

That sustained run used the post-chroma-fix build; a later same-frame generation guard corrected a seek-only case and was functionally retested in the final runtime. Failed earlier trials remain local: a 60-second pilot stalled at 2.048 seconds because a coalesced PCM network read exceeded queue capacity; an eight-second reset-at-every-cut version presented ~36.4 FPS; the first 125-second window closed before completion and supplied no complete result. None is reported as a pass.

**Picture precision:** final sampler retains **877** luma levels from lossless 10-bit HEVC (normalized MAE **.0001618**). A tagged PQ ramp retains 877 levels, maximum linear scRGB **125.0**, mean error normalized by 1+reference **.0001831**. A layered transform/keyframe/reference first-frame comparison has RGB MAE **.0083224**, p95 **.0127355**. This verifies the scoped generated composition and PQ formula; full effect/color calibration remains unqualified. The test found and fixed visible-plane edge clamping rather than relaxing its tolerance.

**Private camera scope:** three originals were ignored before tests, kept read-only and never included in Git. FFprobe stream/side-data facts, unknown device/lens/exposure fields, orientation and color policy are documented using aliases in the integration report. Final-runtime 180-frame offscreen runs took **1.182 / 1.133 / 1.087 s** for A/B/C; all completed and all **nine bounded source-PTS seeks matched**. A/B preserved HDR10+ side data at decode and float maxima **17.953 / 14.352**, not authored metadata. Corrected float CPU-reference RGB MAE **.003499 / .009812 / .001829**. Full-file PTS scanning of A exceeded 180 s; bounded six-second tables were used instead, with that limitation retained.

On-screen A/B PQ tests correctly rejected inactive Windows HDR rather than silently converting to SDR. CameraC's three-second native GUI test completed at .722 s initial ready / 144,000 silence-clock samples; old installed 3.4.5 took 5.547 s in the corresponding explicit-SDR 540p case. CameraC has no audio. A separate ten-second native test mixed actual A/B stereo camera audio with C video across the PCM chunk boundary: **480,000 samples, zero underruns, no browser errors**, .663 s initial ready in the source run. This is digital clock/sample qualification, not an acoustic/lip-sync measurement.

**Windows package:** optional native runtime was built into a local **3.4.6** MSI, SHA256 **FC461B4AC17A086308DFA500AA6E91543D421C7A8994537E99A03956CE2C895E**. The verified 3.4.5 MSI was preserved under a version-specific local filename. New MSI upgrade/uninstall/reinstall each returned **0**; executable/shortcuts and one retained project/settings document passed removal/restoration/byte-preservation checks. An earlier lifecycle invocation happened before the builder finished and therefore checked the old 3.4.5 MSI; it is excluded from 3.4.6 evidence. No public binary release is created.

**Installed final-runtime checks:** all 22 Python entry/engine modules structurally matched source; every web file and installed executable/native runtime matched the bundle/hash manifest. Installed rational transport/rapid seeks/process fallback passed with 86,486 post-seek samples and no underruns. The final-runtime 60-second three-original4K/three-audio run reached its end: **2,880,000 samples, zero underruns**, composited/Present **57.137 FPS**, DXGI **57.153/s**, **161 skipped frames**, 1.481 s first ready and 1,903.9 MiB peak summed working set. No proxies/intermediate encoded video; 540p composition and 356×200 child display, not 4K output.

Installed original-media regression passed two independent **5,972,550,422-byte (>5 GiB)** sources: native path drop/linking with no copies, source packet offset **4,578,951,204**, proxy cancellation/retry, source step/review, grade/scopes, linked audio/nest/expand/undo, motion apply/undo, explicit offline AI approval/redo/reload and normal exit. Export fully decoded **84 frames at 3840×2160 / 60/1**, **1.4 s** video/audio; RGB MAE **.052**, no browser errors. Selected seek .609 s, export 3.969 s in this fixture. Control UI captures matched at DPR1/sRGB. The installed actual-camera audio mix also passed ten seconds / 480,000 samples / zero underruns.

**Final private-media gate:** all three SHA256 hashes and mtimes matched their before-test values; exactly three files remained in the original folder with no generated additions. No private folder files were tracked, staged or found in reachable history, no original-content blob matched, and no original names/paths/hashes/private creation/GPS/serial tags matched history or publishable working text. Only sanitized numerical/alias reports are committed. The earlier filtered-error incident is explicitly described in the integration report. Python source offline tests block external sockets/DNS; installed browser tests block external requests and an external fetch failed. The frozen installed Python guard is false; no physical disconnect or OS-firewall qualification is claimed.

**Production blockers:** sustained 60 FPS, full native effect parity, long real-camera and acoustic synchronization, actual GPU reset/recreation, calibrated HDR display, HLG/Log/mixed working spaces, HDR10+ mastering, native GPU export, multichannel routing, multiple GPU/Windows/display configurations, code signing and dependency corresponding-source/license review. Existing original-media FFmpeg export/fallback and offline editing remain; native stays opt-in.

## 3.4.5 architecture investigation — 13 November 2026

Development only. This work branches from the existing 3.4.4 development tip and preserves PR #1 and all previous tags. The [audit](docs/ARCHITECTURE_AUDIT.md), [engine benchmarks](docs/ENGINE_BENCHMARKS.md), [decision](docs/ARCHITECTURE_DECISION.md), [roadmap](docs/PERFORMANCE_ROADMAP.md) and [curated generated-fixture JSON](docs/benchmarks/2026-11-13) are the current report. Sections below this checkpoint retain historical 3.4.4/3.3/3.1 results.

The final local Python regression passed **41 tests in 33.378 s** with the opt-in Python socket/DNS guard active and external connections blocked; **six JavaScript tests** passed in 72.345 ms. Additional prior full runs passed after each substantial production change (opaque fastpath: 34 Python; cache: 39; shutdown: 40, followed by the launch-race test and final 41). Cache tests include restart, output corruption, source/proxy mutation, nested/solo dependencies, budget eviction and protection of linked originals. Two index lifecycle tests cover actual child termination and cancellation before launch.

Local **3.4.5** MSI built successfully. SHA-256 **E2EC33BA5649CE2E43F95092EFE2D370F8EB7C4E81DAC9231EE78B6FB810A189**. Upgrade from 3.4.4, uninstall and reinstall returned **0**; executable/shortcut removal/restoration and byte-identical project/settings retention passed (one controlled retained document in this profile). No public binary release is created. The former 3.4.4 MSI is retained locally under a version-specific filename.

Final large-file extension also passed with **two independent 5,972,550,422-byte (>5 GiB)** six-second allocated raw4K60 MOVs. The installed native workflow linked originals, left the copy directory empty, sought beyond 4 GiB, exercised the full edit/review/undo/reload/proxy workflow and exported **84 completely decoded frames / 1.400000 s** of matching original4K60 video/audio. Pixel MAE .052; browser errors empty; native exit normal. It measured .391 s drop→timeline, 3.172 s through proxy-ready, 1.110 s selected seek, 3.000 s export; peak summed workflow working set 1,925.9 MiB. Native drop-bridge payloads are qualified; physical Explorer mouse gestures and arbitrary formats remain unqualified.

The first six-second run correctly produced 84 frames but failed the old harness's fixed 24-frame expectation for five-second media. The harness now computes the expected count from known source duration minus the selected 4.6-second offset and additionally decodes the whole export. The assertion was generalized to the new fixture, not loosened; no renderer change was required.

The installed 3.4.5 workflow passed with two independently allocated **4,977,125,566-byte** sources, native path drop, original linking, proxy cancel/retry, exact original source step, selected-frame review, curves/reference/scopes, linked audio/nest/expand/undo, motion apply/undo, explicit offline AI approval/redo/reload, recovery behavior and normal exit. Export selected packet offset **4,578,951,204**, produced **24 decoded 3840×2160 frames at 60/1**, with audio/video both .400000 s. Source comparison RGB MAE .052 at the test's reduced comparison size. Browser errors were empty. One run measured .656 s native drop→timeline, 3.297 s through proxy-ready, 1.000 s seek, 1.281 s export; peak summed workflow working set 1,724.9 MiB.

Offline scope is explicit: Python source regression blocks external sockets/DNS; native workflow blocks external browser requests and uses a closed loopback proxy. An external test fetch failed as required. The frozen installed executable does not load sitecustomize, so its Python socket guard is reported false. This is not a physical disconnect or OS firewall test.

Visual failure was investigated rather than ignored: DPR alone did not stabilize a systematic flat-color shift. Explicit DPR1 and sRGB capture profile removed display-color dependence. References were regenerated from the preserved, independently verified 3.4.4 MSI, inspected, then all three installed 3.4.5 control images matched exactly at the existing tolerance. This qualifies that capture configuration, not high-DPI/HDR monitor appearance.

Packaged verification also compared all 20 Python entry/engine modules structurally with current compiled source, every web file by SHA-256, and installed executable/web bytes against the built bundle; all matched. tests/verify_bundle.py repeats this automatically in the Windows package job.

Safe production changes: conservative opaque-picture fastpath (three-second original4K60 single-stream median 7.326→6.101 s); range dependencies/persistent bounded program cache (unrelated caption rebuild 12.717 s→.001731 s cache hit with identical MP4); deterministic index-process cancellation/reaping. Independent video/PCM draining, original exports, schema migration and live API integration remain.

All 60 current-source matched video-only engine invocations completed: FFmpeg, MLT 7.41 and native resident/download/software controls at 540p/4K, one/three original4K60 inputs. Native GPU resident won this limited throughput comparison. Its visible SDR child surface, float16/ramp precision and MLT six-channel PCM checks also passed. Complex effect equivalence, integrated audio/VFR/HDR and sustained native presentation remain unqualified. These experiments are not packaged editor features.

The 70-second distinct-source source smoke completed, but recorded 52.04 callbacks/s and 548 browser-dropped frames. The installed full **600-second** sequence then reached its end in **600.117 measured seconds**, with **51.76 callbacks/s**, **4,865 drops / 35,694 browser frames**, .7942 s buffering, 2.674 s first ready, no browser errors and a final complete cache of **12 files / 59,659,593 bytes**. This uses 32 independent two-second 720p60 generated originals, 1,500 timeline clips and a 540p composed monitor, without proxies. Functional/end/budget checks passed; the 60 FPS target did not. Peak summed working set was 1,730.6 MiB; periodic samples plateaued in a ~1,420–1,720 MiB band after initial growth, not proof of no long-term leak. The full low-resolution render passed: 600 s / 1,500 clips / 32 sources, 320×180/60 output, 269.464 s rendering, all 36,000 video frames and 28,800,000 stereo 48 kHz sample frames decoded, zero end sample-count error, source SHA-256s unchanged. This is not long 4K or acoustic sync qualification. The historical drain fixture passed 100 consecutive decoded nine-frame renders. All six CPU/AMD H.264/HEVC/AV1 smoke paths decoded. A final short original4K60 export produced 180 decoded frames on both libx264 (6.360 s, 28.30 FPS) and h264_amf (2.359 s, 76.30 FPS); these single-run simple-scene results do not qualify layered real-time rendering. Hosted ordinary/offline regression passed; native compile initially failed at SDK archive extraction (Server 2022 tar lacked LZMA), corrected to prefer available 7-Zip. The rerun at a7e09f3 passed ordinary/offline regression, MSI/bundle verification and native compile-only. The final head is checked again before delivery.

The final ABBAAB opaque-guard control completed twelve decoded 180-frame original4K exports. Current-renderer guard-off→on medians were 8.984→5.406 s (libx264) and 7.671→2.427 s (AMF), with first/last decoded RGB MAE below .714 at 192×108. This isolates one optimization and differs from the earlier whole-version 7.326→6.101 s set; see ranges and limitations in ENGINE_BENCHMARKS. A tracked reproduction of the drain stress also passed 20/20 decoded repetitions with zero timeouts, in addition to the full 100/100 historical run.

Remaining release blockers include dropped frames/range handoff, native scheduler/source-PTS/audio/effect parity, managed color/HDR/Log/HDR10+, multichannel product routing, pending real-camera corpus, one-hour acoustic sync, unified cache/storage pressure, device-loss/corrupt/clean-Windows/multiple-GPU/high-DPI qualification, signing and corresponding-source/licensing review. No paid request, camera upload or automatic AI edit was used.

---

## Historical 3.4.4 qualification

12 November 2026. Local Windows build **3.4.4**, delivered as release/VlogCraft-Studio-3.4-x64.msi. SHA-256 **D90488F38D5D14ECE6A55FC86548CBDE7F5B7921AB53EFDA05B09CA1FC0D5A2D**. The installed application passed the native workflow. This remains a development build with an experimental buffered playback mode.

## GitHub integration and publication audit

The public repository is [JakubSoltysiak/VlogCraft](https://github.com/JakubSoltysiak/VlogCraft). Git Credential Manager and the connector both verified JakubSoltysiak before writes. Future commits use JakubSoltysiak and 255693@edu.p.lodz.pl.

main preserves the verified 3.3 history plus the publication audit at 3db1d2d85a9911cc1710b08368f9cea9acee3811. All four baseline tags were published with their original hashes. studio-3.3-verified remains ddb8b553da3223337691f6ac25cae95430cbbc93. A fresh mirror clone passed full Git fsck. The 3.4 work is on feature/studio-3.4-playback in [draft pull request 1](https://github.com/JakubSoltysiak/VlogCraft/pull/1).

The initial audit inspected all 11 commits and 154 distinct file-content versions, including archived images. There were no credential-pattern hits, tracked editing projects, personal footage, installers or dependency binaries. Ignore rules now cover local credentials, environments, projects and media. PUBLICATION_AUDIT.md and THIRD_PARTY.md document scope and provenance. No new project license was granted. Corresponding-source review for bundled dependencies remains a public binary-distribution task.

## Implemented and tested changes

- Exact 100, 120/1 and 120000/1001 sequence rates, including the 119.88 alias, use the existing rational frame/tick model.
- Constant-speed editing extends to 10% speed, supporting 20% 120→24 slow motion. Speed ramps and synthesized optical-flow interpolation remain missing.
- 8K UHD is available in the project and export presets.
- A continuous FFmpeg video graph and a separate audio graph evaluate eight-second sequence ranges. Completed streams are muxed for playback. Matching source/seek/speed inputs share decoding within each media type.
- The optional Composited preview monitor plays one combined audio/video stream, prepares the next range, reports progress and supports cancellation, obsolete-state invalidation and selectable preview resolutions.
- The new mode defaults to 540p. Live layers stays the initial interactive mode. Complete preview files have a twelve-file/512 MiB cache budget. Crash remnants and full cache-management tooling need more work.
- Decoded range/export comparisons cover clip appearance/disappearance, title fades, animated rotation, shared source inputs and delayed audio. A cache regression checks reuse, edit invalidation and cancellation.

**The final 33 Python regression tests passed in 35.188 seconds, and all six JavaScript timeline tests passed.** Evidence is build/qa/regression34-final.log and build/qa/node34-final.log. The preceding post-repair full run also passed in 32.476 seconds. Nine packaged engine modules were structurally compared with compiled current source and matched. All bundled web files and the installed executable/web files also matched. build/qa/bundled-source34-drained.json records those checks.

## Installed 4K60 editing and endurance measurements

The performance runs below were recorded with the installed 3.4.4 build after the independent-stream repair. Tests used Windows 11 Pro build 26300, Ryzen AI 9 HX 370, Radeon 890M, 24 logical CPUs, FFmpeg 9.0.2 and WebView2 on one workstation.

The tested 4K60 sources are real decoded H.264/AAC moving test patterns. They are generated stress fixtures. The layered scene contains three video layers with animated transforms and three independent audio tracks. The endurance sequence has 1,500 clips across 600 seconds and was played for 70 seconds. Its cuts repeat one source; this does not qualify 1,500 independent files or a full ten-minute session.

Both cases below use 720p source proxies and the 540p continuous-range compositor. The monitor presents the fully composed result through one video element. These are proxy-assisted, reduced-resolution figures.

| Installed scene | Measured s | Presented composite FPS | Dropped / browser total frames | Buffering s | Initial preparation s | Three seek latencies ms, range | Peak summed working set MiB | Peak process GPU memory MiB, dedicated / shared |
|---|---|---|---|---|---|---|---|---|
| 4k60-3video-3audio-proxy | 9 | 59.67 | 2 / 535 | 0.010 | 8.625 | 47–93 | 1020.2 | 7.86 / 369.64 |
| 4k60-1500clips-proxy | 70 | 59.63 | 16 / 4163 | 0.077 | 3.718 | 31–156 | 2025.0 | 7.82 / 301.79 |

The endurance playhead advanced 69.932 seconds during 70 seconds of measurement. Its UI animation rate was 119.44 callbacks/s and p95 video callback gap was 18.10 ms. The layered run averaged 7.40% of machine CPU, and endurance averaged 8.22%. Preparation peaked at 1060.8/1931.2 MiB summed working set respectively. The table's memory and GPU figures cover playback and subsequent seeks. Process I/O and counter samples are in build/qa/composited34-drained/playback.json and build/qa/endurance34-drained/playback.json.

FPS counts presentation callbacks. The frame totals and drops come from getVideoPlaybackQuality counters accumulated across player replacement; the raw JSON retains the historical decoded_frames field name for totalVideoFrames. Audio meter activity was observed in both cases. The media clock owns this combined stream, so an independent HTML audio-element drift figure is inapplicable. Container A/V duration and delayed audio placement have decoded tests. Physical output latency, sample-locked range handoff and one-hour drift remain unqualified.

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

Actual GPU encoding through AMD AMF is preserved, with software fallback on failure. Final 3.4.4 smoke exports with H.264, HEVC and AV1 passed complete decoding on all three CPU and all three AMD AMF encoders at 640×360/60. build/qa/encoders34-drained.log records the results.

The repaired renderer also exported and decoded 180 original-resolution 3840×2160/60 frames at a 35 Mb/s target. These source-engine measurements use the same packaged engine code verified above.

| Encoder | Export s | Encoded FPS | Sampled process-tree CPU s | Peak summed working set MiB |
|---|---|---|---|---|
| libx264 | 11.063 | 16.27 | 33.11 | 1302.1 |
| h264_amf | 9.219 | 19.52 | 13.20 | 593.1 |

build/qa/encode34-drained/encoding.json contains the measurements. Independent-stream draining introduces scratch-file/process overhead, and current throughput is lower than the historical 3.3 figures below. The reliability repair has not established an export-speed improvement. Recovering throughput while retaining deadline/frame-accuracy checks is remaining work. GPU composition and a native zero-copy decoder/render path remain missing. NVIDIA and Intel driver qualification remains open.

PDH now records dedicated/shared GPU process-memory counters. Those sums can count shared allocations across processes. The integrated Radeon uses shared system memory, so these figures are not a complete physical VRAM inventory. Video/3D utilization counters still report near zero in cases where AMF/D3D11VA completed. Their occupancy interpretation remains unqualified. Raw decode diagnostics are in ignored build/qa/decode34.json.

MLT's service architecture was reviewed as a candidate. The measured prototype reuses the existing FFmpeg effect and audio evaluator to preserve reference/export behavior. MLT was not integrated or performance-qualified.

## Windows installer, large files and recovery

The initial 3.3→3.4.0 and subsequent development upgrades passed. The final 3.4.3→3.4.4 upgrade, uninstall and reinstall each returned zero. Intermediate 3.4.3 contained a rejected renderer experiment and is not a qualified delivery. Shortcuts were removed and restored correctly, and the controlled project-retention sentinel survived. That profile had no pre-existing user project/settings documents in the scanned directory. A populated long-lived profile still needs qualification.

The final installed app passed the complete native workflow with two independently allocated 4,977,125,566-byte MOVs exposed through native paths. It linked originals without populating its media-copy folder, sought beyond 4 GiB, split/trimmed/moved and exercised undo/redo. Its delivery contains 24 frames at 3840×2160/60 with 0.400000-second audio/video. First-frame RGB error against the selected original was 0.891 levels at 96×54.

That workflow also passed original-frame stepping, proxy cancellation/retry, source monitor, grading/reference/scopes, linked audio, nesting/expand/undo, selected-frame multitrack review, motion apply/undo, AI approval/undo/redo, project reload and the single-stream composited monitor. Browser errors were empty and the host exited normally. build/qa/lifecycle34-drained/lifecycle.json and build/qa/installed34-drained-final/windows-workflow.json retain the results.

Control-image comparison initially failed because the capture inherited the native window width. The harness now fixes the viewport at 1440×850, clears focus/hover, and uses reviewed source-build references for those dimensions. The same three installed controls matched with zero mean RGB difference, with the original tolerance unchanged. The 1024- and 1440-pixel layout checks also passed. These checks cover the specific controls and viewports, rather than full visual or accessibility acceptance.

Recovery and previous-format compatibility passed the complete existing regressions. Native high-DPI changes remain unqualified. The earlier WebView2 DPI-emulation attempt timed out. No manual user test is being counted as acceptance.

## GitHub CI/CD

Windows Actions checks all reachable history for credential patterns and forbidden generated files, dependency compatibility, Python/JavaScript syntax, Python regressions, JavaScript commands, application packaging and MSI lifecycle. Official action revisions are pinned and the FFmpeg archive checksum is verified.

The initial hosted run found two assertions that compared an 8.3 temporary path with its canonical Windows spelling. Those assertions now compare resolved paths. Hosted CI later reproduced the mixed-stream drain stall described below. After the independent-stream repair, all 33 Python tests, six JavaScript tests, packaging and MSI lifecycle passed in the [3.4.4 repair CI run](https://github.com/JakubSoltysiak/VlogCraft/actions/runs/43303641985). Final branch checks may run again after report commits. Their live status is shown on pull request 1.

CI does not publish a stable GitHub release or bundled installer artifact. Exact dependency source/redistribution material still needs review for public binaries. The local development installer remains available.

## Render drain investigation and correction in 3.4.4

A hosted run timed out in the existing multitrack title/two-audio render despite the 3.3 single-filter-worker workaround. Controlled local reproduction then timed out in two of twelve original renders. Serial decoding alone and separate demux inputs with combined encoded output also remained intermittent. Those failed runs remain recorded in ignored build/qa diagnostics.

An output-shortest experiment sometimes appeared stable but later stalled and dropped fractional-rate/8K frames. Restricting input duration damaged preroll and selected-frame accuracy. Both changes were rejected. The final code preserves preroll and exact output frame/sample bounds, renders video and PCM audio independently, then muxes complete streams. Export and buffered preview both use render_range. This adds process and scratch-file overhead in exchange for removing the reproduced combined-stream drain dependency.

The repaired scene passed **100 consecutive renders, zero timeouts, all nine expected frames per render**, with every output decoded. build/qa/stall-drained34.json retains the results. The ordinary mixed-track regression repeats three times with a 20-second deadline and exact frame-count checks. Fractional-rate, VFR held-frame, animated reference/preview parity, short 4K120 and short 8K tests all passed the complete suite. This evidence qualifies the tested scene and corpus; arbitrary long-form material still needs stress qualification.

## Pending-seek correction in 3.4.2

Final review found that a range completing preparation could display an earlier cursor position. The monitor now records the latest requested target and either seeks the prepared range to that target or loads the range that contains it. The installed regression issues a seek during preparation and verifies the resulting media time before playback. Cache misses can still wait for current preparation.

The correction first passed the 3.4.2 installed workflow. The final 3.4.4 application was rebuilt from source and again passed the complete native workflow, including that pending-seek regression.

## Known limitations and next priorities

The buffered mode has startup/cache-miss latency and range handoff overhead. The independent-stream reliability repair adds export overhead. It is an experimental transport, and live-layer preview remains available. Full continuous native/MSE playback, sample-locked audio, hour-long endurance, high-DPI changes, camera acceptance media, GPU composition and broad HFR/8K qualification remain production blockers.

Offline review/proposals remain multitrack-aware and consent-bound. The optional online AI connector retains its existing legacy scope. No paid call was required and no footage was sent to an external service. Public GitHub publication includes source and reviewed demonstration images.

The next work is to remove range handoff gaps with an uninterrupted transport, reduce first-play preparation, qualify longer HFR/8K camera material and mixed codecs, and add a measured zero-copy GPU path. Professional masks, managed HDR, corrective tracking, audio mastering, multicam and interchange gaps remain listed in FEATURES.md.

---

# VlogCraft Studio 3.3 release qualification

12 November 2026. Private Windows development release. The qualified MSI is release/VlogCraft-Studio-3.3-x64.msi, 206,409,324 bytes. SHA-256 is **566D077D2FFD2972B59DCA6B03D77C3A845E35C4F844FE2333FFBA15A93D0AA2**. Version 3.3 was installed with Start menu and desktop shortcuts for this historical qualification.

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

The first complete run stalled in the FFmpeg mixed-video/title/two-audio graph. A diagnostic reproduction also timed out. The stalled child was terminated, and that run is recorded as failed in build/qa/regression33.log. Using one complex-filter worker resolved that reproduced run. The fixed complete suite passed at the time. Later 3.4 hosted stress reproduced an intermittent drain stall, superseding that workaround as described in the 3.4 report above. The affected regression now imposes a 20-second subprocess deadline.

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
