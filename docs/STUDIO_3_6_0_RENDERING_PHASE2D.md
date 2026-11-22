# VlogCraft Studio 3.6.0 Phase 2D

Phase 2D starts at the verified Phase 2C commit `c499f54ab2a146870b11c3fd350c8d2ab80d4f57` and is stacked on the Phase 2C branch. The ordinary saved format and reference FFmpeg renderer remain available. The development installer exposes the GPU renderer only as an explicit option for an edited HDR10+ master. It requires a matching, previously verified reference master. A rejected native attempt retries the whole export with FFmpeg.

## Saved project to verified HDR10+

| Stage | Implementation and ownership |
|---|---|
| Load and validate | The editor and the command-line driver use the existing project validation. Version 4 source ticks and sequence frame indices reopen directly through the existing timing model. |
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
| Audio and HDR10+ | Both comparison pairs retain camera audio crossfade, mixed music, x265 Main10, static HDR and exact decoded audio. Fallback renders the whole project. AMD AMF remains outside edited HDR10+ qualification. |
| Preview | Existing preview and audio paths require no changes. Matched final output validates against the same managed rendering rules. Installed live-preview parity, calibrated HDR monitor behavior and physical audio sync remain open. |

The adapter admits up to eight source slots and four resident video decoder streams. The worker checks its texture budget and verifies the manifest before rendering. The plan is bounded to 7,200 output frames with a bounded early-source decode window. These experimental admission limits route other valid workloads to the reference. Imports and original media remain unrestricted by the GPU planner. The plan is stored as local scratch with a staged delivery file. Inputs and diagnostic media stay local.

## Paired Windows workstation results

Radeon 890M hardware on AC. The 24-picture comparison reopens the exact Phase 2C saved project and uses its frozen reference master. The 120- and 300-picture projects extend the same editing pattern with changing media and reuse the same private PQ source. Their paired references share the Phase 2C parallel-color and exact author. The table uses the native wall clock through independent comparison. The reference clock includes the renderer's existing author verification. The 300-picture reference time is a stage estimate reconstructed across an interrupted run and its recovery.

| UHD60 saved project | Reference | Native with comparison | Speedup | Correctness |
|---|---:|---:|---:|---|
| 24 pictures, untouched Phase 2C fixture | 113.253 s | 18.731 s | 6.05× | 58.38 dB overall, 54.47 dB lowest picture, exact PCM and 24 HDR10+ associations |
| 120 pictures, changing mixed media | 412.983 s | 36.092 s | 11.44× | 57.03 dB overall, 51.77 dB lowest picture, exact PCM and 120 HDR10+ associations |
| 300 pictures, interrupted reference recovered | ~801.277 s estimated | 62.428 s attempt | — | Rejected at 49.48 dB on frame 193. The reference remains valid. |
| 600 pictures | No paired run | No paired run | | Unqualified |
| 1,800 pictures | No paired run | No paired run | | Unqualified |
| 3,600 pictures, 60 s | No paired run | No paired run | | Separate production gate |

| Native measurement | 24 pictures | 120 pictures |
|---|---:|---:|
| Preparation, including original PTS index and static assets | 9.498 s | 12.533 s |
| Segment render, existing audio and mux | 6.467 s | 14.567 s |
| GPU composition, median per picture | 7.792 ms | 7.731 ms |
| GPU PQ conversion, median per picture | 2.388 ms | 2.429 ms |
| Resident decode, sum of source decode wall counters | 0.063 s | 0.107 s |
| Resident normalization, sum of source GPU counters | 0.266 s | 0.865 s |
| x265 feed and wait wall, including pipeline backpressure | 5.132 s | 13.139 s |
| x265 encoding process CPU time | 5.718 s | 21.001 s |
| HDR10+ author including packet verification | 1.221 s | 4.050 s |
| Complete native master before independent comparison | 17.188 s | 31.152 s |
| Delivered FPS through independent comparison | 1.281 | 3.325 |
| Audio endpoint at 48 kHz | 19,200 samples | 96,000 samples |
| Peak summed process working set, native | 2,346.9 MiB | 3,258.2 MiB |
| Peak summed process working set, reference render | 7,086.5 MiB | 8,015.9 MiB |
| PDH peak shared GPU process memory | 1,533.28 MiB | 1,540.78 MiB |
| Sampled machine CPU share, native | 5.40% | 7.15% |

GPU time, source normalization, pipe waits and measured x265 feed/wait time overlap. Each wall clock is measured separately. Both hardware video sources report zero CPU pixel transfers. CPU encoding reads back the GPU output. DXGI/PDH memory measurements overlap shared system allocations on the integrated Radeon and should be interpreted separately from the process working set. PDH reported zero engine occupancy during known GPU work. Per-dispatch timestamp queries provide the GPU timing in this report.

FFmpeg's cadence filter independently selected the same original source timestamps as the native plan on all 22 source-layer samples in the 24-picture project, 100 in the 120-picture project and 224 in the 300-picture project. The check covers preroll and clips appearing in two layers during dissolves.

