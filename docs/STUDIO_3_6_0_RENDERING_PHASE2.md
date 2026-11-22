# VlogCraft Studio 3.6.0 native rendering investigation

Phase 2 is stacked on draft PR #15 at `045da0a6b3d8d956d07c075a6c0e73f6878a2d9f`. The archived [Phase 1 controls](STUDIO_3_6_0_RENDERING.md) and the installed build remain the production reference.

The lab feeds the same premultiplied display-linear Rec.2020 pictures to frozen FFmpeg filters, single-thread scalar C++, eight-worker SIMD C++, and D3D11 compute. The native paths use the same inverse geometry, bilinear taps, layer order, feathered shapes and centered-dissolve composition. The GPU experiment uses float32 sources and separately checks float32 and float16 output targets. No production engine selection has changed.

The small mask and dissolve controls compiled and ran on Radeon 890M. An initial FFmpeg run rejected the raw input because the filter did not receive its alpha association declaration. The corrected lab tags input as premultiplied and checks the results against the frozen filters. Full-size trials use qualified AC power and retain numerical rejections as well as successful comparisons.

The first UHD geometry comparison found isolated hard-edge differences of 0.504 linear units for scalar/SIMD and 0.148 for D3D11 FP32. Low average error did not qualify the outputs. Both native paths now receive per-row coverage intervals computed in double precision from the source transform. Interior taps and alpha operations still use float32. Hardware and WARP passed the small masked and dissolve checks with this change. The measured UHD retries are reported separately.

## Frozen export reruns

| Workload | Archived Phase 1 on battery | Fresh Phase 1 on AC |
|---|---:|---:|
| 360p spatial, 48 pictures | 7.703 s | 6.469 s |
| 720p spatial, 120 pictures | 47.406 s | 58.781 s |
| UHD opacity, 24 pictures | 65.671 s | 73.000 s |
| UHD spatial, 24 pictures | 98.468 s | 148.922 s |
| UHD spatial, 48 pictures | 170.671 s | 177.750 s |

These are separate conditions and one new observation per workload. All fresh outputs retained the exact picture counts, 48 kHz audio endpoints and per-picture ST 2094-40 validation. The opacity rerun initially received a split command-line argument and stopped before rendering. The corrected invocation uses the identical archived source. Its benchmark driver printed the current repository head after the branch moved, so the report separately identifies the actual extracted Phase 1 source.

## Experimental export

The lab can export its mixed layer fixture using D3D11 output, the existing serial zimg PQ conversion, CPU x265 Main10, the existing decode-clock normalization and HDR10+ authoring. It compares scene-linear samples and decoded PQ, checks exact PCM and metadata association, and publishes a verified file inside its local result directory. A rejected or unavailable native path selects the verified FFmpeg reference. An automated forced-unavailable case exercises that path. The initial export smoke found a packet-clock difference after direct x265 muxing. The test passed after applying the existing final clock and audio mux contract.

## Benchmark scope

The full-size cases use generated deterministic linear ramps, highlights and soft coverage. The FFmpeg comparator imports the archived filter source after verifying it against the exact Git revision. It opens planar controls and uses the frozen transform, mask, matte and linear blend operations. Its throughput includes process launch, raw input and a null encoder sink. Native throughput times warmed in-process work and GPU completion, with source preparation, initial upload and setup measured separately. Scene-linear quality capture is separate from the timed arms. The export test includes source-buffer loading, download, disk transfer, planar packing, encoding, clock normalization and HDR10+ authoring. Its independent A/B comparison is timed separately.

Picture acceptance requires maximum RGB error at most 0.05, RGB RMSE at most 0.002 and maximum alpha error at most 0.003, with 1.0 representing 100 nits. The test also tracks relative highlight and absolute shadow errors, mean edge alpha error and linear PSNR. The independent encoded comparison requires at least 50 dB PQ code-value PSNR with exact clocks and PCM. A failure remains recorded even when subsequent runs pass.

The native program reuses its CPU worker pool, source textures, coverage buffer, output UAV and optional readback surface. GPU timestamps are reported only when the D3D11 disjoint query returns valid timing. DXGI local and non-local figures describe usage segments on a unified-memory adapter, and they can overlap with system working-set figures. WPR was blocked by system policy in Phase 1. The investigation uses D3D11 timestamps, memory samples and process CPU time. OS-reported CPU frequency is available, while GPU frequency and calibrated thermal measurements remain unavailable. [D3D11 timestamps](https://learn.microsoft.com/en-us/windows/win32/api/d3d11/ne-d3d11-d3d11_query) · [DXGI memory accounting](https://learn.microsoft.com/en-us/windows/win32/api/dxgi1_4/nf-dxgi1_4-idxgiadapter3-queryvideomemoryinfo).
