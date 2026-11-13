# Workstation optimization — 3.4.7 development

This milestone continues PR #3 / commit 48f4d4e6ce28e063121514d601984435071a9bb5. PRs #1–#3 stay unmerged drafts. The newer canonical main roadmap, including VC-P0-024–031, was merged into the new development branch without replacing the 3.4.6 history. Native preview stays optional. Original-media export and the full FFmpeg fallback remain.

## Verified workstation and conditions

| Item | Locally observed technical fact |
|---|---|
| CPU | Ryzen AI 9 HX 370; 12 physical / 24 logical processors. Windows topology exposes four cores in efficiency class 1 and eight in class 0, each with two logical threads. No affinity is forced. |
| Memory | Firmware reports four 8 GiB memory devices, 32 GiB total, configured 7500 MT/s, 32-bit data width per firmware device. This does not imply four replaceable DIMMs. |
| GPU / driver | Radeon 890M, driver 32.0.32015.7029; D3D11 feature level 11.1 in the explicit device probe, unified-memory architecture. About 338 MiB dedicated and 15,932 MiB shared memory reported; those figures are not guaranteed free VRAM. |
| Decoder formats | Actual D3D11 profile queries accept H.264 NV12, HEVC Main NV12, HEVC Main10 NV12/P010. Codec/profile/bitstream and concurrent-stream limits still require actual playback tests. |
| Storage | MTFDKBA1T0QFM-1BD1AABGB NVMe SSD, about 1.024 TB decimal, NTFS system/cache volume. No serial, disk ID or private path is collected. |
| Storage microbenchmark | One generated 128 MiB direct-I/O write: 2,134 MiB/s; sequential read 3,494 MiB/s; 512 random 4 KiB reads p50 .0668 ms / p95 .1138 ms. Temporary file deleted on close. Short bounded/device-cache-sensitive test, not sustained-drive certification. |
| Display | Physical 2880×1800. Available DXGI rates 60/1 and 120/1. Initially battery mode reported 60 Hz; after the owner connected AC, Windows reported 120 Hz, 10-bit output and PQ/BT.2020 DXGI color space. No display/HDR/power-plan setting was changed by the app. |
| Power / thermals | Initial battery 34%, then owner-connected AC. Accepted comparisons record stable AC operation. Balanced Windows power plan observed. Public thermal-zone sensors unavailable; no claim of absence of throttling. |
| NPU | AMD Compute Accelerator driver 32.0.20102.4480 present. No ONNX Runtime package in the test Python environment; no compatible inference model/runtime workload was qualified. NPU is not used for video decode or composition. |

Hardware profiling is opt-in and local. Whitelisted technical fields exclude hostnames, users, serials, instance/network IDs and media paths. The native probe opts into DPI awareness before reporting physical monitor dimensions; an initial DPI-virtualized inventory was rejected. Reported OS build was Windows 11 Pro 26300. Actual disk free space and available RAM are recorded per local run because background applications and charging conditions change.

## Baseline and reproducible methodology

The preserved 3.4.6 installer/runtime was used before candidate binaries. Historical 3.4.6 had 125 seconds / 1,500 clips, three original 4K inputs plus three audio tracks, 960×540 composition, about 57.2 presented FPS / 345 skips / zero audio underruns. That is not 4K-resolution output.

Fresh matched AC baseline trials 2/3/4 used the same 125-second generated workload and original source offsets. Present-call rates were **57.829 / 56.768 / 57.715 FPS**, skips **264 / 407 / 279**, and first-ready latencies **.998 / .966 / 1.038 s**. All reached their ends with 6,000,000 samples and zero underruns. Peak summed working sets were 2,146.5 / 2,578.5 / 2,496.5 MiB. These sums can count shared pages more than once.

Early battery trials and a setup/compilation-interference warmup are retained separately and excluded from the AC comparison. One old-runtime trial fell back to FFmpeg; the original harness then failed because native counters were absent. The corrected harness retains the failure data and does not count it as completed native playback. Filesystem caches were not forcibly emptied: fresh app/program versus repeated source visits are distinguished, not called guaranteed cold SSD reads.

Baseline repeated-seek GPU-completion endpoint: p50 498.5 ms / p95 644.1 ms, 12 source visits. The first three distinct destinations and subsequent repeats remain in the raw numerical report. Three identical 3-second original 4K60 CPU export trials had median **6.035 s**, range **5.858–6.090 s**. Independent render/audio drain and output quality settings were unchanged.

## Confirmed scheduling bottlenecks and experiments

