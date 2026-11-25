# UHD60 HDR10+ encoder-input qualification

The real project cuts at picture 103. Its independently encoded second span contains pictures 103–599, with random-access pictures at 103 and 353. All 21 failures from the eight-worker export and all 19 failures from the two-worker export fall in this span. The earlier attempts and the indexed-seek measurements are preserved in the [indexed export report](phase3a-indexed-export.md).

## Encoder experiment

Arm A split the final managed filter output immediately before x265. One output fed the normal encoder while the other captured its uncompressed input. The GPU capture used the indexed decoder on the original 600-picture edit, including the preceding trim and cursor reuse. All replays started a fresh encoder at the original edit boundary and supplied the entire 497-picture span. Both GOPs retained their full temporal context.

| Arm | Quantized input | Encoder entry point |
|---|---|---|
| A | Managed float graph, zimg error diffusion | Original managed filter graph and encoder |
| B | Exact bytes captured in A | Native raw-video ingress and encoder |
| C | Original packed GPU planes | Managed labeled filter output and original encoder options |
| D | Same GPU planes as C | Native raw-video ingress and encoder |

The input layout was planar little-endian Y, U, V, with ten significant bits per 16-bit word. The 3840 × 2160 luma and two 1920 × 1080 chroma planes occupy 24,883,200 bytes per picture, without row padding. The delivery uses left-sited chroma, square pixels, limited range, BT.2020 nonconstant luminance, PQ and a 60/1 clock. Each output uses a 1/120000 container clock. All four arms used x265 4.3+45, Main10 Slow CRF 20, two pool workers, two frame threads, WPP, 25-picture lookahead, four B-frames, open GOP and a maximum key interval of 250. The original mastering-display and content-light declarations were retained. The saved 60 Mb/s field coexists with the verified CRF rate-control mode.

For private reproduction, run the following against the saved failed range, its pinned reference and the historical two-worker candidate. The worker must include resident decoding. The directory must be fresh. Raw captures, decoded pictures, source paths and original receipts stay on the workstation.

```powershell
python benchmarks/phase3a_encoder_matrix.py $range $privateFolder $worker $runtime $reference $twoWorkerCandidate --span 103 600
```

The diagnostic compares each quantized plane byte for byte, hashes each HEVC picture's coded slice data, records the packet clocks and independently decodes every picture. It parses actual slice types and QP deltas for the two different inputs. HDR10+ authoring inserts SEI after encoding. Excluding those messages from the coded-slice comparison permits a direct check against the archived authored masters.

All 497 coded pictures matched between A and B, and all 497 matched between C and D. A reproduced the archived managed span and C reproduced the archived native two-worker pipe output. The replay used file-backed raw inputs. The archived encode used the worker pipe. Substituting GPU input at fixed settings changed the B/P/I slice type on 92 of 497 pictures and the slice QP delta on 150. Picture 375 retained its B slice while its QP delta increased from four to five. Pictures 123 and 428 retained both their B slice and QP delta while their coded data changed. The packet comparison establishes input-sensitive encoder decisions. It does not identify a particular motion vector or coding-tree decision.

The two archived GPU captures used the same packed input at both pool sizes. Switching the pool from two to eight also changed the slice type on 94 of 600 pictures and the slice QP delta on 164. The matched two-worker case isolated the raw-input effect. All encoder settings other than the declared worker count and diagnostic log verbosity were held at the saved profile.

Exactly 408,489,022 of 6,183,475,200 ten-bit samples differed between the two raw inputs. Every difference was one code value. The affected fractions were 7.8663% of Y, 4.8450% of U and 3.3266% of V. Raw overall PSNR was 72.00 dB. Every plane in every picture had at least one difference. Under the fixed two-worker settings, A and D differed in all 497 independently decoded pictures. Both same-input pairs matched on 497/497 decoded pictures as well as on every coded-slice hash.

## Correction under qualification

For one fully opaque, neutral camera layer, the indexed D3D11 decoder can supply the visible P010 or NV12 planes directly. The worker verifies dimensions, format, color declarations, chroma location and source PTS. It excludes row and surface padding and retains the selected picture across repeated source timestamps. FFmpeg losslessly unpacks the planes, applies the reference linearization, orientation, bilinear fit, float canvas and final zimg error diffusion, then feeds the original two-worker x265 configuration. Opaque coverage eliminates the general per-pixel matte expression, alpha merge and background composition. Only decoded camera planes cross to the CPU. The normal renderer and the short GPU packed-picture path retain their original selection policies.

