# Indexed camera export and HDR segment qualification

## Upstream implementation review

The following revisions were inspected on 25 November 2026. VlogCraft uses its existing FFmpeg, D3D11, x265 and HDR10+ implementation. No upstream implementation files were incorporated.

| Upstream source | Mechanism inspected | Application to VlogCraft |
|---|---|---|
| OpenReel `7591221d483b45e98694b02662e66bc1fb33994a`, MIT | The scanner examines packet structure, source cadence and GOPs. The smart-render planner distinguishes untouched and altered regions and declines incompatible parameters. The desktop source guard verifies source content and rechecks the planned keyframe. | Use the container index as a candidate, inspect actual NAL types, then confirm the packet and decoded PTS at the destination. We render and reauthor edited HDR pictures. OpenReel's AVC/HEVC smart-copy path excludes HDR and 10-bit sources. Its 10-bit intra ProRes exception is SDR. [Scan](https://github.com/Augani/openreel-video/blob/7591221d483b45e98694b02662e66bc1fb33994a/packages/core/src/export/smart-render-scan.ts) · [Plan](https://github.com/Augani/openreel-video/blob/7591221d483b45e98694b02662e66bc1fb33994a/packages/core/src/export/smart-render.ts) · [Source guard](https://github.com/Augani/openreel-video/blob/7591221d483b45e98694b02662e66bc1fb33994a/apps/desktop/src/main/sidecar/source-guard.ts) · [Smart render scope](https://github.com/Augani/openreel-video/blob/7591221d483b45e98694b02662e66bc1fb33994a/apps/desktop/SMART_RENDER.md) |
| OpenReel, same revision | Its GPU reader leases a finite set of staging buffers, copies into them and maps asynchronously. The native backend receives ordered readback tickets and handles cancellation. The reader's I420/8-bit conversion differs from the native HDR plane path. | A possible D3D11 adaptation would retain the existing packed 10-bit shader, assign a completion query and sequence number per staging buffer, and write the oldest completed slot to x265. A full ring blocks the producer. A fault retires the device and invalidates the partial segment. [GPU reader](https://github.com/Augani/openreel-video/blob/7591221d483b45e98694b02662e66bc1fb33994a/packages/core/src/video/gpu-frame-readback.ts) · [Native backend](https://github.com/Augani/openreel-video/blob/7591221d483b45e98694b02662e66bc1fb33994a/apps/web/src/services/native-ffmpeg-backend.ts) |
| OpenReel, same revision | Clip-edge half-open segments are independent of worker count. History-dependent effects protect a region. The orchestrator uses a snapshot, bounded worker admission and cancellation. The sidecar checks exact tiling and actual frame counts, uses closed GOPs and joins one audio track. Its parallel path declines HDR/10-bit delivery. | The assembly trial uses VlogCraft's authored frame boundaries, validates every segment independently, uses one continuous audio track and verifies complete packet timing. A future parallel encoder needs separate Main10/PQ, static metadata, GOP, seam and resource qualification. [Planner](https://github.com/Augani/openreel-video/blob/7591221d483b45e98694b02662e66bc1fb33994a/packages/core/src/export/segment-plan.ts) · [Orchestrator](https://github.com/Augani/openreel-video/blob/7591221d483b45e98694b02662e66bc1fb33994a/apps/web/src/services/export-queue/parallel-segment-export.ts) · [Session](https://github.com/Augani/openreel-video/blob/7591221d483b45e98694b02662e66bc1fb33994a/apps/desktop/src/main/sidecar/segment-session.ts) · [GOP and mux arguments](https://github.com/Augani/openreel-video/blob/7591221d483b45e98694b02662e66bc1fb33994a/apps/desktop/src/main/sidecar/smart-export.ts) · [Scope](https://github.com/Augani/openreel-video/blob/7591221d483b45e98694b02662e66bc1fb33994a/apps/desktop/PARALLEL_EXPORT.md) |
| FilmCraft `2d1d1b6920cf14c166e1b2bc73ba8208def150c9`, MIT/Apache-2.0 | Converts a tick range to integer frame bounds, caps its Rayon pool and bounds render batches. The registry separates frame preparation, ordered encode and flush. Its offscreen renderer reports device capability/failure and accepts a subset of render plans with a CPU fallback. | Retain managed fallback and separate final encode ownership from GPU composition. Future worker admission must budget x265 threads, decoder surfaces and staging memory together. The RGBA8 shortcut cannot carry our final PQ 10-bit planes. [Export runner](https://github.com/storytold/filmcraft/blob/2d1d1b6920cf14c166e1b2bc73ba8208def150c9/crates/export/src/run.rs) · [Renderer](https://github.com/storytold/filmcraft/blob/2d1d1b6920cf14c166e1b2bc73ba8208def150c9/crates/gpu/src/export_renderer.rs) · [Registry](https://github.com/storytold/filmcraft/blob/2d1d1b6920cf14c166e1b2bc73ba8208def150c9/crates/export/src/registry.rs) |

OpenShot's frame caching and keyframe-oriented seek, MLT's producer and continuous encoder, Kdenlive's supervised temporary jobs, and FreeCut's file-backed sink informed the decoder and recovery decisions. Their exact revisions, files, license references and limitations are in the [source review and recovery report](export-upstream-recovery.md).

## Segmented HDR design

Use the original immutable frame plan and exact rational output clock. Admit a split only at an independent authored picture boundary. Keep overlapping transitions, temporal effects and their source handles in the same dependency span. A still may be held on the GPU only after source orientation, color conversion, alpha and geometry agree with the managed picture. Freeze codec configuration, dimensions, time base, chroma location, mastering and content-light declarations across spans. Require a closed independently decodable first picture. Round absolute endpoints when converting to the concat demuxer's microseconds. Render and encode the full audio graph once to preserve compression state, sample endpoints and AAC priming.

Start with one worker. Additional workers require measured headroom for decoder surfaces, staging buffers, encoder threads and scratch. Verify every segment's picture count and timestamps, including first/last decoded pictures against the independently rendered edit. Join without recompression only if parameters match. Author or independently validate ST 2094-40 on the final presentation clock, then validate decoded PCM, packet timing and the 50 dB floor before atomic publication. Invalidate assets and checkpoints on any recipe or source-identity change. Process recovery and the proposed reusable segment receipt are specified in the [recovery report](export-upstream-recovery.md).

The assembly experiment accepts an already encoded, independently verified reference minute. It splits it at the actual timeline spans, reopens and decodes each part, remuxes them in order with the one original AAC stream, and compares every compressed packet hash, PTS, DTS, duration, codec configuration and presentation endpoint against the original. This isolates assembly integrity from the separate question of picture quality after independent x265 encodes.

## Reproduction on the Windows workstation

Use an untouched v4 saved-project snapshot with the audited output settings. The camera-range tool requires local source files, a resident project worker built from this revision, its matching FFmpeg shared DLLs and the qualified HDR statistics DLL. Every output directory below must be fresh. The public application keeps its existing short first-export admission. The longer CLI trials use a separate qualification workspace.

```powershell
python benchmarks/phase3a_indexed_seek.py $synthetic $worker $runtime
python benchmarks/phase3a_camera_range.py $minute $short --frames 0 120 --worker $worker --runtime $runtime --author-dll $statistics --parallel-x265
python benchmarks/phase3a_camera_range.py $minute $upright --frames 2314 2362 --worker $worker --runtime $runtime --author-dll $statistics --parallel-x265
python benchmarks/phase3a_camera_range.py $minute $longer --frames 0 600 --worker $worker --runtime $runtime --author-dll $statistics --parallel-x265
python benchmarks/phase3a_segment_assembly.py $minute $verifiedMinuteMaster $assembly
```

Run the commands serially. The legacy decoder control uses `--linear-preroll`. Omitting `--parallel-x265` retains two x265 pool workers. The saved Slow preset, CRF, frame threads, verification criteria and AAC graph remain the same. To reuse an oracle from an independent prior run, supply its receipt directory, the original source identity receipt and the previously recorded SHA-256 using the [camera-range instructions](phase3a-camera-range.md). Only use independent references matching the exact project, range, configuration and source identities.

## Indexed source clock

For avc1/H.264 and hvc1/HEVC MP4-family streams the planner checks individual length-prefixed NALs inside sync samples. It separates presentation order from decode order, retains the original stream ticks and format start, and rejects damaged, duplicate or ambiguous packet clocks. An HEVC CRA can precede pictures in decoding order that display before it. A trim needing one of those pictures must start at an earlier usable access point. On fresh seek, the worker verifies the selected packet's PTS, DTS, byte position and key status, then checks hardware output against the indexed presentation clock. Returned leading pictures must be independently decodable RADL entries from that access point. H.264 requires an IDR. Ineligible or failed attempts can use the managed fallback.

The decoder only seeks on a fresh context. Neighboring monotonic trims of the same stream continue on the live cursor, preserving delayed pictures in order. Separate normalization slots preserve each clip's geometry. For distant trims with multiple intervening random-access opportunities, a fresh context avoids carrying delayed output across the seek. Playback retains its existing device and handoff policy.

The first live-reseek attempt stopped when the decoder emitted original picture 4,610 after requesting the later IDR at 4,668. The worker rejected this unexpected picture. The attempt and managed fallback took 213.273 s. A worker-only reproduction returned the same unexpected PTS. The corrected trial started at IDR 4,468 (PTS 9,016,784, DTS 8,993,599 in the 1/90,000 source clock) and decoded forward through both trims. The byte-for-byte output hashes of the corrected 48- and 120-picture MP4s matched the previous eight-worker masters.

## Physical measurements, Radeon 890M

All workstation exports ran serially on AC power. The real inputs and output clocks are from the pinned saved project. The full 21m47s job was never restarted. Results use UHD60, HEVC Main10 Rec.2020/PQ, static mastering metadata, per-picture HDR10+, x265 Slow CRF 20 and the original audio mix. Times in the native column include preparation, render, AAC, HDR authoring and the runtime delivery check. The independent all-picture comparison is additional.

| Range | Managed reference | Previous native | Indexed native | Additional comparison | Minimum / overall PSNR | Result |
|---|---:|---:|---:|---:|---:|---|
| 48 upright SDR pictures, 8 workers | 105.123 s | 51.573 s | 41.879 s | 3.880 s | 53.65 / 54.59 dB | Pass, 48 picture records and exactly 38,400 samples/channel |
| 120 rotated PQ pictures across a cut, 8 workers | 190.193 s | 110.166 s | 71.333 s | 5.627 s | 52.62 / 56.36 dB | Pass, 120 picture records and exactly 96,000 samples/channel |
| 600 rotated PQ pictures across the same cut, 8 workers | 870.989 s | — | 231.874 s | 25.348 s | **48.07 / 53.93 dB** | Fail, 21 pictures below 50 dB |
| Same 600 pictures, 2 workers | Same pinned master | — | 362.456 s | 25.591 s | **48.09 / 54.15 dB** | Fail, 19 pictures below 50 dB |

The upright source decoded 48 pictures in both cases (0.071 s previously, 0.061 s indexed). Its output begins at the start of the source. Its wall-time difference includes run-to-run variation and a change to packet-based preparation. The 120-picture rotated cut went from 9,303 decoded pictures in 48.842 s to 225 in 0.531 s plus 0.023 s seeking. Of these 225, the first trim consumed 142, the second 83 on the existing cursor. Its complete delivery took 35.2% less time than the previous eight-worker path. The sampled delivery checks alone took 41.479 s of the corrected run.

For 600 pictures, the native path decoded 705 source pictures (0.958 s at eight workers and 0.840 s at two). A separate raw comparison rendered all 600 again with both VSD2 prefix decoding and VSD3 indexing. Prefix decoding consumed 9,783 source pictures. All 600 packed Main10 input frames delivered to x265 had identical SHA-256 frame hashes and packet clocks. The original source-identity checks passed. Both encodes maintained correct source selection, video PTS, static HDR, all 600 dynamic picture records and identical stereo PCM through sample 480,000.

### Why these packed exports failed the 600-picture gate

The sampled checks passed at frames 0, 51, 102, 103, 351 and 599. The complete comparison caught discrepancies elsewhere. An independent diagnosis decoded the exact source PTS for each of three failing pictures, rendered them through the managed float graph, and compared the native packed output before encoding, the managed encode, and both native encodes. Scores are in PQ code-value PSNR.

| Frame | Raw GPU vs managed raw | Managed encode vs managed raw | 8-worker encode vs GPU raw | 8-worker vs managed encode | 2-worker vs managed encode |
|---:|---:|---:|---:|---:|---:|
| 123 | 72.69 | 48.48 | 48.50 | 49.23 | 49.25 |
| 375 | 71.69 | 49.27 | 49.08 | 48.07 | 48.09 |
| 428 | 71.26 | 48.17 | 48.26 | 48.16 | 48.29 |

For these pictures the large divergence appears after separate lossy encodes. The smaller raw conversion differences merit investigation as potential inputs to different x265 decisions. Returning to two workers did not restore the all-picture gate. An isolated generated test also exercised closed H.264 IDR and open-GOP HEVC CRA with B-frames, variable picture spacing and a 2 s stream start. Both formats produced 36 byte-identical packed pictures and exact selection ticks for 32 decoded source pictures versus 152 with the prefix decoder. The first generated fixture lacked the requested transfer tags and was rejected; the rerun set explicit frame color properties.

At this checkpoint the native 3,600-picture first export was gated on a passing 600-picture comparison. The subsequent [encoder-input investigation](phase3a-camera-raster.md) qualified a corrected 600-picture raster. The camera qualification tool keeps longer outputs private until the full comparison and source checks pass. The ordinary first-export cap remains 120 pictures. The managed renderer remains available. A practical next experiment is to feed x265 the same verified sequence of reference-quantized Main10 pictures, compare encoder input and output per frame, and qualify a conservative native/managed segment choice before retrying 600. Preserve the observed quality failures in that comparison.

### GPU transfer and memory

| Trial | Compositor GPU | PQ shader GPU | PQ copy GPU | Copy through Map, wall | Mapped pipe write, wall | Encoder feed and wait, total | Native worker peak RSS | Peak local GPU usage |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| SDR 48, 8 workers | 4.122 ms | 2.342 ms | 0.647 ms | 3.380 ms | 3.152 ms | 23.942 s | 462 MiB | 422 MiB |
| PQ 120, 8 workers | 4.240 ms | 2.459 ms | 0.689 ms | 3.847 ms | 20.157 ms | 24.519 s | 763 MiB | 774 MiB |
| PQ 600, 8 workers | 4.236 ms | 2.470 ms | 0.704 ms | 3.875 ms | 144.831 ms | 126.543 s | 764 MiB | 774 MiB |
| PQ 600, 2 workers | 4.259 ms | 2.502 ms | 0.680 ms | 3.795 ms | 306.906 ms | 267.982 s | 765 MiB | 775 MiB |

Per-picture columns are medians. D3D11 timestamps bracket the packed buffer copy in a valid disjoint-query interval. The Map wall interval includes earlier queued work. Pipe write time includes backpressure and the encoder interval overlaps rendering. The source path reported zero CPU source-frame transfers. The full qualification process trees peaked at approximately 2.81, 3.83, 5.69 and 3.81 GiB of summed sampled working sets, respectively, including the independent checks and any fresh reference render. Shared pages may appear in multiple working sets.

The direct pipe remains the single-span control. The existing bounded relay enforces multi-span encoder boundaries. A three-slot ring would add about 47.5 MiB for two extra UHD staging buffers. The measured copy and map times are small relative to encoding and validation; no ring or parallel encoder was enabled.

### Assembly and recovery

The audited reference minute split at frames 103, 667, 752, 1502 and 2314. The six segments started with random-access packets. Split and join took 0.469 s. Packet verification and fresh independent decoding of the source and all six isolated segments took 244.505 s. All 3,600 decoded pictures matched, including every boundary. HEVC and AAC packet payloads, PTS, DTS, duration, codec configurations and endpoints matched. This measures a lossless join of existing Main10/HDR10+ segments. Independently re-encoded segments still require all-picture comparison against the same edit, and concurrent workers have no measured admission budget.

New editor jobs have durable, atomically written snapshots and owner receipts. A real abrupt process exit, owner PID reuse, inaccessible owners, a concurrent terminal write, and a worker launch failure are covered. The earlier external supervisor's receipt and private media remain intact. Automatic reuse of segment files requires the separate verified content/configuration manifests described in the [recovery design](export-upstream-recovery.md).

A final upright publication regression ran the updated qualification entry point. Its 48-picture candidate published after a passing all-picture comparison (38.173 s for export plus 3.490 s for comparison). The returned output had 48 valid HDR10+ records and exact decoded audio. The private laboratory receipts for the earlier rejected encodes remain available under their original names.