Native timing now separates source-queue waits, GPU-slot waits, queue-free clock skips, source-frame repetition, CPU submission, immediate-context lock waits, asynchronous completion observation, GPU timestamp composition and Present calls. Histograms are bounded, with .1 ms quantile bucket upper bounds and explicit overflows above 100 ms. GPU completion-observation latency includes polling/queueing and is not shader execution time. DXGI counters and CPU Present intervals are not physical scanout or acoustic measurements.

The coarse Sleep(1) probe actually slept p50 **15.803 ms**, p95 **16.000 ms**. The old scheduling code could miss a 16.667 ms sequence boundary just waiting for its next poll. The instrumented three-layer test measured mean GPU composition around .78 ms while completion observation p95 reached 62.2 ms. High GPU usage alone did not identify a slow shader.

A scoped high-resolution waitable timer now wakes on deadlines, native commands or window messages. It does not alter global timer resolution, desktop refresh or power settings. The timer-only trial reduced p95 Present-call interval from about 31.5 to 18.9 ms and measured p95 wake overshoot .7 ms, but still skipped frames. This short result motivated further queue investigation rather than a 60 FPS claim.

One-frame and two-frame DXGI admission queues reduced GPU completion age but presented only about 55.1 and 54.8 FPS in the short trials. Both were rejected. They are not shipped as an optimization. A memory-budgeted GPU completion ring and corresponding decoder-surface allowance removed GPU-slot starvation in the accepted long trial. An original-frame prefix cache then reduced recurring source-seek starvation. Cached selection requires the next actual PTS; it never synthesizes an interval or interpolated image. Forward playback holds through backward clock corrections instead of redrawing earlier sequence frames. Raw calls and distinct sequence submissions are recorded separately.

## Real media: provenance and privacy

The owner identifies CameraA and CameraB as Samsung Galaxy S25 Ultra recordings; CameraC is a Google Earth travel animation. FFprobe does not independently prove a device model or Samsung Log. The correction is provenance from the owner, not fabricated embedded metadata.

A/B remain original 4K HEVC Main10/PQ/BT.2020 with HDR10+ decode side data and rotation; C is full-range H.264 without audio. All originals are read-only, ignored, and hashed before/after. Temporary plans, frames, PTS tables, raw logs and exports remain in separate ignored local storage. Only aliases/technical measurements are published.

On the now-active AC/HDR desktop, the 3.4.6 baseline displayed six seconds of each original: first-ready .587 / .561 / .852 seconds for A/B/C, 288,000 clock samples each, zero underruns. C's clock audio is generated silence. This verifies digital playback, not calibrated HDR mastering or full dynamic-metadata application. HDR10+ remains retained at decode only.

## Smart preview and diagnostics scope

Manual native monitor choices cover 540p, 720p, 1080p, 1440p and 2160p. The status states actual composition dimensions and reduced versus original output resolution; presentation size is measured separately. Quality changes rebuild the native surface instead of merely seeking the old-resolution instance. The existing original-resolution reference/export path remains independent.

Optimize for My PC runs a genuine local inventory and optional bounded storage test. Its suggestion is a conservative display/memory preview choice with explicit uncertainty; applying it changes only monitor resolution and can be reversed with the existing control. It does not silently switch the experimental engine or alter export settings. Full automatic decoder/encoder/cache/background scheduling calibration and seamless dynamic resolution require additional measured policy.

## Permanent regression framework

benchmarks/performance_suite.py defines QUICK (correctness/JS/precision), STANDARD (transport, playback, seek/export/memory) and FULL (multiple monitor resolutions and endurance) profiles. performance_gate.py compares repeated trials only when workload, source class, composition/surface resolution, rate, proxy/cache state, power, driver and active refresh match. >5% throughput loss or >10% latency increase triggers investigation, retaining ranges and repetition counts rather than hiding noise.

Conditions record AC/battery, system CPU and available RAM. Counter buffers and process ownership are bounded; private raw reports are never uploaded. Future feature PRs must run the affected profile and update measured results. Hosted Windows CI cannot replace GPU, display or actual camera tests.

## Final measured results

Matched 125-second medians: **57.715 → 59.666 Present calls/s** (+3.38%), **279 → 28 skipped sequence frames** (89.96% reduction), native first-ready **.998 → .934 s**. Candidate raw and distinct rates agree in all three matched trials. Candidate rates ranged **57.832–59.796**, with 12/28/262 skips; that variation prevents a zero-skip sustained60 claim. All runs ended with 6,000,000 sample frames and zero underruns.

