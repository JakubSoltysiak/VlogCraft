# VlogCraft Studio 3.6.0 rendering performance

Phase 1 starts at draft PR #14 head `05f74e7095d77b46b80f0530ab9293871dbace14`. The [3.5.7 qualification](STUDIO_3_5_7_HDR_EDITING.md) and its installer are the frozen baseline. This stacked branch targets render throughput with the same scene, frame clock, image precision and delivery profiles. It leaves native preview optimization to a later checkpoint.

| Archived 3.5.7 workload | Result |
|---|---:|
| 360p60, 48 frames, spatial photo animation | 21.609 s |
| 720p60, 120 frames, spatial photo animation | Timed out at 190.109 s |
| UHD60, 24 frames, photo opacity animation | 144.765 s, including 4.656 s for HDR10+ authoring |

The matched runs use the same synthetic sources, codec and output geometry. Process timing and filter ablations are collected separately from end-to-end acceptance. Abbreviated graphs are diagnostic workloads. Full verification covers decoded video and PCM, picture count, timestamps and HDR10+ metadata.

## Root-cause isolation

The frozen source completed a fresh 120-frame 720p test in 158.859 s and the 24-frame UHD opacity control in 137.125 s. The earlier 720p timeout remains a recorded outcome. The fresh frozen workloads ran serially on the Ryzen AI 9 HX 370, with the same FFmpeg 9.0.2 binary and generated source parameters. The UHD results JSON obtained its Git label from the outer checkout after the documentation checkpoint. The Python source itself was imported from the frozen archive of `05f74e7`.

| Diagnostic | Frames | Wall | FFmpeg CPU | Sampled peak RSS |
|---|---:|---:|---:|---:|
| 720p final scene, normal x265 | 10 | 27.922 s | 27.422 s | 641 MiB |
| 720p, same graph, no encoder | 10 | 27.813 s | 27.172 s | 591 MiB |
| 720p, geometry ablated, no encoder | 10 | 5.922 s | 5.625 s | 584 MiB |
| 720p, same graph, four filter slices, no encoder | 10 | 9.031 s | 32.063 s | 615 MiB |
| UHD opacity final scene, normal x265 | 6 | 40.078 s | 39.907 s | 5,014 MiB |
| UHD opacity, same graph, no encoder | 6 | 39.969 s | 38.656 s | 4,587 MiB |
| UHD opacity, matte ablated, no encoder | 6 | 6.625 s | 6.343 s | 4,109 MiB |
| UHD opacity, same graph, four filter slices, no encoder | 6 | 13.843 s | 46.985 s | 4,806 MiB |

These ablations change pixels and serve only to attribute cost. The graph-only and normal-encoding times overlap most work. The launch-to-exit startup control took 0.079 s. Individual input probes took 0.047–0.109 s, the short decode controls 0.078–0.219 s, and Python graph construction 0.031–0.078 s. Process I/O samples and the final deliverables are small on these synthetic inputs. The cause of the main wall-time bottleneck is repeated single-threaded evaluation of pixel expressions in the float graph. Geometry recomputed scale and rotation expressions for every sample of all four planes, and still/title mattes reread RGB and alpha across repeated pictures. Float buffers account for a large working set even with the matte ablated. Two initial profiling attempts failed before processing because of an FFmpeg interval syntax error. Both were retained and retried.

FFmpeg's float `geq` loop evaluates its expression per pixel and creates separate expression state for each filter slice. This makes row-invariant motion terms and bounded slice parallelism testable without changing the raster mapping. [FFmpeg geq implementation](https://ffmpeg.org/doxygen/8.0/vf__geq_8c_source.html) · [Windows Performance Recorder profiles](https://learn.microsoft.com/en-us/windows-hardware/test/wpt/built-in-recording-profiles)

## Renderer checkpoint

The managed graph schedules at most four filter slices. The affine sampler evaluates its y-coordinate and animated coefficients at the first pixel of each slice row, then preserves the original inverse mapping and bilinear sample. Integer-coordinate matte and mask reads access the requested sample directly. Static still geometry, mask and grade run once before holding the prepared frame. The compositor copies its RGB and alpha planes directly to the existing float merge, avoiding intermediate grayscale RGB planes. Source decoding, CPU x265 settings and the audio render path are unchanged.

An exploratory whole-graph slice change finished 720p in 36.093 s and UHD opacity in 46.500 s. Independent comparison caught changed decoded samples, although PCM remained exact. This attempt is unqualified. The updated graph keeps each zimg conversion/resample/dither at the reference single slice. The first affected control matches decoded frame/PCM hashes, timestamps and full dynamic metadata at every picture, with 48 frames at 640 × 360 completing in 7.781 s versus 18.500 s on the fresh baseline.

