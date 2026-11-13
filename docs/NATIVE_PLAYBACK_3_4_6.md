# Experimental native playback integration — 3.4.6

This development milestone continues commit 6bf93f94033936d1ac66ed872c64ba8e5b31ba31. PRs #1 and #2 remain unmerged drafts. The existing WebView2 interface, editing commands, project schema, live API integration and production FFmpeg exporter remain. **Native GPU preview is opt-in and is not production-qualified.**

## Implemented contract

The local C++ child uses libav/D3D11VA original-media decoders, one asynchronous producer per active asset, at most three decoders, four queued AVFrames per producer and three float16 composition slots. GPU queries retire frames asynchronously; shared D3D immediate-context work uses FFmpeg's device lock. Present runs outside that lock. Adjacent source-contiguous cuts reuse decoders. Discontinuous cuts and generation seeks flush/decode from an earlier keyframe and select the held half-open source PTS interval. Rational sequence/source units are rescaled with integer arithmetic. Stream display matrices supply orthogonal source orientation.

The native panel is parented to the existing Windows form. CSS bounds are converted using devicePixelRatio. Paused resize redraws; dialogs, reference images and scopes hide the child surface. Child exit/device errors return the full SDR program to the FFmpeg compositor. PQ failures block native display until the user explicitly selects SDR composition. Process termination/retry is tested; actual GPU removal/reset and multi-monitor HDR changes are not.

The audio master is a bounded 48 kHz stereo AudioWorklet fed by raw PCM from the existing FFmpeg audio compiler. No intermediate encoded program video is required for the supported native path. Eight-second PCM production chunks have exact cumulative sample budgets; the browser splits arbitrary network reads below its 96,000-frame queue capacity. Audible output timestamps map through sample-counted segments that exclude pause/underrun gaps. Seeks cancel obsolete PCM, coalesce destinations and use generation checks. Initial source audio PTS offsets are retained. Identity speed bypasses atempo; actual speed processing retains the existing compiler. Mono/stereo admission is explicit; multichannel is rejected rather than silently folded.

## Capability and fallback matrix

| Area | State and evidence | Remaining limits |
|---|---|---|
| Original H.264/HEVC decode | Tested on generated 4K60 and three local camera recordings, including Main10/P010, B-frames and VFR | Other codecs use reference; broader damaged/long media corpus pending |
| Source timing | Nine real-camera PTS seeks matched bounded FFprobe tables; rational 60000/1001 integrated transport | Full-file VFR indexing, negative/video start gaps and hour-long sync not qualified |
| Multitrack composition | Three source layers; position, scale, opacity, orthogonal source orientation, rotation and source-time transform keys | SDR encoded-domain blending approximates reference; calibrated managed-color parity pending |
| Nested sequences/cuts | Flatten existing sequence model; bounded active sources and decoder reuse | Overlapping offsets of one asset, >3 layers use reference |
| Advanced effects | Whole-program fallback for titles, stills, masks, chroma, wipes, curves/LUT/grades, unsupported/Bezier keys | These remain functional in the existing renderer; no native parity claim |
| Audio | Shared EQ/compression/gain/speed compiler, stereo PCM, pause/seek/cancellation and exact sample budgets | No multichannel routing, acoustic measurement, device clock change or hour-long drift qualification |
| HDR precision | FP16, 10-bit sampling, PQ EOTF and BT.2020 to linear scRGB; decode-side HDR10+ side data retained | No HLG/Log/APV transform, mixed SDR/HDR working space, HDR10+ application/authoring or native HDR export |
| HDR display | Explicitly rejects PQ when Windows HDR is inactive; no automatic SDR conversion | This session cannot qualify actual HDR scanout/calibration |
| Recovery | Owned child cancellation/reap, unexpected child exit, full SDR fallback and retry | Real D3D device reset, disk-full/import interruption and multi-vendor soak pending |
| Export | Existing original-media FFmpeg CPU/hardware fallback; 4K60 remains available | Native GPU export is not implemented; export remains explicit 8-bit SDR/stereo |

## Real-camera privacy and inspection

Three owner-provided originals were ignored before development and opened only for reading. All probes, PTS tables, graphs, frame readbacks, audio and exports remain in ignored local QA storage outside the original directory. Public results use CameraA/B/C aliases and selected technical numbers. No private footage, frame, thumbnail, source hash, original name, identifying path, GPS or private metadata is included in Git.

