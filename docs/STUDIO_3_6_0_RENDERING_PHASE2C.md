# VlogCraft Studio 3.6.0 Phase 2C

The verified Phase 2B starting commit is `899ad995fc6ffd013e1eac2c25339459887fedc6`. The prepared 600-frame UHD60 HDR10+ export finished in 157.253 s, with 112.27 s attributed to authoring. [Phase 2B evidence](STUDIO_3_6_0_RENDERING_PHASE2B.md).

## Authoring profile on AC

The profile uses 120 encoded UHD pictures from the generated Phase 2B control. A setup encode removes the earlier dynamic metadata and supplies one identical tagged Main10 intermediate to all authoring arms. Setup is excluded from the measurement.

| Operation | Wall |
|---|---:|
| HEVC decode to null | 0.704 s |
| HEVC decode and PQ RGB16 reconstruction to null | 1.070 s |
| Decode, reconstruct and drain the original Windows pipe | 19.789 s |
| Frozen statistics and payload serialization during authoring | 5.306 s |
| Prepare HEVC fragments | 0.091 s |
| Insert per-picture SEI | 0.095 s |
| Remux | 0.113 s |
| Verify all packets | 0.269 s |
| Complete frozen authoring | 27.107 s |

Null and pipe probes are independent arms. Decode and reconstruction overlap transport. Python statistics and serialization consumed 5.313 host CPU seconds. The timed author used 33.77 sampled process-tree CPU seconds and reached 1,140 MiB peak summed working set. It transferred about 5.54 GiB of raw reconstructed data across the pipe. The large difference between reconstruction-to-null and the drained pipe identifies transfer and buffering as the first target.

## Exact authoring optimization

The experimental path opens a 1 MiB anonymous Windows pipe. The native pass calculates the exact 65,536-bin MaxRGB histogram and three unsigned 16-bit channel maxima using SSE2. Four reusable histogram shards reduce contention in frequently populated bins. The existing PQ lookup, rank policy, rounding and serialization are shared. Up to three workers in the measured route consume complete decoded frames in order. Per-picture payload authority remains the final decoded and quantized Main10 encode.

| 120-frame matched authoring | Wall | Peak summed working set | Final master |
|---|---:|---:|---|
| Frozen | 27.107 s | 1,140 MiB | Reference |
| Large pipe, NumPy statistics | 9.771 s | 1,133 MiB | Byte-identical |
| Large pipe, native statistics, one worker | 4.590 s | 1,135 MiB | Byte-identical |
| Large pipe, native statistics, three workers | 3.820 s | 1,137 MiB | Byte-identical |

The first comparison invocation used the same name for the final output and the fragment transport and stopped in remux. The corrected invocation uses a distinct destination and retained the failed receipt. The standalone statistics check independently compares complete serialized metadata for six controls with random values, ties, end-range codes, moving highlights, strided input and an incomplete SIMD block.

The saved-project export tool exposes explicit fast authoring. Its qualified default still uses the original decoder and NumPy statistics. Failure of the experimental author closes its scratch job and retries the same encoded intermediate through the reference author. The verified final master uses the existing atomic publication path.

```powershell
python benchmarks/profile_phase2c_author.py generated-120.mp4 build/qa/profile120 --frames 120
python benchmarks/compare_phase2c_author.py build/qa/profile120 build/qa/author120 --library $statisticsDll --mode pipe --mode native1 --mode native3
```

## Prepared-source UHD60 delivery

| Pictures | Phase 2B delivery | Phase 2C delivery | Phase 2C authoring | Phase 2C output FPS |
|---:|---:|---:|---:|---:|
| 24 | 8.126 s | 6.780 s median | 1.219 s median | 3.540 |
| 120 | 33.758 s | 16.012 s | 3.878 s | 7.494 |
| 300 | 79.281 s | 32.911 s | 8.893 s | 9.115 |
| 600 | 157.253 s | 61.121 s | 17.351 s | 9.817 |

