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

The WARP and Radeon swatch/edge tests compared the raw packed GPU output with zimg to within two luma and one chroma codes, and exercised black, shadow and peak codes. The separate eight-frame, 320 × 180 WARP encoded comparison reached 49.47 dB average, below the existing 50 dB acceptance threshold. That trial published no master. Lossy-encoder sensitivity with different dithering remains a qualification issue alongside the passing UHD measurement.

The primary transfer and matrix definitions are ITU-T H.273. Left-sited 4:2:0 uses horizontal 1:2:1 and vertical 1:3:3:1 bilinear weights, checked against the independently run FFmpeg/zimg graph. The shader clips to legal Main10 levels. Its swatch and edge suite includes saturated colors, ramps down to shadow levels, black and the 10,000 cd/m² PQ endpoint. [ITU-T H.273](https://www.itu.int/rec/T-REC-H.273-202309-I/en) · [zimg implementation](https://github.com/sekrit-twc/zimg).

## Progressive UHD60 delivery

| Frames | Frozen Phase 2 | CPU workers | Packed GPU | GPU output FPS | GPU decoded PQ PSNR |
|---:|---:|---:|---:|---:|---:|
| 24 | 20.229 s | 12.588 s | 8.126 s | 2.953 | 57.71 dB |
| 120 | 90.842 s | 62.863 s | 33.758 s | 3.555 | 57.48 dB |
| 300 | 228.495 s | Unmeasured | 79.281 s | 3.784 | 57.43 dB |
| 600 | 474.519 s | Unmeasured | 157.253 s | 3.816 | 57.38 dB |

All four Radeon GPU deliveries passed the existing 50 dB decoded PQ gate against the corresponding frozen output, with exact PCM and matching format declarations. The 600-picture candidate verified 600 HDR10+ associations and exactly 480,000 audio samples. It delivered in 33% of the previous wall time, with 3.94 GiB peak summed working set and DXGI local usage near 1.93 GiB after warm-up. At pictures 300 and 600 the sampled compositor working set differed by less than 1 MiB. The unified-memory adapter's local usage can overlap system working-set accounting.

At 600 pictures, median compositor time was 7.572 ms, PQ shader time 2.201 ms and copy/map time 3.354 ms, versus 14.274 ms for Phase 2's float readback. These measurements overlap. Composition, transfer and x265 completed in 44.542 s, and HDR10+ authoring took 112.27 s. The 71% authoring share identifies the next bottleneck on warm prepared textures. The 600-picture result projects about 15.7 minutes for a 3,600-picture repetition of the same loops. A representative 60-second project requires distinct decoded frames and stronger coverage.

Reproduce the fresh control or candidate with the same worker, frame count and verified master. Set `--conversion reference`, `parallel` or `gpu`. For isolated conversion, the same `video_command` graph can be wrapped in FFmpeg `bench=start` and `bench=stop`, writing temporary planar Main10 frames and feeding them into `packed_encoder` with explicit HDR tags. Compare independent frame hashes before interpreting timing.

```powershell
python benchmarks/render_phase2_stream.py build/qa/phase2b-reference --executable $worker --loops --frames 24
python benchmarks/render_phase2_stream.py build/qa/phase2b-gpu --executable $worker --loops --frames 24 --conversion gpu --compare-master build/qa/phase2b-reference/verified-hdr10plus.mp4
python benchmarks/check_phase2b_color.py --executable $worker --backend warp32
```

## Live decoder and saved-project export

The experimental live route opens two actual source decoders. The first decoded presentation timestamp is the origin for each rational source in-point. A disk-independent timestamp probe supplies the selection clock, and FFmpeg's decoded timestamp trace is independently checked against it. Only a new selected picture replaces its texture slot. Variable gaps hold the last eligible source picture and the lab rejects ambiguous or incomplete timestamp ranges. The test uses H.264 SDR VFR, HEVC Main10 PQ, differing coded sizes, a changing mask, dissolve, an animated overlay and a mix from both audio sources. Decoding and normalization use software FFmpeg, followed by a bounded block stream into D3D11. Hardware decoder surfaces are outside this path.

The first native live intake streamed through C++ standard input. Its 24-picture reference took 151.123 s, and the packed GPU pilot took 147.54 s. The native process spent over 100 CPU seconds in the initial trial while the two decoders and encoder frequently waited. The revised Windows path reads staged slots using bounded `ReadFile` blocks. The two paths are measured separately.

The explicit saved-project tool `benchmarks/phase2b_project_export.py` connects the exact CPU workers to the editor's managed HDR video graph. It reads a validated primary project and retains its source timing, all supported effects, audio and HDR10+ authoring. The three-worker mode explicitly replaces only the recognized terminal color stage. Unsupported commands and single-picture segments run through FFmpeg's existing route. A converter error closes the worker group and retries the segment with that same renderer. A verified master is published atomically to a new path. Its first tested scene used two video layers, a masked animated photograph, audio, and a 29.97 fps project. Decoded picture and PCM matched across reference, parallel and injected-fallback runs. The independent probe saw six exact output timestamps and six HDR10+ records. A before/after SDR Reference preview produced identical decoded output. The installed native preview and its audio clock are outside this test.

```powershell
python benchmarks/phase2b_project_export.py project.json new-hdr10plus.mp4 --backend parallel --workers 3
```

## Failure coverage

The injected D3D11 removal HRESULT interrupted a live WARP export after two pictures. Neither the partial candidate nor any owned child survived. A separate 120-picture active deadline expired in the conversion relay with the same cleanup result. An earlier eight-picture deadline control finished within its deadline and is retained. The project regression verifies reference retry on an injected worker failure and refuses an existing destination or a missing media file. Physical Radeon device reset, driver resource exhaustion and installed-app shutdown during the experimental route remain open.
