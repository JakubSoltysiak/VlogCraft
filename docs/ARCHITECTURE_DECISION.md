# Decision: retain the editor, develop a GPU video slice behind parity gates

13 November 2026; development decision, not approval to replace the production transport or merge PR #1.

The low-risk delivery is the optimized existing FFmpeg engine. The preferred next media-engine direction is **libav hardware decode → D3D11 GPU-resident high-precision composition → native display**, alongside the existing WebView2 UI, project/command model, offline assistant, audio/reference/export fallback. The [matched tests](ENGINE_BENCHMARKS.md) demonstrate a useful video-only advantage on Radeon 890M. They do not demonstrate a complete winning nonlinear editor.

At three original 4K streams and 4K output, native hardware composition led CPU FFmpeg and the tested MLT CPU image-pull path. Hardware decode with download was materially slower than keeping surfaces resident. Native child-window presentation coexisted with WebView2. The presentation prototype still serialized every frame behind a GPU completion query and did not sustain an established gap-free 60 FPS session. Production default remains unchanged.

## Alternatives actually evaluated

| Candidate | Evidence | Decision / unresolved gates |
|---|---|---|
| A: existing FFmpeg | Real project compiler, decoded regression, measured opaque-base and cache improvements; continuous raw RGBA pipe to WebGL canvas | Ship narrow verified improvements. Retain complete effect/timing/export fallback. Raw transport lacks audio/pacing and cannot by itself solve CPU composition. |
| B: MLT 7.41.0 Windows | Real moving images via C ABI, affine composition, threaded rawvideo consumer, FFV1 file, RGBA64 ramp and six-channel PCM | No adoption on measured CPU path. Existing effects/project commands still need translation. New MLT 7.42 placebo GPU module was not built or benchmarked; this result does not reject that module. |
| C: libav + D3D11 C++ | NV12/P010 decoder textures sampled directly, float16 target, download/software controls, visible SDR swapchain embedded beside WebView2 | Preferred narrow next prototype. Not shipping replacement: source PTS/VFR, audio, equivalent effects, export hardware surfaces, full color management and sustained presentation remain gates. |
| D3D12 | API/ownership review only | No working prototype or throughput claim. D3D11 interop matches the tested decoder path; revisit D3D12 only with a measurable need. |

MLT's official [7.42 release](https://www.mltframework.org/) describes a new libplacebo GPU module. The portable binary tested here reports 7.41.0. GPU, HDR, effect/transition compatibility, licensing selection and packaging for that newer module remain independent investigations.

## Why C++ for this slice; Rust remains a candidate

The environment had no MSVC SDK/Rust toolchain on PATH. An isolated checksum-pinned Zig C++ compiler built a small direct C/COM/libav slice. C++ gives straightforward access to AVFrame hardware contexts, COM textures, DXGI and shader compilation with RAII around native handles. It also permits memory-unsafe defects; fuzzing, sanitizers and explicit ownership are necessary before adoption.

Rust could enforce ownership around queues, generations and resource handles, but FFmpeg/COM/shader boundaries still require audited unsafe FFI and wrapper/toolchain packaging. No Rust implementation was benchmarked. There is no evidence here for a language speed difference. Choose a stable narrow C ABI now; consider Rust for the scheduler or engine once equivalent tooling, Windows integration and maintenance costs are evaluated. Do not rewrite the Python/UI to obtain a different language.

## 3.4.6 implementation checkpoint

The limited scheduler/audio/panel contract is now experimentally integrated. See [current implementation, parity/fallback and measured limits](NATIVE_PLAYBACK_3_4_6.md). The 125-second original4K/540p monitor test remained below 60 presented FPS; default adoption and full HDR/effect qualification remain blocked. The contract below records the earlier design, not a claim that every gate is now complete.

## Proposed engine contract — historical 3.4.5

- Input: existing immutable project snapshot plus generation, exact Fraction sequence rate, source tick ranges and track evaluation. UI commands remain unchanged.
- Frame: sequence frame number, original source PTS/timebase, duration, orientation/SAR, alpha convention, color description, optional dynamic metadata reference and owned GPU surface. Never substitute nominal FPS for VFR source PTS.
- Scheduler: bounded decoded-frame/audio queues, one owner per D3D11 immediate context, asynchronous producer, audio-master clock, explicit GPU fences, cancel/release on seek or project generation change. Limit in-flight textures using measured memory, not an unbounded queue.
- Display: native child surface with transport controls in WebView2; handle resize/DPI/occlusion/device-loss, no private file payload across UI IPC. Separate CPU submission, GPU completion, DXGI presentation and physical-display measurements.
- Export: graph evaluation shared with display at original resolution, GPU encode interop only when real capability tests pass, deterministic CPU fallback, separate video/audio drains preserved until equally reliable replacement proven.
- Faults: return a structured unsupported operation/media/device failure; switch the entire affected range to a faithful reference path. Never silently skip an effect or reinterpret color.

