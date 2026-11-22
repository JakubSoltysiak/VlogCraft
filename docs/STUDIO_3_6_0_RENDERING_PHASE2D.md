# VlogCraft Studio 3.6.0 Phase 2D

Phase 2D starts at the verified Phase 2C commit `c499f54ab2a146870b11c3fd350c8d2ab80d4f57` and is stacked on the Phase 2C branch. The ordinary saved format and reference FFmpeg renderer remain available. The development installer exposes the GPU renderer only as an explicit option for an edited HDR10+ master. It requires a matching, previously verified reference master. A rejected native attempt retries the whole export with FFmpeg.

## Saved project to verified HDR10+

| Stage | Implementation and ownership |
|---|---|
| Load and validate | The editor and the command-line driver use the existing project validation. Version 4 source ticks and sequence frame indices reopen through the existing timing model. No project migration or alternate saved format is required. |
| Schedule | The adapter flattens sequences with the managed sequence helper and uses the existing integer frame spans, visible track order, clip positions, transition plans and source handles. The worker receives a temporary binary command stream. |
| Select and decode | Bounded FFprobe indexing supplies original video timestamps and time bases. The instruction stream retains rational source selections for VFR. The worker verifies each decoded timestamp and uses the D3D11 device shared with its compositor. |
| Normalize and composite | Resident NV12/P010 is converted to float32 linear Rec.2020, oriented, fit to the canvas and composited in track order. Prepared still and title pixels are uploaded once per distinct source in an export. The affine sampler retains the Phase 2 half-pixel coverage rule and samples premultiplied color and coverage together. |
| Encode and mux | GPU PQ conversion yields packed Main10 pictures. The existing segment exporter requests each video span, builds the existing audio graph, joins segments and produces their rational final clock. Only the provider of encoded video spans changes. CPU x265 retains the reference settings. |
| Author and verify | Phase 2C's histogram uses the final decoded Main10 pictures. The existing author verifies payloads against their pictures and validates the coded video and audio. A separate delivered-master comparison requires matching stream declarations, video timestamps, static HDR, one HDR10+ record per picture, and exact decoded PCM and audio endpoint. Decoded PQ PSNR must reach 50 dB both overall and on every picture. |
| Publish | The proven output is committed through the existing destination protection in the editor. CLI publication is atomic and rejects an existing destination. The reference master is opened read-only and cannot also be the destination. |

## Native admission and verification

| Operation | Status |
|---|---|
| H.264 BT.709 SDR VFR and rotated HEVC Main10 PQ | Resident on Radeon 890M and verified against the 24- and 120-picture saved projects. Original presentation timestamps are checked during decoding. Other devices, profile combinations and late-source seeks require further qualification. |
| Multiple video tracks, original clip positions, trim ranges and source holds | Integrated with the managed scheduler. The reference comparison checks every delivered picture. Nested timelines use existing flattening and still need dedicated native end-to-end coverage. |
| Scale, translation, rotation, opacity, premultiplied alpha and geometry keyframes | Basic operations implemented. The matched project covers animated scale, a rotated translucent overlay and title fades. Easing and broader keyframe combinations need more end-to-end controls. |
| sRGB PNG/JPEG and title rasterization | Prepared once with the managed photograph and title helpers. PNG alpha, animated photograph and title appearance passed in both pairs. EXIF orientation is covered by adapter tests. The source cache belongs to a single export and naturally discards entries when the job ends. |
| Canvas fit, crop to fill, ellipse and rectangle with feather | The representative project verifies a rotated feathered ellipse and a pillarboxed portrait source. Crop to fill and rectangle are implemented. Broader aspect ratios, explicit clip crop, mask combinations and independent mask-animation coverage remain open. Explicit clip crop uses the reference. |
| Centered dissolves and dip transitions | Two centered dissolves passed in both Radeon pairs. Fractional-rate white dip is covered by the WARP saved-project test. Black dip and simultaneous picture transitions need dedicated controls. Multiple simultaneous picture transitions use whole-project reference fallback. |
| Exposure and technical color | Linear exposure and mixed tagged BT.709/PQ passed. Unsupported resident range/codec/profile, creative contrast and saturation, retiming and unsupported geometry use the managed path. Existing HDR restrictions still apply to LUTs, chroma key, unqualified HLG, Samsung Log and other effects. |
| Audio and HDR10+ | Both comparison pairs retain camera audio crossfade, mixed music, x265 Main10, static HDR and exact decoded audio. No segment-level path mixing. AMD AMF remains outside edited HDR10+ qualification. |
| Preview | Existing preview and audio paths require no changes. Matched final output validates against the same managed rendering rules. Installed live-preview parity, calibrated HDR monitor behavior and physical audio sync remain open. |

