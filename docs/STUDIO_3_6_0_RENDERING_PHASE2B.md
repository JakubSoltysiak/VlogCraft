# VlogCraft Studio 3.6.0 Phase 2B HDR delivery

The frozen comparator is Phase 2 at `ef829c1c6c97c9915140dd16b81efd9ec8482b46`. Its 600-picture UHD60 fixture delivered in 474.519 s and generated 600 HDR10+ records with the exact 480,000-sample audio endpoint. The resident compositor processed 3,600 pictures at 134.31 FPS. [Frozen Phase 2 results](STUDIO_3_6_0_RENDERING_PHASE2.md).

## Fresh pipeline profile

A fresh AC run regenerated the identical two tagged HEVC source loops, checked their hashes, used the same 24 output frames and composed the same dissolve, motion, opacity and mask. It independently compared the isolated encoder's decoded pictures with the stored verified piped master. All picture hashes and BT.2020/PQ limited-range declarations matched.

| Stage | Fresh wall time |
|---|---:|
| Source creation, decode and normalization into the texture bank | 3.925 s |
| Native load, upload, composition, planar readback and diagnostic file write | 3.692 s |
| Frozen single-thread zimg PQ and error diffusion with raw I/O | 12.390 s |
| Isolated x265 Main10 with tagged raw input and video mux | 1.739 s |

The zimg filter's median and p99 were 513.489 ms and 536.116 ms per frame. Prior matched pipe delivery at 24 pictures took 20.229 s, with 4.763 s of HDR10+ analysis and authoring. Diagnostic file I/O and the product pipe use different paths. The stage measurements and pipelined wall are reported separately. The prototype targets parallel conversion at the same pixel contract and compact GPU readback before considering hardware encode.

## Matched 24-picture UHD60 qualification

| Conversion | Delivery wall | Output FPS | Peak summed working set | Independent decoded comparison |
|---|---:|---:|---:|---|
| Frozen single-thread zimg | 19.460 s | 1.233 | 4,137 MiB | Exact match to archived Phase 2 |
| Three persistent zimg workers | 12.588 s | 1.907 | 4,742 MiB | Exact picture, PCM and clock |
| D3D11 FP32 to packed Main10 | 8.126 s | 2.953 | 3,065 MiB | 57.71 dB PQ PSNR, exact PCM and clock |

Workers process whole frames with the unchanged error-diffusion filter. The bounded relay allows one picture per worker and releases converted pictures in order. The packed D3D11 route uses ST 2084 at 100 cd/m² per linear unit, BT.2020 non-constant-luminance matrixing, left-sited 4:2:0, limited range and ordered dithering. It reads back 24,883,200 bytes per UHD picture, one quarter of the former planar float payload. x265 and HDR10+ authoring remain common.

The WARP swatch/edge test compared the raw packed GPU output with zimg to within two luma and one chroma codes, and exercised black, shadow and peak codes. The separate eight-frame, 320 × 180 WARP encoded comparison reached 49.47 dB average, below the existing 50 dB acceptance threshold. That trial published no master. Lossy-encoder sensitivity with different dithering remains a qualification issue alongside the passing UHD measurement.
