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

PQ decodes to absolute linear light normalized so1.0=100cd/m². Version1 treats Rec.709 input as display-referred ideal-black BT.1886 (gamma2.4), with an explicit80–300cd/m² white policy (default100), not as an inverse camera OETF or a calibrated display. This follows the pinned zimg display-referred transfer selection and is gated by an independent mid-gray reference; the initially mistaken inverse-OETF oracle is retained as a failed test. Scene-referred camera transforms require separate future profiles. Both inputs convert primaries into linear Rec.2020 before composition. The first managed reference slice uses zscale and explicit gbrpf32le throughout blending, exact right-angle source orientation and resize. The installed FFmpeg9.0.2 float32 blend/transpose paths execute with automatic format conversion disabled. Float32 padding fails that negotiation test and is not used. Full-canvas, matching oriented aspect, square-pixel video, trim/speed, nested tracks, opacity keys/fades and linear exposure are supported. Arbitrary clip spatial transforms, masks/chroma, titles/stills, SDR creative grades/LUTs and other animated effects fail explicitly. Full-frame resizing is linear-light, not an8-bit workaround.

Managed HDR10 uses libx265 Main10/yuv420p10le with explicit Rec.2020 primaries/nonconstant matrix, PQ transfer and limited range. All source AVFrame side data is removed before encoding, avoiding stale dynamic metadata, orientation or source-master signalling. Explicitly supplied mastering and content-light declarations are authored afresh; values are structurally checked, not claimed to be measured from the display or recomputed from arbitrary edited content. Unknown mastering stays absent; x265 may signal content-light zero/zero as unknown. Rational segment/video/audio sample budgets and120000Hz container timing are retained through final managed muxing. Independent drain, cancellation, source protection and atomic output replacement remain intact.

Monitoring is explicit: Composited/reference/review output is an8-bit Rec.709 Hable tone map from the same linear composition; HDR10 delivery remains10-bit PQ. The native PQ/scRGB path remains opt-in for its supported all-PQ subset, on an active HDR output. Native canvas dimensions now follow project aspect;16:9 dimensions are unchanged. A square-pixel-only input declaration can use native preview; other technical overrides, exposure and mixed spaces require managed reference monitoring. Native unsupported HDR never silently switches to SDR. Live-layer monitoring is redirected to the labelled managed compositor for managed projects. No calibrated HDR monitoring or WebView HDR surface is claimed.

The13 initial HDR tests plus the later explicit pixel-aspect/future-profile test cover independent PQ references, primary conversion, HDR colored patches, decoded precision/static signalling, linear mixing, source VFR holds,29.97 timing, orientation direction, unsupported gates, project roundtrip/cache identity and SDR monitor tags. A full139-test integration run passed before the final pixel-aspect declaration extension; final exact-head normal/offline CI is still required. Both actual PQ originals have unspecified SAR; bounded camera qualification explicitly declares square pixels and records that assumption, rather than claiming it is verified metadata. Initial fixture/SAR/metadata and syntax/test-rate failures remain in the QA history.

Final candidate refinements: all managed zscale stages now explicitly set agamma=0, disabling the backend's default approximate-gamma mode. The SDR BT.1886 mid-gray oracle, colored primaries, all right-angle source orientations, animated opacity and VFR2× speed pass independent decoded checks. A deterministic storage-publication fault also reproduced a UI rollback/recovery-draft inconsistency in Apply Color. The correction keeps the unsaved color edit, undo entry and recovery document aligned, matching ordinary editor save-failure behavior. Its four color-control tests pass. The local development MSI revision is3.5.1 to allow a genuine upgrade from the initial3.5.0 candidate; no new milestone, branch or stable release is created. Initial results remain bound to37d96da; final precision/installed receipts will be recorded separately.

## HDR10+ preservation boundary and next authoring work

Probe preserves whitelisted stream/first-decoded-frame mastering, content-light and actual FFprobe-recognized ST2094-40 metadata with source PTS/coverage. First-frame absence does not prove absence later. It does not infer HDR10+ from filenames, device models or10-bit codecs. The private original bitstream remains the authoritative full metadata source. The project preserves a sample and original-bitstream association, **not a complete frame-indexed extracted metadata track**. Native decode-side retention is unchanged. HDR10+ output requests fail; no automatic downgrade is implemented.