The packed shader uses ordered dither in independent tiles. zimg propagates rounding error from the previous pixel and the previous row. Matching the reference on the GPU would also require equivalent linearization, resize arithmetic, chroma filtering, clipping and rounding before the dependent quantizer. The experiment retains the working indexed decoder and uses the existing reference kernels for the neutral raster. [zimg error diffusion](https://github.com/sekrit-twc/zimg/blob/master/src/zimg/depth/x86/error_diffusion_avx2.cpp)

A six-picture isolation used the original timestamps at 103, 104, 123, 375, 428 and 599. Feeding the GPU's linear FP32 composition through the reference final zimg conversion still left 845,412–1,052,774 differing samples per UHD picture, with a maximum difference of two codes and 70.92–71.87 dB raw PSNR. This places part of the mismatch upstream of the final quantizer. Starting from the indexed decoder's coded camera planes and applying the neutral reference kernels matched **every byte on all six probes**. Applying only the final CPU dither to a full floating-point GPU readback would have increased transport without solving the observed mismatch.

The qualification recipe uses `--camera-raster` on `benchmarks/phase3a_camera_range.py`, together with the original project snapshot, saved range, matching reference hash and media identities. The candidate must pass the original 50 dB floor for every output picture, all source and packet timestamps, HDR10+ syntax/association, static HDR and PCM checks before publication. The archived minute also requires the full range to encode back to the same project document. Complete-section reference receipts cannot be applied to a different edit.

The existing repair mechanism replaces one complete independently encoded edit span, up to 16 pictures and one quarter of the sequence, after a matched reference comparison. The failed span contains 497 of 600 pictures. Its internal open-GOP random-access point does not establish an independent repair boundary. Repair admission and the staging-buffer budget retain their previous limits.

On the Radeon workstation a cancellation after the worker had begun writing real pictures stopped all four observed owned processes, removed all temporary render directories and left the destination absent. The source identities matched. The ordinary editor retains its managed fallback. A reference-pinned exact-raster laboratory trial records rejection directly so a failed diagnostic does not launch a redundant full reference render.

## Physical delivery

| 600-picture export | Delivery | Additional independent comparison | Minimum / overall decoded PSNR | Pictures below 50 dB |
|---|---:|---:|---|---:|
| Managed reference, Slow CRF 20 | 870.989 s | Reference | Baseline | — |
| Packed GPU, eight workers | 231.874 s | 25.348 s | 48.07 / 53.93 dB | 21 |
| Packed GPU, two workers | 362.456 s | 25.591 s | 48.09 / 54.15 dB | 19 |
| Indexed camera + zimg, two workers | 688.461 s | 24.671 s | Identical on all 600 | 0 |

The corrected delivery saved 182.528 s (21.0%) against the managed reference. Both faster packed exports failed. The complete independent check brought the corrected time to 713.132 s. All 600 coded pictures, independently decoded pixels, source selections, packet PTS and dynamic metadata records matched the reference. The static mastering and light declarations, square-pixel Main10 limited Rec.2020/PQ and 480,000-sample/channel stereo endpoint passed, with matching decoded PCM.

The indexed decoder selected from 705 decoded pictures in 0.832 s, plus 0.017 s seeking. This route executes zero GPU composition or PQ shader dispatches. Visible source planes totaled 14,929,920,000 bytes. Median hardware readback took 8.145 ms and the blocked pipe write took 891.864 ms. Feeding and draining both raster/encoder processes took 563.671 s. x265 logged 1.02 and 1.08 fps for the two spans, 1.069 fps combined including input waits. HDR10+ analysis, insertion and verification took 15.287 s. First-export delivery checks took 107.799 s. Peak native working set was 364.0 MiB, sampled local GPU usage 361.3 MiB and sampled aggregate process-tree working set 4.322 GiB. Workstation benchmarks ran serially on AC. [Stage measurements for each attempt](benchmarks/studio-3.6.0-camera-raster.json)