The adapter admits up to eight source slots and four resident video decoder streams. The worker checks its texture budget and verifies the manifest before rendering. The plan is bounded to 7,200 output frames with a bounded early-source decode window. These experimental admission limits route other valid workloads to the reference. Imports and original media remain unrestricted by the GPU planner. The template is stored as local scratch with a staged delivery file. Neither the inputs nor diagnostic media are published.

## Paired Windows workstation results

Radeon 890M hardware on AC. The 24-picture comparison reopens the exact Phase 2C saved project and uses its frozen reference master. The 120-picture project extends the same editing pattern with changing media and reuses the same private PQ source. Its paired reference shares the Phase 2C parallel-color and exact author. The table uses the native wall clock through independent comparison. The reference wall clock includes the renderer's existing author verification.

| UHD60 saved project | Reference | Native with comparison | Speedup | Correctness |
|---|---:|---:|---:|---|
| 24 pictures, untouched Phase 2C fixture | 113.253 s | 18.731 s | 6.05× | 58.38 dB overall, 54.47 dB lowest picture, exact PCM and 24 HDR10+ associations |
| 120 pictures, changing mixed media | 412.983 s | 36.092 s | 11.44× | 57.03 dB overall, 51.77 dB lowest picture, exact PCM and 120 HDR10+ associations |
| 300 pictures | Pending | Pending | | |
| 600 pictures | No paired run | No paired run | | Unqualified |
| 1,800 pictures | No paired run | No paired run | | Unqualified |
| 3,600 pictures, 60 s | No paired run | No paired run | | Separate production gate |

| Native measurement | 24 pictures | 120 pictures |
|---|---:|---:|
| Preparation, including original PTS index and static assets | 9.498 s | 12.533 s |
| Segment render, existing audio and mux | 6.467 s | 14.567 s |
| GPU composition, median per picture | See JSON receipt | 7.731 ms |
| GPU PQ conversion, median per picture | See JSON receipt | 2.429 ms |
| HDR10+ author including packet verification | 1.221 s | 4.050 s |
| Complete native master before independent comparison | 17.188 s | 31.152 s |
| Delivered FPS through independent comparison | 1.281 | 3.325 |
| Audio endpoint at 48 kHz | 19,200 samples | 96,000 samples |
| Peak summed process working set, native | 2,346.9 MiB | 3,258.2 MiB |
| Peak summed process working set, reference render | 7,086.5 MiB | 8,015.9 MiB |
| PDH peak shared GPU process memory | 1,533.28 MiB | 1,540.78 MiB |
| Sampled machine CPU share, native | 5.40% | 7.15% |

GPU time, source normalization, pipe waits and measured x265 feed/wait time overlap. Their sums do not represent wall time. Both hardware video sources report zero CPU pixel transfers. CPU encoding reads back the GPU output. DXGI/PDH memory measurements overlap shared system allocations on the integrated Radeon and should be interpreted separately from the process working set. PDH reported zero engine occupancy during known GPU work. Per-dispatch timestamp queries provide the GPU timing in this report.

The first hardware run took 19.257 s and reached the same 58.38 dB. The original 120-picture fixture setup reopened at 121 pictures because the synthetic still hold used an image demuxer time base. The retry gave the generated still an explicit timeline-compatible tick before saving. The 24-picture fixture was reused unchanged. The Windows WARP test initially found a test title still had its default fade-out and exposed transient scratch cleanup on one fault attempt. The fixture now isolates fade-in and the worker's scratch cleanup retries short Windows sharing conflicts.

## Reproduce and interpret the results

Build with the pinned Windows native tools using `tools/setup_architecture_lab.py --component zig --component ffmpeg-shared --build-project-export`. Include the runtime in a private development installer with `packaging/build_windows.py --experimental-native --experimental-project-export`. The standard installer build does not supply the project export worker.

```powershell
python benchmarks/phase2d_project_export.py $savedProject $target --backend d3d11 --worker $worker --runtime $sharedDllFolder --author-dll $statisticsDll --compare-master $referenceMaster --report $localReceipt --resources
```

The supplied master must correspond to the same project, source media, edits and export settings. This guard is appropriate for repeated qualification and controlled use. It does not eliminate the cost of creating a first reference and is not a general automatic project-export policy. Candidate output that fails comparison is discarded before the existing reference export runs. Keep comparison files and diagnostic media local.

Phase 2D qualifies a scoped development path. Remaining gates include physical device-loss/recreation, interrupted or shutdown stress, wider decoder and effect coverage, multi-minute memory and editing workloads, installed preview parity, the full 60-second UHD60 HDR10+ export and display acceptance. Test and delivery receipts are linked in [VERIFICATION](../VERIFICATION.md). The [machine-readable report](benchmarks/studio-3.6.0-phase2d.json) retains the measured comparisons and failed setup attempt. The complete milestone roadmap is in [TODO](../TODO.md).