A failed early baseline traceback exposed one source identifier to the assistant's tool output; it was acknowledged, and subsequent errors were filtered. It was not published to GitHub. This distinction prevents a false claim of literally zero identifier exposure during tooling.

| Alias | Verified video | Verified timing/color/audio |
|---|---|---|
| CameraA | 3840×2160 HEVC Main10, 10-bit 4:2:0, display rotation −90° | Nominal 60; average about 57.22, timebase 1/90000, variable intervals. Limited BT.2020 nonconstant/PQ; mastering/content-light and SMPTE2094-40 HDR10+ side data. AAC stereo 48 kHz; audio starts +6 ms |
| CameraB | 3840×2160 HEVC Main10, 10-bit 4:2:0, display rotation −90° | Nominal 60; average about 59.78, timebase 1/90000. Same verified color/side-data classes; AAC stereo 48 kHz; audio starts about +31.896 ms |
| CameraC | 3840×2160 H.264 High, 8-bit full-range 4:2:0, no display rotation | 60/1, timebase 1/15360, bt470bg matrix, unspecified primaries/transfer; no audio stream |

FFprobe did not provide a verified camera model, lens, focal length, exposure or Samsung Log identification. These are unavailable, not inferred. CameraC's unspecified transfer is not proof of calibrated SDR. Windows HDR output was inactive.

## Baseline and comparison methodology

Baseline was measured before engine changes against the installed 3.4.5 build, with local probes and original hashes retained privately. Three-second original4K explicit-SDR exports took 25.521 / 25.557 / 10.848 seconds for A/B/C; each decoded to 180 output frames. Software decode of 180 frames took 11.895 / 11.526 / 4.546 seconds. These are separate decode/export workloads.

Installed 3.4.5 three-second 540p program startup took 17.151 / 17.036 / 5.547 seconds and then completed each short scene at approximately 56.7–57.6 browser callbacks/s. A separate 36-second combined program failed to finish during a 45-second observation, advancing only 8.421 seconds with 36.267 seconds of buffering. That failure is retained.

The native CameraC three-second GUI case first became ready in .722 seconds and ended with 144,000 generated-silence clock samples and no underruns. CameraC has no audio, so this does not test camera audio sync. CameraA/B native GUI presentation was blocked by inactive HDR, not silently tone-mapped. Native 180-frame offscreen runs were approximately 1.2–1.5 seconds, but omit audio, display and export encoding and cannot be called a 20× export speedup.

Private float comparisons use FFmpeg/zscale linear PQ/reference conversion followed by float-only resize/pad. An earlier reference chain clipped HDR to 1.0 and was rejected. The corrected first-frame comparisons had normalized RGB MAE .00350 / .00981 / .00183 (A/B/C). This numerical test preserves values above SDR white; it is not calibrated color or complete effect parity.

## Qualification boundaries

See VERIFICATION.md for final measured test/package results and sanitized machine-readable evidence. Earlier failures are retained: oversized PCM network reads initially deadlocked playback; resetting a decoder at every adjacent cut reduced presentation to about 36 FPS; a padded chroma-edge read corrupted the last visible row; and seek audio initially resumed before its queue was ready. Fixes address the measured causes.

Remaining release gates include sustained original4K60 with no frame losses, 10–60 minute real-camera sessions, calibrated HDR/mixed-color/effect parity, acoustic sync, actual device removal/recovery, independent long-source stress, other GPU vendors, accessibility/DPI/display qualification, code signing and dependency corresponding-source review. The native engine stays experimental and the full FFmpeg path stays available.

## Reproduction and local packaging

Use tools/setup_architecture_lab.py with --component zig --component ffmpeg-shared --build-native, then benchmarks/native_precision.py, tests/native_windows.py and benchmarks/native_playback.py on generated fixtures. benchmarks/camera_native.py accepts a private manifest and writes only to a separate local results directory; never publish its raw outputs. tools/audit_private_media.py verifies private names/metadata absence and original SHA256/mtime without printing them.

packaging/build_windows.py --experimental-native includes the optional runtime and its DLL/license/hash manifest in a local MSI. The ordinary build can omit it; the default renderer is unchanged. CI compiles/packages but has no GPU qualification and uploads no native binaries. The pinned shared FFmpeg build contains GPL components. This milestone grants no new license or binary redistribution clearance.