Microsoft documents that [GetData](https://learn.microsoft.com/en-us/windows/desktop/api/d3d11/nf-d3d11-id3d11devicecontext-getdata) returns completion status for GPU queries. Current per-frame waiting intentionally proves completed work, but prevents useful overlap. Replacing it with a bounded ring must preserve measurement of completed frames rather than counting queued submissions as throughput.

## High precision and HDR contract

Current product: 8-bit SDR picture pipeline and stereo delivery, with an explicit export notice for PQ/HLG-to-SDR behavior. Prototype: P010 and RGBA16_FLOAT preserve more than 256 ramp levels, including software/download controls; this is precision preservation **without HDR color management**. Prototype rejects PQ/HLG/BT.2020 rather than pretending it handles them.

Future graph must retain bit depth, chroma siting, range, primaries, transfer, matrix, mastering display, content light and per-frame metadata independently of pixel storage. Decode transfer and transform into a documented common working space; perform compositing in an explicit linear/scene-referred float space; define SDR reference-white/peak handling. LUT domains, interpolation, alpha premultiplication, gamut mapping and tone mapping must be testable. Float16 storage by itself does not define any of these.

Windows HDR preview needs correct output color space, advanced-color detection, calibrated display transform and verified HDR-capable presentation. The current BGRA8 SDR swapchain is not that path. Export needs appropriate high-bit-depth codec/profile/container signaling and decoded verification, not copied labels.

[Samsung's Log documentation](https://developer.samsung.com/mobile/samsung-log-video.html?lang=en) supplies a basis for supported transfer/LUT workflows; actual embedded model/mode/firmware and sample files must establish the profile. Do not fabricate lens matrices or assume every Galaxy file is Log. [Samsung APV documentation](https://developer.samsung.com/mobile/apv.html?lang=en) describes a separate codec; support on another device generation does not prove S25 Ultra recording capability. APV decode/encode, formats, metadata and packaging are untested.

### HDR10+ metadata

Keep original metadata locally, keyed by source frame PTS and provenance. Untouched eligible passthrough may preserve it. Retiming must map metadata to the actual selected output pictures. Scaling, blending, titles, masks, grading or transfer/gamut changes invalidate the assumption that source mastering metadata describes output; discard/regenerate according to a validated mastering policy, and label the delivery honestly. Never blindly copy a dynamic payload onto changed pictures.

The [HDR10+ workflow paper](https://hdr10plus.org/wp-content/uploads/2023/11/HDR10_WhitePaper.pdf) includes mastering/metadata generation and encoding; [x265's dhdr10-info](https://x265.readthedocs.io/en/4.1/cli.html) accepts creative-intent metadata for encoding. Tool acceptance is not proof of correct mastering. Metadata extraction, timeline mapping, generation, syntax, frame association and actual TV playback all need acceptance tests. Full HDR10+ authoring is absent.

## Audio architecture

Current stereo caches/mix/export cannot preserve all source channels. New probe fields expose actual source layout without implying multichannel delivery. The isolated MLT six-channel test preserved 96,000 PCM sample frames bit-exactly; it is not integrated project routing or Atmos.

Use explicit sample rate, channel mask/order, sample count and rational clock origin through clip edits, buses and export. Preserve compatible untouched compressed bitstreams only when container/cut/tempo constraints allow it. Mixing/processing requires decoding; source spatial/object metadata cannot simply be copied afterward. Binaural stereo, 5.1/7.1 speaker PCM and Dolby Atmos object bitstreams are different deliverables. No Atmos encoding/mastering is implemented. PCM multichannel and accurate monitoring/downmix take priority.

## Finalization evidence

The installed 3.4.5 ten-minute synthetic test reached its sequence end but delivered 51.76 callbacks/s. A matched 3.4.4 control was similarly below target. Cached seeks are fast while uncached original4K program ranges take seconds. Full low-resolution long export frame/sample counts and two independent >5 GiB native workflows passed. These findings reinforce the incremental scheduler/parity milestone; they do not justify enabling the native prototype as the default.

## Adoption criteria

Do not switch the default until the native slice passes rational/VFR PTS and frame-ID cuts; three-video/three-audio animated effect equivalence; sample-accurate clock tests; seek/cancel/recovery/device reset; original-quality CPU/GPU export fallback; bounded long-session memory; explicit SDR/HDR policy; two independent >5 GiB native imports; and 10–60 minute real-camera sessions. Preserve an automatically exercised full-fidelity FFmpeg fallback throughout.

License/source-provision and build reproducibility are separate release gates. Experimental shared FFmpeg/MLT tools are fetched into ignored local storage; no binaries or private recordings are published.