The follow-up prepares RGB once for a still with only fading or opacity keys and evaluates the animated coverage on one float32 plane. Against the preceding corrected graph, the 24-frame UHD opacity control changed from 69.578 s / 134.516 sampled CPU-s / 4.67 GiB to 65.671 s / 120.141 sampled CPU-s / 4.42 GiB. Decoded pictures, audio, timestamps and frame-associated HDR10+ are identical to the frozen 3.5.7 reference. The new plane split also passed an animated-opacity test with a rotated, masked, partially transparent photo and a bright PQ background.

## Matched rendering controls

All durations cover the CPU x265 Main10 render and edited HDR10+ authoring. Generation and independent verification are outside the timed window. Canvas and source sizes match for each row. Tests ran serially using the same inputs, filter quality, output frame rate, and FFmpeg build on the workstation. The machine was on battery at the sampled checks. Table entries use one fresh run per arm and preserve the archived timeout separately. Larger real-camera projects can create more disk and memory pressure than the highly compressible fixture.

| Workload | Frozen 3.5.7 | Phase 1 | Phase 1 output FPS | Peak summed RSS, baseline → Phase 1 |
|---|---:|---:|---:|---:|
| 640 × 360 spatial, 48 frames | 18.500 s | 7.703 s | 6.231 | 279.6 → 266.4 MiB |
| 1280 × 720 spatial, 120 frames | 158.859 s, archived timeout at 190.109 s | 47.406 s | 2.531 | 852.3 → 771.6 MiB |
| 3840 × 2160 opacity, 24 frames | 137.125 s | 65.671 s | 0.365 | 5.16 → 4.42 GiB |
| 3840 × 2160 spatial, 24 frames | Timed out at 250.344 s in scene 7 of 7 | 98.468 s | 0.244 | No complete baseline → 4.68 GiB |

The first three rows match frozen decoded pictures, PCM, clocks and ST 2094-40 records at every presentation timestamp. The spatial UHD baseline left 18 pictures across six completed scenes. Their video, PCM and clocks are exact against the optimized scene files. The optimized final six pictures also match the preceding corrected renderer. The complete optimized 24-picture result passed independent HDR metadata association and static/HDR10+ decode equality, with the 19,200-sample 48 kHz audio endpoint. The baseline timeout left no owned processes alive.

Sampled average CPU usage across 24 logical processors rose from 4.4% to 10.1% on 720p and from 4.5% to 7.6% on the UHD opacity control. Sampled CPU work still fell from 167.9 to 114.8 CPU-s and from 148.0 to 120.1 CPU-s, respectively. Spatial UHD used 247.0 CPU-s. Scratch peaks ranged from 273,444 B to 607,065 B in the four optimized cases. Summed working sets can count shared pages more than once. The exact stage, memory, and scratch measurements are retained in the [sanitized record](benchmarks/studio-3.6.0-rendering.json).

## Remaining cost and installed checks

On a two-picture optimized UHD boundary at the same source size, the full graph without encoding took 7.875 s. Removing the final PQ transfer/quantization reduced that to 6.719 s. Replacing dissolve arithmetic with a pass of one input while keeping both source graphs reduced it to 6.844 s. The ablations overlap and change output, so their differences cannot be summed. Same-input demux and decode took 0.094 s and 0.203 s. Decoding and converting two source pictures to float linear took 1.860 s. A still decode, its float conversion and the fit-to-UHD diagnostic each completed in 0.093–0.156 s. Those figures include FFmpeg launch overhead. Per-allocation call stacks are unavailable. Float buffers exceeded 4 GiB RSS even during the boundary ablations.

The optimized UHD opacity route spent 59.984 s on static rendering and 5.687 s in HDR10+ authoring. In the latter stage, decoded picture analysis took approximately 5.14 s, HEVC metadata insertion/remux 0.25 s, and final packet/clock verification 0.22 s. The render remains a CPU workload. Offloading encoding alone cannot remove its main cost.

The longer 48-picture UHD spatial sequence completed in 170.671 s, including 10.625 s for HDR10+ authoring. It independently passed all 48 metadata associations, exact static/dynamic decoded picture and audio equality, the 38,400-sample endpoint and source integrity. Measured throughput was 0.281 output FPS with 5.21 GiB peak summed working set and 428.9 sampled CPU-s. The full 60-second mixed export was deferred because the observed throughput remains impractical for it. The next rendering checkpoint should target the remaining per-pixel spatial sampler and full-size float surface passes, then compare on longer, higher-entropy fixtures.

The development MSI was built in 116.890 s. Windows upgraded from 3.5.7, uninstalled and reinstalled the candidate with exit code zero each time and preserved seven protected files. All 44 bundle checks passed, including the packaged source, installed native tools and approved icon. The installed 3.6.0 UI labels and executable version matched. In offline conditions, the installed 18-picture mixed HDR project passed visual, frame-specific HDR10+, undo/redo and reopen checks. An installed six-picture UHD control passed static HDR10, Samsung HDR10+ and YouTube HDR10 in 11.8, 13.1 and 11.2 s respectively with correct audio/video endpoints. The Samsung and static HDR10 pictures and PCM matched. The previous export-folder preference was restored byte-for-byte. Local tests passed 166 Python and 29 JavaScript cases.

