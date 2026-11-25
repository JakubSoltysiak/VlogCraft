# First vlog export audit

## Saved project and delivery settings

The latest desktop revision of the vlog loaded through the normal project validator. Its four-track timeline runs for 21 minutes 47.117 seconds and contains 10 video clips, 18 PNG or JPEG stills and four standalone audio clips. All 24 used media files were present. The camera material includes HEVC SDR and Main10 PQ, rotated and upright clips, variable source cadence, source audio, and repeated trims from the HDR recording. A probe of the HDR camera recording found mastering-display and content-light declarations and HDR10+ dynamic metadata. The audit pinned a private copy of the saved revision, its SHA-256, and the identities and modification times of the linked media files.

The revision requests 3840 × 2160 at 60 fps, HEVC AMF and a 60 Mb/s target. The user confirmed a full-quality edited HDR10+ master. The reference exporter renders the entire edit to Main10 PQ and authors new HDR10+ metadata from the final decoded pictures. The old AMF setting has no managed color contract. Original HDR10+ stream copy requires a single unedited recording and its original cadence. The experimental first-export mode admits up to 120 frames and one or two opaque contiguous video clips. Its full-master comparison mode requires an existing verified master. See the [Phase 3A export scope](STUDIO_3_6_0_PHASE3A_EXPORT.md#first-export-without-a-prebuilt-master).

The managed path requires libx265 and a known source pixel aspect. The five linked camera files omit sample aspect ratio in the saved inventory and in a fresh stream and decoded-picture probe. Preflight rejected the saved geometry. With VlogCraft’s existing explicit square-pixel override and a complete PQ settings contract supplied in memory, every picture layer passed preflight. The resulting full-project clock is 78,427 pictures and an expected 62,741,600 samples per channel at 48 kHz.

## Representative reference export

The 48-picture preflight used the actual project’s still with standalone audio and a contiguous HDR-to-SDR camera cut with source audio and a change in orientation. It preserved 3840 × 2160 at 60 fps. The isolated project copy used the square-pixel override, the saved Slow setting and 60 Mb/s target, HEVC Main10 and 100-nit SDR white. The reference path carried the recording’s P3-D65 mastering primaries and 0.005–1,000 cd/m² mastering range, plus MaxCLL 1,000 and MaxFALL 200 cd/m², in the Rec.2020/PQ stream. It authored new HDR10+ dynamic metadata for the edited output.

The production reference export finished in **136.190 seconds**, including 8.650 seconds of HDR10+ authoring and verification after final muxing. The output was 679,781 bytes. Separate checks confirmed 48 Main10 Rec.2020 PQ pictures with exact PTS and duration, 48 conforming HDR10+ blocks, matching static declarations, and 38,400 samples per channel of 48 kHz AAC. The decoded PCM matched a separately rendered audio graph.

The first visual check timed out while seeking beyond the HDR source's video endpoint. The authored clip extends six output frames beyond that endpoint. A retry traced the reference cadence and matched all 36 camera picture selections to the corresponding packet PTS floor, including the six held pictures. The verifier decoded the selected source pictures directly for its raw composition, then compared the first, middle, and last output picture of each section. The nine decoded-to-raw PQ scores ranged from 51.90 to 58.53 dB. The last picture before the HDR-to-SDR cut scored 58.53 dB against the final HDR source picture. The independent retry took 54.552 seconds and left zero owned child processes. The original project and all 24 linked media signatures matched after the run.

The 60-second measurement uses one contiguous range from the pinned revision. It covers five original camera cuts across rotated VFR Main10 PQ trims into upright VFR SDR HEVC with camera audio. The 48-picture preflight also covered a still and standalone audio. The original edit uses straight cuts and contains no saved transitions or creative effects. The output clock is 3,600 pictures and 2,880,000 samples per channel at 48 kHz.

The 60-second reference export completed in **6,321.394 seconds (1 h 45 min 21.394 s)** and used 157,515,196 bytes of sampled peak export scratch. The delivered MP4 was 37,208,960 bytes. Independent verification took 454.103 seconds. It confirmed all 3,600 picture timestamps, durations and conforming HDR10+ blocks, the expected Main10 Rec.2020/PQ declarations and static metadata, and the exact 2,880,000-sample AAC endpoint per channel. Decoded PCM matched the independently rendered audio graph. All 3,600 camera selections matched the original PTS floor. The trace counted 70 repeated selections, including the six expected holds at the source endpoint. The 18 exact-source PQ spot checks ranged from 50.22 to 58.41 dB. The pinned project and linked media signatures matched after the run.

The minute's independent receipt sampled one child before the worker exited. A live Windows process query during verification identified its console host. A post-exit Windows query found neither the minute worker nor processes with that worker as their parent. The full run has a separate worker.

## Full export status

After the minute passed, the supervisor rechecked the pinned media, confirmed a new destination and recorded the estimate before starting the full reference export. The minute's measured export cost projects approximately **38 h 15 min** for all 78,427 pictures. The full project's mix of stills, camera footage, cuts and audio can change the actual rate. The saved nominal bitrate implies a 9.80 GB output and a 49.34 GB working-space budget, both decimal. The destination had 191.92 GB free before launch. The full render is encoding in a local Windows process with stage and elapsed-time receipts. Full-master timing and result remain pending.

## Where the reference minute spent its time

The six video-stage intervals below come from transitions in the original monotonic progress log. Each includes its source read/decode, selection, managed float graph, format conversion and x265 encode. The export ran at 0.5695 output pictures/s. Independent verification brought elapsed time for export plus audit to 6,775.497 s.

| Operation | Measured wall (s) | Interpretation |
|---|---:|---|
| Video spans of 103, 564, 85, 750, 812 and 1,286 pictures | 187.784, 925.484, 155.208, 1,220.711, 1,278.919, 1,933.179 | 5,701.284 s together, 90.19% of delivery. The commands overlap software decode, VFR cadence selection, FP32 composition/fit, zimg PQ conversion and x265 Slow. |
| Segment audio render, summed | 0.611 | Camera audio preparation across six spans. Final AAC coding also runs in the final mux process. |
| Segment stream joins, summed | 0.753 | Six joins. |
| Final MP4 mux | 1.009 | Includes concat and final audio processing. |
| Analyze final decoded PQ pictures | 616.796 | Reconstruct the pictures and derive dynamic metadata. |
| Attach HDR10+ blocks / internal final verification | 0.522 / 0.405 | Packet-order authoring and completion through the export return. |
| Independent verification | 454.103 | Additional source-clock, picture, metadata and PCM checks. |

The initial stage notification arrived at 0.014 s. Process startup, temporary I/O and thread contention occur inside these wall intervals. Peak observed scratch was 157,515,196 bytes. The minute contains no native GPU compositor or resident GPU-to-encoder handoff. Its log contains no isolated decode, source selection, spatial composition, linear-to-PQ or x265 timer. Subtracting separate microbenchmarks would misattribute overlapped work.

Earlier four-slice CPU filter tests reduced wall time on affine and matte fixtures. The measured 24-picture Phase 2B lab split was 12.390 s for raw-I/O zimg conversion and 1.739 s for x265 with already prepared input. The graphs, presets and input pictures differ from this vlog. Phase 2C moved eligible decoder pictures onto the GPU and shortened final-picture HDR10+ analysis while retaining byte-identical verified masters on its fixtures. Phase 3A's first-export mode subsequently delivered 48 Ultrafast pictures in 37.751 s versus 64.672 s for its reference. These results establish which components can be reused. [Phase 1](STUDIO_3_6_0_RENDERING.md) · [Phase 2B](STUDIO_3_6_0_RENDERING_PHASE2B.md) · [Phase 2C](STUDIO_3_6_0_RENDERING_PHASE2C.md) · [Phase 3A](STUDIO_3_6_0_PHASE3A_EXPORT.md).

### Effective encoder settings

FFprobe reported a 60.000 s container at 4,961,194 bit/s, HEVC Main10 video at 4,755,352 bit/s and AAC at 192,946 bit/s. The encoded x265 build 217 user-data record declares `rc=crf crf=20.0`. The saved Slow project passed both CRF 20 and a nominal 60 Mb/s value. FFmpeg selects x265 CRF before its average-bitrate branch. The observed size follows quality-based rate control. The original 49.34 GB working-space allowance remains a conservative planning figure. This evidence does not establish a file-size forecast for the other vlogs. [FFmpeg encoder initialization](https://ffmpeg.org/doxygen/trunk/libx265_8c_source.html#l00431) · [x265 rate control](https://x265.readthedocs.io/en/stable/cli.html#quality-rate-control-and-rate-distortion-options).

The Radeon 890M accepted P010 or D3D11 surfaces for AMF Main10. In a separate 24-picture transcode its D3D11 path took 0.609 s versus 1.947 s for software x265. Its CQP 20 and x265 CRF 15 results are different rate-control experiments. AMF changed two in-band mastering coordinates and the single-command mux shortened the audio. The repaired audio mux did not resolve mastering. Keep software x265 for verified HDR10+ delivery. [AMF comparison](STUDIO_3_6_0_RENDERING_PHASE2B.md#amd-amf-diagnostic).

### Full master interruption, 25 November

The last activity was output picture 3,489 of 78,427, 58.15 s of timeline, segment 9 of 30, at 2,875.099 s elapsed. Windows logged a power-off request six seconds after the final progress sample and a kernel power transition five seconds later. On the subsequent check the recorded supervisor, worker and encoder were absent. The intended destination contained no final master. The saved status still said running and recorded no worker exception or exit code. This is an interrupted job with no final-file verification. The job folder, source project, media, private scratch and destination were left in place. Recovery of the partial render and restart-safe segment reuse remain open.