Next implement a bounded/cancellable full frame/PTS metadata index and schema validation, identity-preserving trim/reorder/speed mapping and duplicate/hold semantics. Reuse is permitted only for validated picture-preserving cases. Scaling, transitions, exposure, compositing and grading require a standards-compliant regeneration/authoring policy tied to final pixels and target display; original creative-intent metadata is invalidated. x265's dhdr10-info interface can transport supplied metadata, but does not by itself provide validated authoring. Add decoded per-frame roundtrip/sequence-level validation and applicable licensing/toolchain review before exposing HDR10+ delivery.

## Measured delivery results

Production and packaged source are frozen at3487af7; subsequent delivery edits are QA tests/evidence/documentation only. The initial37d96da cohort remains separate. [Sanitized measurements and immutable attempt outcomes](benchmarks/p0-color/qualification.json) include both, with exact source/host identity. Final local140/140offline tests(45.119s),26/26JavaScript and14focused HDR tests pass; exact-final-head normal/offline/compile/package CI receipts live in [draft PR #8](https://github.com/JakubSoltysiak/VlogCraft/pull/8).

| Verification | Measured result | Boundary |
|---|---|---|
|Reference10-bit ramp|868decoded luma codes; max2codes error;12frames|1024×32,24fps, Main10/yuv420p10le/PQ/2020; reference mastering10000nits/MaxCLL10000/MaxFALL1072 checked in actual decoded metadata.|
|Linear and mixed blends|551.712nits vs550expected|128×72, Rec.709/BT.1886 reference-white100nits and PQ input; actual8-bit H.264 SDR/10-bit PQ mixing also passes the final focused test; independent primary/mid-gray/colored-PQ checks also pass.|
|Native precision retained|877levels; PQ normalized error0.0001831; max125scRGB|Unchanged native runtime/offscreen generated precision; no calibrated monitor claim.|
|Installed monitor/delivery comparison|0.406684mean RGB levels/255|One PQ/exposure fixture, explicit SDR monitor transform after genuine HDR10 delivery; not every effect/profile.|
|Native actual-camera HDR|144000samples/0underruns/0skips|3s;960×1706composition/180×320physical; active HDR/FP16/scRGB presentation, sampled visibility held; decode-side dynamic data retained but not applied.|
|Actual-camera bounded HDR10|Both PQ originals:12frames,.2s video/audio endpoints|144×256/60; explicit square-pixel interpretation because source SAR is unspecified; unknown output mastering omitted.|
|Full-resolution HDR10|2160×3840/60,12decoded frames,.2s endpoints; SSIM0.980326|PQ-code-domain comparison against independently decoded/auto-oriented original.37.733s export, not realtime or long-form qualification.|
|Project/recovery|Exact80undo states, tracks/output color, source metadata, draft and paused restore|Both installed renderer/browser faults; input override UI and exposure undo/redo pass. Publication-fault consistency test reproduces before correction and passes afterward.|
|Installer|3.5.1 upgrade/uninstall/reinstall exit0; protected data and approved resources preserved|SHA25632feee1ea0b3a3155822e2ff44a55361d442d8ce085d709914bbde6eeb71b8f5; local development binary, no public redistribution/signing/stable release.|

The float32 CPU reference path is slow. Disabling approximate gamma intentionally chooses the accurate path; the initial16.453s and final37.733s/.2s UHD observations also differ in operating conditions, so they are not an isolated cost attribution. Neither score is hidden. Future optimization must preserve the independent image/metadata tests; encoded HDR relabelling or8-bit shortcuts are not an alternative. No12-bit preservation or native upload above P010 precision is qualified. HDR10's10000nit ceiling, gamut/clipping treatment and HDR/nits scopes still need operator tools and broader acceptance. Current scopes describe the SDR monitor image.

## Limited SDR preservation comparison

Frozen83e6afb baseline and the first P0 candidate use the same generated original4K sources,600s/7200clips, three video/three audio tracks,960×540composition,356×200physical surface, detached30s observation plus natural idle, no forcedGC/PDH/profiler. Both retain sampled visible focus/coverage and AC. Cache state is unmanaged and thermal throttling is not observable. These are one-run diagnostics, not new protected ten-run/endurance/physical-sync acceptance.

|Active interval metric|Frozen3.4.10|P0 candidate|
|---|---:|---:|
|Skipped sequence frames|14|25|
|Audio underruns|0|0|
|Mean interval ms|16.8191|16.9303|
|p95 / p99 upper bounds ms|25.0 /39.1|25.2 /37.8|
|Maximum active interval ms|66.9772|105.872|
|Aggregate WebView private commit at active end MiB|1944.785|1917.566|

The candidate's105.872ms outlier is retained. Single snapshots do not establish lower RAM or an active plateau; per-frame variance was not collected. Historical348/349cohorts, long stalls and657underruns remain unchanged. Final HDR-only gamma/save-failure refinements do not alter the native clock/SDR pixel compiler; source/installed consistency and the final-build export case are recorded separately.

|SDR UHD60 export cohort|Frozen median seconds|Candidate median seconds|Interpretation|
|---|---:|---:|---|
|Initial four runs, ABBA|6.4535|6.8890|+6.75%; investigation trigger retained.|
|Reversed four runs|4.3340|4.2308|−2.38%; initial slowdown not consistently reproduced.|
|Final3.5.1 paired run|5.1036|5.4873|+7.52%; throughput equivalence remains open.|

All180frames per export fully decode, SSIM0.997805, matching audio/video endpoints. Frozen/current FFmpeg/FFprobe/native binaries match; SDR video/audio commands and graphs are identical. Absolute timings and direction vary across cohorts. This narrows attribution but does not prove general performance preservation or explain host/scheduling variance. No provisional trigger was suppressed or converted into an automatic pass. No extra long benchmark loop is justified in this foundation delivery.

## Failure ledger, privacy and remaining gates

The public numeric ledger retains every completed local attempt. Initial fixture failures include missing SAR, missing actual frame color tags despite requested encoder tags, an unsupported10fps test timeline, the orientation string syntax error, and the wrong inverse-OETF gray oracle. Installer attempt1 used the old3.4MSI; it qualifies only that retained build. UI attempts omitted expanding a details control, initially polled an async predicate incorrectly, and compared an unnormalized fixture with the acknowledged canonical project. Exact compressed histories/metadata were already identical in that comparison; normalization was corrected before retesting. A hidden native-resolution control was selected before native mode showed it. The storage-publication test exposed a real new-feature consistency defect and retains its pre-fix failure; the subsequent cross-VM prototype assertion was corrected to compare serialized project data. All final required checks actually pass within the boundaries above; none of these attempts is silently excluded.

Originals remain read-only, ignored and outside all generated directories. Public results contain aliases/technical numbers only; complete metadata, private projects, screenshots/frames, source names/paths and hashes remain local. Final source hash/mtime/privacy and repository audits are recorded with delivery. No source-media size cap, history/cache reduction, active forcedGC, compact clock response, online API change or previous-PR merge is introduced.

The first explicit HDR10 slice is useful for controlled development verification, not a complete production finishing system. Remaining gates include slow HDR CPU throughput, variable SDR export timing, arbitrary HDR geometry/masks/LUTs/titles, full HDR10+ indexing/regeneration, HLG OOTF/Log transforms, calibrated external monitoring, high-bit-depth breadth/gamut/highlight scopes and the old playback/audio/memory failures. Next P0 work should optimize/extend the exact high-precision composition path and build the frame-indexed dynamic-metadata foundation with unchanged independent tests. The editor is not ready for the Kenya project.

## Technical references

- [ITU-R BT.2100-3](https://www.itu.int/dms_pubrec/itu-r/rec/bt/R-REC-BT.2100-3-202502-I!!PDF-E.pdf): transfer definitions, primaries and separation of signal/scene/display operations.
- [FFmpeg filter documentation](https://ffmpeg.org/ffmpeg-filters.html): explicit zscale/float formats, blend and tone-map interfaces; actual installed negotiation is tested separately.
- [Microsoft Advanced Color](https://learn.microsoft.com/en-us/windows/win32/direct3darticles/high-dynamic-range): FP16 scRGB and OS-managed presentation; scRGB1.0 represents80nits, distinct from the reference compositor's100nits unit.
- [x265 options](https://x265.readthedocs.io/en/latest/cli.html): static mastering/content-light units and supplied dynamic metadata transport. Encoder availability alone is not HDR acceptance.
- [zimg transfer selection](https://github.com/sekrit-twc/zimg/blob/master/src/zimg/colorspace/gamma.cpp): display-referred Rec.709 selects BT.1886, while its scene-referred option selects the inverse camera OETF. The installed path is verified numerically rather than assuming those curves are interchangeable.
