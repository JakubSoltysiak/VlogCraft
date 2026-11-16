# P0 color foundation — development scope

Starts from verified source checkpoint83e6afb on a dedicated branch stacked on PR #7. The owner's new P0 instruction authorizes independent HDR foundation work; previous playback/audio/memory blockers remain release blockers. No stable release or existing PR merge is authorized.

## Existing pipeline audit

| Stage | Existing representation and limitation |
|---|---|
| Probe/project | Transfer/primaries/matrix/range/pixel format and rational source timing persist; mastering/content-light and per-frame dynamic metadata are not represented reliably. |
| Native decode | libav D3D11 NV12/P010 or software upload. Decode-side HDR10+ frame side data can survive queues; this is not HDR10+ output authoring. |
| Native composition | FP16 target; PQ EOTF and Rec.2020-to-linear709 scRGB transform, alpha blending. SDR uses encoded-domain compatibility. Mixed SDR/HDR and HLG are rejected. SDR creative effects route to reference. |
| Native presentation | PQ plans require active DXGI HDR output and an FP16 scRGB swap chain with explicit G10/P709 signalling. This is uncalibrated OS-managed HDR, not guaranteed calibrated monitoring. |
| Reference | HDR sources tone-map to709, final yuv420p/libx264. Effects/overlay/LUTs assume SDR. Cannot currently export genuine HDR10. |
| Export | Independently drained video/audio, rational frame/sample budgets, concatenation and atomic destination replacement; output 8-bit SDR regardless of HEVC selection. |

## Intended first slice and gates

Add an opt-in, versioned color contract: explicit source interpretation/overrides, separate technical transforms and creative controls, display-linear Rec.2020 float32 reference working values (1.0=100cd/m²), and explicit SDR/HDR10 output choice. Preserve legacy projects/SDR behavior. Qualify actual installed FFmpeg float32 filter negotiation before selecting the high-precision graph. No implicit 8-bit conversion is acceptable.

First HDR10 output uses software HEVC Main10, PQ/2020 nonconstant matrix and validated static mastering/content-light values when provided. Never copy picture-dependent HDR10+ metadata after edits or silently downgrade an HDR10+ request. Unsupported creative operations must fail explicitly. Native PQ/scRGB remains opt-in; explicit SDR monitoring is labelled separately from HDR output. HLG and Samsung Log interpretation must be represented without pretending their transforms are qualified.

Generated ramps, known PQ luminance values, linear blends, decoded Main10 metadata/frame/audio counts, persistence/recovery, private read-only originals and limited matched performance checks will determine acceptance. Results and supported-operation boundaries will be appended after actual verification. The historical4.629s gap/657underruns/active-memory plateau are not part of this feature's success claim.

## Implemented foundation checkpoint

The output.color version1 contract records workingSpace=linear-rec2020-100nits, explicit hdr10/sdr delivery, SDR reference-white policy and optional declared mastering/content-light values. Legacy output without this contract retains its existing SDR path. Existing project version4 is retained. Clip inputColor stores explicit transfer/range/pixel-aspect interpretation independently of asset colorMetadata; hdrExposure is a separate display-linear gain in stops. HLG/Log profile identifiers survive save/reopen but their rendering transforms fail explicitly. No source conversion is baked into original media.

PQ decodes to absolute linear light normalized so1.0=100cd/m². Rec.709 input uses its documented inverse signal transfer and an explicit80–300cd/m² reference-white policy (default100); this is not an implicit calibrated BT.1886 display transform. Both convert primaries into linear Rec.2020 before composition. The first managed reference slice uses zscale and explicit gbrpf32le throughout blending, exact right-angle source orientation and resize. The installed FFmpeg9.0.2 float32 blend/transpose paths execute with automatic format conversion disabled. Float32 padding fails that negotiation test and is not used. Full-canvas, matching oriented aspect, square-pixel video, trim/speed, nested tracks, opacity keys/fades and linear exposure are supported. Arbitrary clip spatial transforms, masks/chroma, titles/stills, SDR creative grades/LUTs and other animated effects fail explicitly. Full-frame resizing is linear-light, not an8-bit workaround.

