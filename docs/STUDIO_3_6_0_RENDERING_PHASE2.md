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

To reproduce the kernels, extract `045da0a` with `git archive` under ignored build storage and provide that directory to `--reference`. The lab can build its own executable from the pinned Zig compiler used by the Windows native job.

```powershell
python benchmarks/render_phase2.py build/qa/phase2-repeat --reference build/qa/phase2-reference --compiler $zig --require-ac --precise-edges --cases uhd-geometry,uhd-mask,uhd-mixed --frames 4 --repeat 3 --transfers
python benchmarks/render_phase2_export.py build/qa/phase2-export --reference build/qa/phase2-reference --executable build/qa/phase2-repeat/VlogCraftRenderLab.exe --precise-edges --frames 4
```

## Core kernel results on AC

Each throughput entry is the median of three runs. FFmpeg throughput includes launch and warm-up. Native throughput starts after loading sources and warming the compositor. These rates describe raster work. Output encoding and physical preview presentation are outside the timing.

| Core case | FFmpeg FPS | Scalar C++ FPS | 8-worker SSE2 FPS | D3D11 FP32 FPS | D3D11 FP16 FPS |
|---|---:|---:|---:|---:|---:|
| 1080p transform | 0.891 | 24.55 | 249.43 | 1026.25 | 1049.10 |
| UHD geometry | 0.121 | 2.80 | 24.56 | 207.86 | 253.01 |
| UHD animated mask | 0.062 | 2.20 | 17.25 | 208.22 | 219.87 |
| UHD mixed layers | 0.060 | 1.72 | 14.63 | 138.94 | 173.54 |
| UHD HDR composition and dissolve | 0.093 | 2.10 | 19.74 | 145.41 | 165.40 |

Every corrected core mode passed against independently captured frozen reference pictures. GPU FP32 maximum linear RGB error was 0.00208 across the core cases. On the UHD mixed case it was 0.00180 with RMSE 0.00000342. FP16 reached 0.00835 maximum across the core cases. Native preparation retains float32 source pixels in both GPU tests. FP16 changes the output surface format. SIMD and scalar are compared independently in the [sanitized measurement record](benchmarks/studio-3.6.0-phase2.json).

| Additional case | FFmpeg FPS | Scalar C++ FPS | 8-worker SSE2 FPS | D3D11 FP32 FPS | D3D11 FP16 FPS |
|---|---:|---:|---:|---:|---:|
| UHD single layer | 1.123 | 6.13 | 66.62 | 284.34 | 297.96 |
| UHD three layers | 0.518 | 2.07 | 26.87 | 133.07 | 154.57 |
| UHD animated photo | 0.177 | 5.64 | 53.86 | 311.55 | 345.67 |
| UHD animated opacity | 0.726 | 2.73 | 37.55 | 195.83 | 217.49 |
| UHD dissolve | 0.377 | 3.41 | 41.79 | 177.25 | 213.45 |
| UHD 120 fps compatibility | 0.182 | 5.39 | 42.82 | 270.23 | 341.54 |

The six corrected cases also passed scene-linear picture comparison. The 120 fps result exercises the shorter source clock on a prepared buffer. It carries no 120 fps playback or encoding qualification.

For the UHD mixed case, median trial peak working set was approximately 6.08 GiB for FFmpeg, 513 MiB for SIMD and 1.15 GiB for D3D11 FP32 including its initial uploads. Median within-trial p99 was 83.5 ms for SIMD and 7.36 ms for resident FP32. A separate FP32 capture took 12.04 ms median for final readback and 82.86 ms for writing each raw frame. Forcing all sources to upload again took 152.75 ms per frame and increased DXGI local usage from roughly 1,030 to 2,566 MiB. That control shows why moving compositing to the GPU only pays end to end if the pipeline keeps sources and intermediate surfaces resident.

## Architecture decision

Advance a hybrid path with D3D11 FP32 for eligible linear compositing and the qualified FFmpeg/libav color, clock and delivery stages. The bounded export uses this decision now. SIMD is valuable as a CPU alternative for later profiling. The approved fallback remains FFmpeg. The larger error of the FP16 output is unnecessary for the first HDR integration despite its higher resident throughput. Camera streams, edit-state changes and production cancellation must be qualified through a streaming integration before enabling experimental selection in the editor.

The first four-picture UHD HDR export pair took 85.585 s in the FFmpeg branch and 6.960 s through the GPU branch. The raw-composition portions were 80.803 and 1.362 s, with subsequent HDR10+ authoring at 1.155 and 1.189 s. Both retained four independent metadata associations and the exact 3,200-sample audio endpoint. Static mastering and content-light declarations and decoded PCM matched. Decoded 10-bit PQ PSNR was 60.79 dB. Both branches use CPU x265 from the same normalized inputs. This fixture has no full production timeline decode or live playback.