The FULL 600-second / **7,200-clip** 540p case ended with **28,800,000 samples**, zero underruns, **59.872 distinct frames/s** and **62 skipped sequence frames**. Three skips followed source waits; none followed GPU-slot waits. Remaining tails occurred without source/GPU queue starvation and include clock, driver/Present and host scheduling. Physical scanout/acoustic causality is not established. P95 CPU Present interval was 18.1 ms. Whole-process summed working set rose from 3,256 to 3,616 MiB over ten minutes, peak 3,703 MiB; bounded GPU/cache ownership is verified, a general leak-free claim is not.

Memory is a real tradeoff: matched median peak summed working set **2,496.5 → 3,437.3 MiB**. Matched CPU medians were **9.02% → 8.91%** of the machine, within variation. Earlier historical 6–7% CPU numbers came from different power/display conditions and are not the comparison. Shared GPU-memory peak medians were roughly 2,018 → 2,283 MiB; UMA pages/counters can overlap. PDH video/3D occupancy returned zeros despite actual hardware frames and GPU timestamp work, so no utilization improvement is claimed.

All five short monitor-quality cases completed with exact audio counts and zero underruns. At 3840×2160 composition, the small-surface 30-second case had zero sequence skips. The corrected physical-layout test used the native 2880×1676 client, **168 DPI / 175%**, and a **2545×1432** presentation surface: 30 seconds, 3 skips, 59.393 distinct frames/s, 1,440,000 samples / zero underruns. Its first harness overlay was resized by normal monitor layout and became portrait; that invalid case was rejected and an aspect-ratio assertion added. No app image-quality tolerance was relaxed. FPS windows include up to one 250 ms end-observation tail; exact frame completeness is also reported.

Single-source cadence tests at 24/25/30/50/60000/1001/60/120 passed exact timeline sample budgets. The 120 case deliberately held original 60 frames and skipped three sequence frames; generated frames were zero. cadence.py models ideal rational holds, not measured physical scanout. GDI nominal120 and the probe's DWM ratio 10000000/83701 (~119.47) are both retained rather than forcing a refresh mode.

Strict repeated same-UI/runtime-swap seek controls (two runs ×12 destinations per arm) gave median-of-trial p50 **494.7 → 522.9 ms**, p95 **697.5 → 671.3 ms**; ranges overlap. An initial >10% p95 comparison was investigated with a stricter new-generation/actual-frame endpoint; no reproducible >10% regression remained. No significant seek speedup is claimed. Fresh frozen-process ready medians were **2.153 → 2.278 s**; caches unmanaged. Native cold start remains variable; a final installed functional case took 1.65 s.

The first export comparison (6.035 → 7.673 s for three seconds original 4K60) triggered investigation. render_engine.py is byte-identical to 3.4.6. Six alternating-label executions of that same compiler ranged **6.860–8.907 s**, with arm medians 7.451/7.004 s. This estimates condition noise, not an implementation speedup. Export performance remains unoptimized; no improvement is claimed. CPU and AMD AMF H.264/HEVC/AV1 smoke exports all fully decoded.

All three complete real recordings then played on the installed native runtime: **81.683 / 49.267 / 18.017 s**, sample budgets **3,920,800 / 2,364,800 / 864,800**, zero underruns. Nine bounded direct seeks plus fifteen cache/cut PTS checks matched local reference tables. Original hashes/mtimes remained identical and the original folder still contains exactly three files, no generated additions.

The isolated 640×360 CPU interpolation experiment produced 116 decoded motion-compensated output frames in 5.213 s (~22.25 FPS), versus 120 repeated frames in .190 s. Lookahead truncated the end, artifact/energy acceptance was not performed, and no GPU/NPU model was qualified. It was rejected for product adoption. No interpolation control or export change was introduced.

Adaptive resolution was not adopted: the tested resolution matrix did not show a clear shader-resolution bottleneck, while a quality change currently rebuilds transport. Manual quality and original-resolution reference remain available. Full automatic worker/encoder/cache calibration is future work. [Sanitized records](benchmarks/2026-11-13-native347) retain compatible contracts, results and investigation notes.

## Remaining gates

Final results, failed attempts and precise scopes are in VERIFICATION.md. Broad production adoption still needs sustained frame-accurate 60 FPS, physical presentation/acoustic sync, longer original-camera sessions, complex native effect parity, actual GPU reset, calibrated HDR/HLG/Log/mixed working spaces, dynamic-metadata mastering, native GPU export, multichannel and other hardware/Windows/display qualification. No stable release is created.
