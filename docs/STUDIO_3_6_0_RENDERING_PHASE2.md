# VlogCraft Studio 3.6.0 native rendering investigation

Phase 2 is stacked on draft PR #15 at `045da0a6b3d8d956d07c075a6c0e73f6878a2d9f`. The archived [Phase 1 controls](STUDIO_3_6_0_RENDERING.md) and the installed build remain the production reference.

The lab feeds the same premultiplied display-linear Rec.2020 pictures to frozen FFmpeg filters, single-thread scalar C++, eight-worker SIMD C++, and D3D11 compute. The native paths use the same inverse geometry, bilinear taps, layer order, feathered shapes and centered-dissolve composition. The GPU experiment uses float32 sources and separately checks float32 and float16 output targets. No production engine selection has changed.

The small mask and dissolve controls compiled and ran on Radeon 890M. An initial FFmpeg run rejected the raw input because the filter did not receive its alpha association declaration. The corrected lab tags input as premultiplied and checks the results against the frozen filters. Full-size trials use qualified AC power and retain numerical rejections as well as successful comparisons.
