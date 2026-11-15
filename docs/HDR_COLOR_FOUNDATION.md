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