Seven 960 × 540 managed program stills were compared with the SDR tone-mapped diagnostic of each delivered master. Relative to these stills, GPU delivery measured 33.39–49.92 dB RGB PSNR and the frozen reference measured 32.17–49.90 dB. The differences from either master include resized composition, tone mapping and delivery quantization. This is a static monitor comparison. Sustained live native preview and calibrated HDR display remain separate gates.

The first hardware run took 19.257 s and reached the same 58.38 dB. The original 120-picture fixture setup reopened at 121 pictures because the synthetic still hold used an image demuxer time base. The retry gave the generated still an explicit timeline-compatible tick before saving. The 24-picture fixture was reused unchanged. The Windows WARP test initially found a test title still had its default fade-out and exposed transient scratch cleanup on one fault attempt. The fixture now isolates fade-in and the worker's scratch cleanup retries short Windows sharing conflicts.

The first 300-picture run saved six complete reference spans covering 208 pictures. The final span exceeded the parallel converter's 300 s timeout and entered the managed retry. Windows then entered standby and the outer supervisor ultimately returned its timeout. The 36-byte incomplete video and original logs are retained locally. Recovery verified both clocks in the six saved spans, regenerated their matching filter graphs and rendered only the remaining 92 pictures with a longer converter deadline. The recovered render and assembly took 424.828 s, and authoring took 7.981 s. The prefix timing estimate of 368.468 s comes from consecutive filter-script creation times. Their sum gives the ~801.277 s reference estimate. Peak working set for the resumed portion was 6,723.2 MiB at 17.84% sampled machine CPU. Prefix peak memory and an uninterrupted full-reference wall clock are unavailable.

The 300-picture GPU attempt processed 4.805 pictures per wall second through verification. It matched video PTS, static HDR, exact PCM, the 240,000-sample endpoint and all 300 HDR10+ associations. It reached 56.90 dB overall. Frame 193 was the only picture below the 50 dB floor and prevented publication. A local comparison of the original eight-picture dissolve span isolated the difference. Frame 193 measured 65.49 dB between the unencoded GPU and managed PQ pictures. The managed and GPU encodes of that picture measured 49.65 and 50.39 dB against their own unencoded inputs. Their decoded outputs measured 49.48 dB against each other. The results identify sensitivity to x265 compression on that frame while the independently checked source PTS agree. The x265 settings and both quality floors remain in force. The failed output stays in private diagnostics, and the installed exporter uses the whole-project reference fallback after this class of rejection.

In the 300-picture GPU attempt, preparation took 16.031 s, segment render took 25.857 s, authoring took 9.387 s and independent comparison took 11.106 s. Median GPU composition and PQ conversion were 4.494 and 2.461 ms. x265 feed and wait took 24.342 s, and sampled encoder CPU time was 46.921 s. Peak summed process working set reached 3,409.2 MiB, sampled machine CPU averaged 8.52%, and peak shared GPU process memory was 1,536.78 MiB. These measurements do not establish a sustained memory plateau.

The 120-frame reference rate and the recovered 300-frame stage estimate project roughly 2 h 40 min to 3 h 27 min for a matching 3,600-frame reference. The rejected GPU attempt projects roughly 12.5 min at the same rate. Neither extrapolation is a completed run. The 300-frame picture rejection and the reference time make a longer paired run premature. The 600-, 1,800- and 3,600-frame project gates remain open.

## Reproduce and interpret the results

Build with the pinned Windows native tools using `tools/setup_architecture_lab.py --component zig --component ffmpeg-shared --build-project-export`. Include the runtime in a private development installer with `packaging/build_windows.py --experimental-native --experimental-project-export`. The worker ships only with explicitly flagged development builds.

```powershell
python benchmarks/phase2d_project_export.py $savedProject $target --backend d3d11 --worker $worker --runtime $sharedDllFolder --author-dll $statisticsDll --compare-master $referenceMaster --report $localReceipt --resources
```

The supplied master must correspond to the same project, source media, edits and export settings. This guard is appropriate for repeated qualification and controlled use. A first-time export still requires a managed reference render. Candidate output that fails comparison is discarded before the existing reference export runs. Keep comparison files and diagnostic media local.

## First-export verification policy

Deterministic admission and the existing format checks can verify codec, stream clocks, audio endpoints, Main10/PQ declarations and final-picture HDR10+ associations before publication. Comparing decoded PCM against the managed audio render is also feasible independently of picture composition. These checks establish delivery integrity. Visual verification also needs a source-to-output contract for each admitted operation, including VFR selection, transition handles, alpha and subpixel sampling on each supported driver. Boundary and sampled reference renders could supplement that contract, with full comparisons retained for the validation matrix. The current workload and device coverage support keeping the full comparison in Phase 2D. The reported speedups apply when a verified matching master already exists.

Phase 2D is complete for the scoped development path. Production gates include the 300-picture encode outlier, physical device-loss/recreation, interrupted or shutdown stress, wider decoder and effect coverage, multi-minute memory and editing workloads, installed preview parity, the full 60-second UHD60 HDR10+ export and display acceptance. Test and delivery receipts are linked in [VERIFICATION](../VERIFICATION.md). The [machine-readable report](benchmarks/studio-3.6.0-phase2d.json) retains the completed comparisons, interrupted reference and rejected native attempt. The complete milestone roadmap is in [TODO](../TODO.md).