## Encoder and GPU diagnostics

Ten fixed, already-composited UHD PQ pictures took 14.500 s to produce and write as 248,832,000 B of raw 10-bit input. A first CPU diagnostic omitted frame color declarations and failed authoring validation. The retained retry applies identical frame-level range, primaries, matrix and PQ declarations to both encoders and reuses the raw pictures. Their compression controls differ and their PSNRs describe this low-entropy fixture.

| Encoder | Wall | CPU time | Peak process RSS | Raw-reference PSNR | Frame metadata |
|---|---:|---:|---:|---:|---|
| libx265 ultrafast CRF 15 | 1.547 s | 1.828 CPU-s | 1,126 MiB | 63.14 dB | Main10 PQ, static mastering/CLL, authored HDR10+ |
| AMD AMF quality CQP 20 | 0.500 s | 0.532 CPU-s | 342 MiB | 66.05 dB | Main10 PQ, authored HDR10+, static mastering/CLL absent |

Both outputs preserved all ten picture timestamps. The authoring stage attached ten fresh ST 2094-40 records and the two independent decoded hashes before and after each remux matched. This raw-input diagnostic is video-only. Audio and synchronization were separately verified in the full mixed workload and the installed presets. The missing static declarations and limited image/codec coverage keep hardware HDR10+ outside production. CPU Main10 remains the delivery route.

In an auxiliary 120-frame loop of the same raw pictures with a null mux, CPU encoding took 9.704 s and AMF took 1.641 s. Windows PDH saw 5.18 MiB dedicated and 151.63 MiB shared GPU memory during the AMF arm. Nine samples returned zero-valued engine activity, so they do not establish a reliable engine-utilization percentage. WPR could not start the CPU, GPU and disk trace under the available Windows policy (`0xc5585011`). The raw probe retained the failed start log locally. A two-picture float ellipse-mask diagnostic took 6.938 s versus 0.234 s for its unmasked control. The remaining per-pixel mask work and float allocation pressure warrant separate optimization.

## Installed preview baseline

Each native test used three original 4K60 tracks mixed to a 960 × 540 program, a 356 × 200 physical monitor and three audio tracks. The visible condition held and all four trials reached 480,000 samples with zero audio underruns. Native runtime binaries matched across all 11 packaged files. The original candidate anomaly remains in the table. Most of its skips followed source waits. The repeated pair did not reproduce the anomaly. These short trials do not establish a cause or sustained performance.

| Native 10-second trial | 3.5.7 skips / maximum active Present gap | 3.6.0 skips / maximum active Present gap |
|---|---:|---:|
| First pair | 2 / 39.3 ms | 32 / 197.2 ms |
| Repeat | 3 / 50.1 ms | 2 / 42.6 ms |

Native median completed-generation seek was 370.8 → 364.6 ms and approximate p95 was 614.5 → 631.8 ms. Native sampled peak summed RSS was 2,653–2,754 MiB on 3.5.7 and 2,651–2,653 MiB on 3.6.0. The Live Layers idle pilots showed 181 and 219 browser callbacks with 30 and 0 dropped frames, and 1,234 and 1,208 MiB peak WebView working set. The first frozen proxy pilot had no sampled overlap and remains unqualified. Both retries used the same 60-second generated background proxy source and observed work in all 13 samples. They logged 207 and 217 callbacks, 0 drops in both, and maximum gaps of 516.9 and 166.8 ms. The candidate's original short proxy pilot logged 19 drops with one overlapping sample. These short browser observations do not qualify a long-session memory plateau or sustained playback. The proxy trials sample browser callbacks and source resolution. They do not measure physical scanout.

## Cross-editor comparison

Adobe documents GPU acceleration for effects, resize and color conversion, and describes hardware decoding and encoding separately. These are comparisons to measure on the same input, output and effects. The workstation currently has no local Premiere Pro installation for an equivalent trace. [Mercury Playback Engine](https://helpx.adobe.com/premiere/desktop/get-started/technical-requirements/enable-mercury-playback-engine-gpu-accelerated-renderer.html) · [Hardware encoding and decoding](https://helpx.adobe.com/in/premiere/desktop/get-started/technical-requirements/hardware-accelerated-decoding-and-encoding.html)

The existing D3D11 engine is a preview transport with a bounded float16 surface ring. The admission checks route boundary transitions, masks, and technical exposure to the managed compositor. A GPU-resident export path needs measured format/transfer parity and equivalent coverage for those operations before it can replace any stage of managed export.
