# VlogCraft Studio 3.6.0 Phase 3A export qualification

Phase 3A starts at `2520ce60149bdff3392a3e895498af54c1e48b39`, the verified Phase 2D checkpoint. The reference exporter remains the default. The optional development runtime offers full-master comparison and a separate first-export experiment.

## Frame 193

The retained 300-frame project uses changing H.264 SDR VFR, a rotated camera HEVC Main10 PQ clip, stills, titles, masks, and mixed audio. Frame 193 belongs to the eight-picture closed dissolve span `[192, 200)`. The probe reproduced the whole span with its original timing and source selection, original Ultrafast CRF 15 profile, and complete encoder context.

| Control at frame 193 | PQ PSNR |
|---|---:|
| Managed raw and GPU raw | 65.49 dB |
| Managed encoded and its own raw input | 49.65 dB |
| GPU encoded and its own raw input | 50.39 dB |
| Decoded GPU and decoded managed | 49.48 dB |
| Decoded GPU with exact CPU zimg output conversion and decoded managed | 49.29 dB |

Repeated encodes of each identical raw input produced identical decoded pictures. The packed GPU output and managed encode differ by less than 0.2% in the eight-picture file size. Frame 193 had QP 26 in all three arms, with 240,200 bits for managed input, 249,392 for packed GPU input and 282,480 for GPU input using zimg. The decoded outlier measured 0.713 cd/m² mean absolute error in reconstructed linear Rec.2020 RGB, versus 0.149 cd/m² for the raw pair. Mean absolute luminance error grew from 0.112 to 0.586 cd/m². For pixels at or above 100 cd/m² in the corresponding managed picture, mean luminance error grew from 1.392 to 6.066 cd/m². Difference images and raw source material stay in the ignored local QA directory. The evidence identifies a deterministic compression response to small input changes in this GOP. The individual x265 decision remains unresolved. Using the managed final PQ converter alone still produced the outlier.

## Bounded repair with full-master verification

When all motion and delivery clocks, decoded PCM, static HDR and metadata associations agree, an isolated picture-quality rejection can trigger one managed rerender. The initial overall PSNR must reach 50 dB. All rejected pictures must lie in one closed segment of up to 16 pictures and at most one quarter of the output. VlogCraft replaces that segment using the original settings, rejoins the existing segment set with its normal timestamps and AAC graph, reauthors from the final decoded pictures, and repeats the full independent comparison. Any remaining rejection uses the whole-project reference. The candidate stays in scratch until verification passes.

The repaired 300-picture project delivered **292 GPU and 8 managed pictures in 137.763 s**, including both comparisons and both rounds of authoring. It reached **57.08 dB overall and 52.53 dB minimum** with exact video timestamps, decoded PCM and a 240,000-sample audio endpoint. All 300 HDR10+ associations and static declarations passed. Its 801.277 s reference is the Phase 2D reconstructed estimate. The first 49.48 dB rejection is retained. x265 profile, bitrate settings, and both 50 dB floors are unchanged.

## First export without a prebuilt master

The experiment is opt-in on the AMD Radeon 890M. It admits up to 120 UHD60 frames with one visible picture track and one or two opaque, contiguous straight-cut video clips. Actual source probes restrict it to limited-range H.264 BT.709 SDR and HEVC Main10 PQ, with the tested upright and clockwise orientations. It uses the existing Ultrafast CRF 15 output profile, static HDR mastering and content-light declarations, and the existing audio engine. It allows the tested neutral or +0.2-stop exposure. Other profiles, transforms, transitions, nested sequences, titles, stills and masks remain available through the reference or full-master GPU mode as applicable.

The runtime independently checks all original source selections against the software cadence filter, output frame timestamps, Main10/PQ signaling, mastering and content-light data, one HDR10+ block per output picture and the exact 48 kHz audio endpoint. It rerenders the audio graph separately and compares decoded PCM. It checks the first, middle and last picture in each closed span against an independently rendered managed PQ picture at 50 dB or above. A failed check discards the candidate and runs the complete reference workflow. Original-file identities are checked before publication. The independent tests also hash the original recordings.

These sampled visual checks cover their selected pictures. Unsampled pictures have structural, source-clock and authoring verification plus evidence from the qualification pairs. Full-master comparison continues to check every decoded picture. Wider coverage and additional adapter/driver combinations remain production gates.

## Measured Windows results

| Saved UHD60 workload and verification mode | Reference | GPU wall time | Result |
|---|---:|---:|---|
| 24, mixed editing, existing master | 113.253 s | 19.386 s | 58.38 dB overall and 54.47 dB minimum, exact PCM |
| 120, mixed editing, existing master | 412.983 s | 35.690 s | 57.03 dB overall and 51.77 dB minimum, exact PCM |
| 300, mixed editing, existing master and repaired span | ~801.277 s | 137.763 s | 57.08 dB overall and 52.53 dB minimum, exact PCM |
| 48, two straight-cut clips, first export | 64.672 s | 37.751 s | 1.71×. All six sampled raw comparisons passed. Its output exactly matched the earlier 37.561 s run, which passed the later full comparison at 55.63 dB overall and 53.64 dB minimum. |
| 48, same project, full-master GPU comparison | 64.672 s | 19.032 s with the master present | 83.704 s if the reference must first be rendered. |
| 120, two straight-cut clips, first export | 231.407 s | 86.294 s | All six runtime samples and the later full comparison passed. The latter measured 55.43 dB overall and 53.64 dB minimum. |

Timings include the candidate's runtime checks. Separate full CPU renders used after the first export provide qualification evidence and are excluded from the experimental operation's wall time. The 48-frame reference uses the same x265 settings and fast HDR10+ author path. Other local QA overlapped the 120-frame straight-cut runs and the 114.961 s injected-GPU-fault run. The latter produced the complete reference output with exact PCM and passed the independent picture comparison. Its time includes the native attempt and the entire managed fallback. These overlapping trials provide functional and resource evidence.

The repeated 48-picture first export reached 2,291.7 MiB peak summed working set. The 120-picture first export reached 2,633.5 MiB working set and 779.28 MiB sampled peak shared GPU memory. The 300-picture repair reached 5,197.1 MiB working set and 1,540.78 MiB sampled shared GPU memory. The integrated Radeon uses shared system memory, so these metrics are reported separately. Short tests measure cleanup and peak resource use.

The packaged editor delivered the first export offline in 51.063 s through the terminal job status during overlapping QA. An independent check verified all 48 decoded pictures and PCM against the reference, and parsed all 48 HDR10+ blocks from the output packets. Active cancellation and confirmed shutdown left zero owned processes, no new terminal windows and no partial masters. An initial shutdown automation attempt sent the wrong confirmation command to the WinForms OK/Cancel prompt. That timed-out attempt is retained, and the same package passed after the test automation was corrected. The default HDR10+ and unsupported-effect fallback controls also passed.

The [measurement record](benchmarks/studio-3.6.0-phase3a.json) retains the outlier, encoder perturbation controls, runtime comparisons and resource receipts. [Verification](../VERIFICATION.md) and the [roadmap](../TODO.md) distinguish development qualification from long-session, physical recovery and full 60-second production gates.
