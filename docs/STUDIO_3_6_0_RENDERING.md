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

Adobe documents GPU acceleration for effects, resize and color conversion, and describes hardware decoding and encoding separately. These are comparisons to measure on the same input, output and effects. The workstation currently has no local Premiere Pro installation for an equivalent trace. [Mercury Playback Engine](https://helpx.adobe.com/premiere/desktop/get-started/technical-requirements/enable-mercury-playback-engine-gpu-accelerated-renderer.html) · [Hardware encoding and decoding](https://helpx.adobe.com/in/premiere/desktop/get-started/technical-requirements/hardware-accelerated-decoding-and-encoding.html)