The recovered repeats were 139.076 s versus 11.743 s with AC observed at both ends, and 128.968 s versus 10.039 s with AC at start and battery at finish. Both passed the same decoded checks. The mixed-power repeat is retained outside the primary AC comparison. The camera attempts also remain recorded. One lacked declared transfer and primaries and the other was rejected because AC power was disconnected.

The next integration should connect decoder surfaces to the compositor with bounded reusable GPU resources. The direct output pipe below removes raw disk staging from laboratory delivery. Keep the full 60-second encoded mixed-media gate separate from the resident kernel test. Production throughput and preview reliability require changing decoded camera frames and a representative timeline.

The D3D11 FP32 endurance run processed 3,600 UHD pictures from reused sources in 26.803 s, or 134.31 kernel FPS. Per-frame p99 was 15.02 ms and the largest sample was 21.40 ms. DXGI local usage stayed at about 903 MiB in the observed samples. Post-warm-up process working set moved from about 932 to 948 MiB. The 60 seconds describe the fixture at 60 fps. This is a 27-second kernel and ownership observation with no temporal decode, readback, mux, or presentation.

The two-frame 8K compatibility control ran three times. Median rates were 1.36 FPS scalar, 14.73 FPS SIMD, 74.97 FPS FP32 and 96.67 FPS FP16. SIMD matched the scalar result exactly. FP32 and FP16 maximum RGB errors against scalar were 0.00613 and 0.01192. This control omits the FFmpeg arm, export and presentation. The supervised cancellation case stopped an active native lab process tree at its six-second deadline. Windows Job Object cleanup reported zero owned survivors and zero unrelated processes targeted.

## Recovered delivery evidence

Local loopback regression passed 166 Python tests and 29 JavaScript tests. The Phase 2 development MSI administrative image passed 44 bundle checks. Its SHA-256 is `f5106de11516c09651bfe0fdb6168b2f57d260753c0007d6817a34659f5784aa`. The previous Phase 1 MSI retained its recorded hash. The lab remains separate from the packaged editor. Hosted Windows regression, native and WARP checks, and MSI lifecycle passed on the recovered code checkpoint. [Windows Actions](https://github.com/JakubSoltysiak/VlogCraft/actions/runs/44972846213).

## Direct readback-to-encoder pipe

The standalone FP32 renderer now converts the mapped D3D11 staging surface directly to one reusable planar float output, then writes it to a bounded operating-system pipe. x265 consumes it through the verified serial zimg/Main10 path. The pipe removes the previously staged RGBA sequence and the unpacking step in Python. Source textures, the staging texture and the planar buffer are reused. The GPU completion and staging barriers remain explicit. On encoder failure or timeout, the launcher closes and joins both children before returning. Output only moves into place after the same clock, PCM and HDR10+ checks.

For the progressive workload the fixture encodes and decodes two tagged three-picture SDR and PQ loops once. The compositor advances those cached pictures under animated geometry, opacity and a mask, then exercises a timed dissolve and stereo delivery. This fixture tests a changing picture and a real x265/HDR10+ pipeline. It keeps source loops resident and does not exercise live decoder scheduling or arbitrary user projects.

### Matched AC trials and quality

| UHD trial | Packed disk delivery | Direct pipe delivery | Decoded comparison |
|---|---:|---:|---|
| Four pictures, repeat 1 | 4.990 s | 4.376 s | Exact picture and PCM |
| Four pictures, repeat 2 | 5.114 s | 4.506 s | Exact picture and PCM |
| Four pictures, repeat 3 | 5.031 s | 4.582 s | Exact picture and PCM |
| Four-picture median | 5.031 s | 4.506 s | Exact in each repeat |
| 24 pictures with changing SDR/PQ | 22.645 s | 20.229 s | Exact picture and PCM |

The four-picture median dropped by 10.4%, and the changing 24-picture trial dropped by 10.7%. The packed comparator includes GPU readback, a raw RGBA file and planar packing. Both routes use the same FFmpeg/zimg and x265 settings. Static HDR declarations matched for each pair, and each file independently passed clock and per-picture dynamic metadata checks. All one-second power observations in these pairs recorded AC. Delivery includes rendering/encoding, clock normalization, muxing and HDR10+ authoring. Input preparation and independent verification are timed separately.

The qualifying camera retry used a tagged PQ snapshot on AC and compared against the independently captured frozen FFmpeg picture. The maximum RGB errors were 0.002160 for scalar and SIMD, 0.001795 for FP32 and 0.007583 for FP16. All passed the same acceptance limits. The tested original's before and after hashes matched. The two earlier attempts remain in the record. WARP exact-disk controls also passed, with the first harness error and corrected retry retained.

The two deliberate UHD pipe deadlines expired while the encoder and producer were supervised. Both exited with the expected timeout, left zero owned members for supervisor cleanup, and published no verified master. Real D3D11 device removal and repeated long-running device recreation remain untested.