The three 24-picture runs delivered in 6.156, 6.780 and 7.609 s. Every complete master matched the corresponding archived Phase 2B master byte for byte, including its encoded pictures, PCM, static HDR, clocks and frame-associated dynamic metadata. The 600-picture arm used 3.94 GiB peak summed working set with the same 480,000-sample audio endpoint. It delivered 2.57 times as fast. These times use the unchanged delivery timer and exclude the additional independent post-delivery check.

## Resident D3D11 source input

The experimental worker attaches libav's D3D11VA decoder to the compositor's own device. It validates the original time base and each decoded presentation timestamp against the separately probed index. Changes in selected picture update their existing FP32 source slot. A compute pass samples the NV12 or P010 planes directly, applies the tested display-referred SDR/PQ interpretation and performs fit and right-angle orientation. It leaves the original surfaces resident. An event query protects their lifetime before reuse. The authored metadata is still derived from the final decoded x265 encode. [DXGI planar formats](https://learn.microsoft.com/en-us/windows/win32/api/dxgiformat/ne-dxgiformat-dxgi_format) · [zimg transfer functions](https://github.com/sekrit-twc/zimg/blob/master/src/zimg/colorspace/gamma.cpp).

| Matched live UHD60, 24 pictures | Software input | Resident input | Resident decoded PQ PSNR | Peak summed working set, software → resident |
|---|---:|---:|---:|---:|
| H.264 SDR VFR and generated HEVC PQ | 39.398 s | 5.628 s | 57.95 dB | 7,785 → 2,197 MiB |
| H.264 SDR VFR and rotated private HEVC PQ | 26.563 s | 5.398 s | 55.34 dB | 6,827 → 2,095 MiB |

Both resident arms verified timestamps, static HDR, 24 dynamic records and exact 19,200-sample audio endpoints against the independent masters. The generated route decoded 23 SDR and 27 PQ pictures and selected 19 and 24 respectively. The VFR holds use the previously selected picture when the next original PTS is later than the requested picture. Resident source video incurred zero CPU frame transfers. One generated overlay still uploads once and the output remains a packed readback to CPU x265.

Separate 24-picture null probes distinguish initialization and decode from the rest of the input route. H.264 demux took 0.057 s, software decode 0.089 s and D3D11 decode 0.243 s. The private HEVC arm took 0.054, 1.691 and 0.415 s respectively. Both D3D11 null paths explicitly reported a resident pixel format. The short H.264 arm demonstrates the hardware setup cost. The large end-to-end gain comes from resident normalization and avoiding bulk host frame movement as well as decode.

The first small resident encode reached 49.61 dB and failed the established 50 dB gate. The UHD candidate continued to use the same gate. Early software comparison attempts lacked the shared runtime DLL path, and one native camera run logged a libav message before its JSON receipt. The corrected path validates the native receipt and preserves the DLL environment for the software retry. WARP exercised this fallback and produced exact decoded output. A production-quality failure prevents candidate publication.

GPU statistics computed on the pre-encode surface would describe a different image. A matched 24-picture diagnostic reconstructed the packed pre-encode pictures using the same PQ RGB path. All 24 resulting payloads differed from their compressed and decoded counterparts. The qualified metadata authority remains the final decoded image. GPU analysis on that decoded image still needs exact reconstruction and histogram conformance.

The 120-picture progression used changing H.264 SDR and the same rotated PQ source. Its software-normalized, zimg-output reference completed in 116.931 s and the resident input plus packed GPU-output candidate completed in 15.549 s at 7.718 output FPS. The arms shared the optimized author. This comparison includes the output conversion change. Decoded PQ PSNR was 56.22 dB, PCM was exact, static signaling matched and all 120 dynamic records tracked the original output clock. The endpoint was 96,000 samples. Peak summed working set moved from 8,410 to 2,897 MiB. Both original PTS traces were validated, with zero CPU video-source frame transfers in the resident arm.

## Representative saved-project gate

The retained 24-picture UHD60 project reopened as an ordinary saved document. It used two video tracks, changing H.264 SDR VFR and rotated private HEVC PQ, two dissolve boundaries, an animated photograph, an ellipse mask, a title, camera crossfade and mixed music. The private PQ source's pixel aspect ratio was undeclared. The project explicitly assumed square pixels for that clip using the existing technical override. Both initial preflight rejections are retained. No media files were rewritten.

The managed project rendered one shared HDR10 intermediate in 112.039 s with 7,087 MiB peak summed working set, seven parallel color segments and zero segment fallbacks. The default author took 5.940 s and the exact native author took 1.214 s. This yields 117.980 and 113.253 s respectively with the shared render time. The final authored masters were byte-identical. Independent decode recovered 24 picture timestamps, 24 metadata associations and an exact 19,200-sample audio endpoint. Source and project hashes matched before and after.

Project composition now accounts for about 99% of the faster saved-project result. A linear projection of this short fixture would take about 4.7 hours for 3,600 pictures. The 60-second project gate stays open. The 120-frame live laboratory result and the prepared 600-frame result exercise different workloads, and the representative project still uses the managed compositor. Its next performance gate is safe resident admission for real project effects and timelines.

## Qualification scope

| Capability | Status | Evidence and remaining coverage |
|---|---|---|
| Managed default FFmpeg/x265 export | Production reference | Current default and packet verification preserved. |
| Fast author on final decoded Main10 pictures | Qualified experimental subset | Exact delivery through 600 prepared frames and the saved UHD project. The explicit project tool retains the reference fallback. |
| Resident NV12/P010 decode and source normalization | Qualified experimental subset | Two-stream UHD and rotated PQ VFR through 120 frames on Radeon 890M. Requires an independent master gate. WARP exercised runtime fallback. |
| GPU source handling for wider formats or timelines | Unqualified | Wider chroma, interlaced material, other transfer functions, arbitrary seek and full project admission need separate verification. |
| Final decoded GPU histogram, physical driver recovery and native preview parity | Open | Pre-encode metadata was rejected. Refactored authoring preserved Reference preview in the saved-project regression. Physical device loss and actual display parity remain open. |

Injected authoring failure retried through the qualified default and matched decoded output. The simulated disk-space preflight preserved the saved project and published no master. The WARP no-hardware case fell back with exact output and no owned survivor. Phase 2C uses the same CPU x265 encoder. The earlier AMF mastering-coordinate discrepancy remains open.

## Windows verification and evidence integrity

The local offline suite passed 169 Python and 29 JavaScript tests. The development MSI was built from the isolated `c1bea606dc47def930698ebdd641e3fb869b71ff` archive. The administrative image and all 44 package/source/resource checks passed. The first package comparison used the Windows working checkout and found line-ending differences in seven web files. Comparing to the exact archive used for packaging resolved those mismatches. The development MSI SHA-256 is `cdaa000247f7d77bd1b5ee023951d274912cfbb7b69c9e496ae5284b83587f44`.

The current default author repeated the 120-picture frozen-input control in 28.161 s and produced a byte-identical master. The packaged editor also passed the normal offline HDR10+ export dialog with 12 generated pictures. Independent decoding verified the picture/audio clock and every picture's statistics. The saved project output settings stayed intact and the supervised session left no owned processes.

GitHub Actions initially rejected the earlier production performance fingerprint after the authoring refactor. The earlier record is now verified against the immutable Phase 2B tree, where its source and protocol fingerprints match. The current record is separately bound to the Phase 2C source and updated protocol. Both checks are required. The private-media audit found zero path, content or private text matches in Git and confirmed all three camera originals unchanged. [Retained fingerprint failure](https://github.com/JakubSoltysiak/VlogCraft/actions/runs/45049471631).