Managed HDR10 uses libx265 Main10/yuv420p10le with explicit Rec.2020 primaries/nonconstant matrix, PQ transfer and limited range. All source AVFrame side data is removed before encoding, avoiding stale dynamic metadata, orientation or source-master signalling. Explicitly supplied mastering and content-light declarations are authored afresh; values are structurally checked, not claimed to be measured from the display or recomputed from arbitrary edited content. Unknown mastering stays absent; x265 may signal content-light zero/zero as unknown. Rational segment/video/audio sample budgets and120000Hz container timing are retained through final managed muxing. Independent drain, cancellation, source protection and atomic output replacement remain intact.

Monitoring is explicit: Composited/reference/review output is an8-bit Rec.709 Hable tone map from the same linear composition; HDR10 delivery remains10-bit PQ. The native PQ/scRGB path remains opt-in for its supported all-PQ subset, on an active HDR output. Native canvas dimensions now follow project aspect;16:9 dimensions are unchanged. A square-pixel-only input declaration can use native preview; other technical overrides, exposure and mixed spaces require managed reference monitoring. Native unsupported HDR never silently switches to SDR. Live-layer monitoring is redirected to the labelled managed compositor for managed projects. No calibrated HDR monitoring or WebView HDR surface is claimed.

The13 initial HDR tests plus the later explicit pixel-aspect/future-profile test cover independent PQ references, primary conversion, HDR colored patches, decoded precision/static signalling, linear mixing, source VFR holds,29.97 timing, orientation direction, unsupported gates, project roundtrip/cache identity and SDR monitor tags. A full139-test integration run passed before the final pixel-aspect declaration extension; final exact-head normal/offline CI is still required. Both actual PQ originals have unspecified SAR; bounded camera qualification explicitly declares square pixels and records that assumption, rather than claiming it is verified metadata. Initial fixture/SAR/metadata and syntax/test-rate failures remain in the QA history.

## HDR10+ preservation boundary and next authoring work

Probe preserves whitelisted stream/first-decoded-frame mastering, content-light and actual FFprobe-recognized ST2094-40 metadata with source PTS/coverage. First-frame absence does not prove absence later. It does not infer HDR10+ from filenames, device models or10-bit codecs. The private original bitstream remains the authoritative full metadata source. The project preserves a sample and original-bitstream association, **not a complete frame-indexed extracted metadata track**. Native decode-side retention is unchanged. HDR10+ output requests fail; no automatic downgrade is implemented.

Next implement a bounded/cancellable full frame/PTS metadata index and schema validation, identity-preserving trim/reorder/speed mapping and duplicate/hold semantics. Reuse is permitted only for validated picture-preserving cases. Scaling, transitions, exposure, compositing and grading require a standards-compliant regeneration/authoring policy tied to final pixels and target display; original creative-intent metadata is invalidated. x265's dhdr10-info interface can transport supplied metadata, but does not by itself provide validated authoring. Add decoded per-frame roundtrip/sequence-level validation and applicable licensing/toolchain review before exposing HDR10+ delivery.

## Technical references

- [ITU-R BT.2100-3](https://www.itu.int/dms_pubrec/itu-r/rec/bt/R-REC-BT.2100-3-202502-I!!PDF-E.pdf): transfer definitions, primaries and separation of signal/scene/display operations.
- [FFmpeg filter documentation](https://ffmpeg.org/ffmpeg-filters.html): explicit zscale/float formats, blend and tone-map interfaces; actual installed negotiation is tested separately.
- [Microsoft Advanced Color](https://learn.microsoft.com/en-us/windows/win32/direct3darticles/high-dynamic-range): FP16 scRGB and OS-managed presentation; scRGB1.0 represents80nits, distinct from the reference compositor's100nits unit.
- [x265 options](https://x265.readthedocs.io/en/latest/cli.html): static mastering/content-light units and supplied dynamic metadata transport. Encoder availability alone is not HDR acceptance.
