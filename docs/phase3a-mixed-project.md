# Mixed camera, photograph and audio export

The private UHD60 edit contains 10 camera clips, 18 PNG/JPEG stills and four standalone audio clips. The [previous camera qualification](phase3a-camera-raster.md) covers 600 and 3,600 pictures on Radeon 890M. All workstation experiments below use the saved HEVC Main10 Slow CRF 20 profile, BT.2020/PQ and software x265. Each performance trial runs separately on AC.

## What changed

The opt-in mixed provider walks the existing render boundaries. A neutral opaque camera span can use the existing indexed D3D11 decoder and reference-equivalent zimg raster. The managed picture graph handles a photograph's color interpretation, EXIF orientation, framing, alpha and opacity. Original source PTS stay on the original timeline even when camera spans are separated by a photograph. The normal renderer owns the audio graph and AAC delivery. The provider checks each independently encoded span for an IDR start, compatible decoder configuration and exact local picture clocks. HDR10+ is authored from the assembled final decoded pictures.

The faster path keeps three FP32 color planes for an opaque rotated camera and reuses constant letterbox margins. An eligible static still needs one fully composed, quantized Main10 picture per span. The enhanced provider repeats that picture before x265, retaining its original frame count and clock. Per-picture creative changes use the full graph. The fast verifier independently re-renders each selected static-still instant through the original graph. A separate decode compares every exported picture with the matched managed master.

## Archived 48-picture control and photograph color

The archived 48-picture mixed excerpt used 12 photograph pictures with standalone audio, 18 rotated PQ camera pictures and 18 upright SDR camera pictures. Its original managed export took 136.190 s. The initial mixed provider reproduced all 48 coded/decoded pictures, all dynamic records and 38,400 stereo samples per channel. Its delivery took 132.370 s, including 55.456 s of first-export checks. This established equivalence with the archived edit.

Inspecting the ICC tags disclosed a shared color error in that reference. The real JPEGs use P3-D65 colorants and sRGB transfer curves. The old renderer recognized “sRGB” in the ICC description and selected BT.709 primaries. Reproducing its pixels alone could not detect the mistake. These legacy measurements remain comparisons to that historical interpretation. The corrected managed and accelerated qualification uses the actual embedded primaries, including the three EXIF-orientation-6 photographs in the longer range. Generic transparent PNGs, a nontrivial opacity and the saved explicit sRGB interpretation have separate regression coverage. The numeric checks use the registered Display P3 primaries, D65 white and piecewise transfer function. [ICC Display P3 definition](https://registry.color.org/rgb-registry/displayp3) · [FFmpeg zscale mapping](https://ffmpeg.org/doxygen/trunk/vf__zscale_8c_source.html).

An explicit saved sRGB override reproduced the original real-camera excerpt's 48 coded/decoded pictures, all 48 original dynamic records and its PCM. With embedded P3 enabled, exactly the 12 photograph pictures and their 12 records changed. All 36 camera pictures and their records stayed identical. The corrected and archived masters still scored 53.43 dB or higher on every picture, illustrating why the colorant and pixel-identity checks are needed in addition to PSNR.

## Raster and encoding measured separately

One 36-picture interval from the failing historical encoder span supplied the same actual Main10 input on disk to each encoder. Capturing the indexed source planes took 1.693 s. The control raster including sequential raw output took 39.496 s. The RGB-only raster with cached margins took 34.114 s and produced identical bytes. Encoding the prepared pictures without the raster took 31.318 s with two pool workers and 9.101 s with eight. Both used two frame threads, WPP and the same mastering declarations. These are isolated stage timings. Rasterization and encoding overlap during delivery.

FFmpeg could not negotiate a float-RGB `pad` filter. Four-thread zimg conversion also changed the quantized input. Isolating four threads separately at input linearization, bilinear resize and final PQ conversion changed pixels in each case on the twelve-picture control. The selected optimization retains single-thread zimg kernels. Prior results, including the rejected packed-GPU exports, remain in the [encoder-input report](phase3a-camera-raster.md).

## Independent delivery measurements

All 48 pictures matched their corrected managed master in both the original edit-boundary encoder and the single uninterrupted encoder. The latter also matched every byte of the independently prepared Main10 encoder input. The first export with edit-boundary encoders reached the authored master in 65.337 s and used 50.116 s for additional verification. Its total was 115.474 s, followed by 3.721 s for independent comparison. The managed edited control took 88.789 s. These small jobs spend a substantial fraction of delivery on verification.

| Corrected mixed excerpt | Delivery or qualification time | Sampled peak process-tree working set |
|---|---:|---:|
| Managed, original edit boundaries | 88.789 s | 3.41 GiB |
| Indexed camera, original raster and verifier, including independent checks | 145.739 s | 2.32 GiB |
| Indexed camera and prepared still, including independent checks | 119.205 s | 2.50 GiB |
| Managed, original edit boundaries, eight x265 pool workers | 78.527 s | 3.43 GiB |
| Indexed camera and prepared still, eight x265 pool workers, including independent checks | 107.914 s | 2.61 GiB |
| Managed, one uninterrupted x265 context with a disk-backed raw oracle | 96.957 s including control preparation | 2.72 GiB |
| Indexed camera and prepared still, one uninterrupted context with full checks | 117.920 s | 2.98 GiB |
| Cold independent segments, serial, both references checked | 103.764 s | 2.50 GiB |
| Cold independent segments, two workers, both references checked | 75.778 s | 3.65 GiB |

An independent decode of every 10-bit Y/U/V sample measured minimum/overall compression PSNR of 51.830/53.788 dB for the edit-boundary encode and 51.847/53.722 dB for the uninterrupted encode. Neither had a picture below 50 dB. The repeated managed uninterrupted control reproduced both the earlier control file and the complete uncompressed input byte for byte.

At a fixed two-worker x265 pool the new raster and still reuse reduced the matched 48-picture wall time, including independent checks, from 145.739 s to 119.205 s (18.2%). At eight x265 workers it took 107.914 s and matched its separately rendered eight-worker reference. These are one physical run per configuration.

Independent segments started at pictures 0, 12 and 30. The joined output preserved all 48 original segment packets and isolated segment decodes. Against the uninterrupted encode, the minimum per-picture PSNR was 54.24 dB and overall PSNR was 55.892 dB. All 48 pictures matched the separately managed encode with the same cuts. Its 48 HDR10+ records matched exactly. The uninterrupted encode reconstructed slightly different pixels in every frame, and its 48 dynamic records accordingly differed. PCM, sample endpoints and static HDR matched both references.

A separate serial export was stopped immediately after its first verified segment. Restart reused that segment, encoded the other two, and passed both references. The declared two-worker memory check requires twice the observed serial segment process-tree working set to be available.

The optional project-export runtime exposes **Mixed cameras and stills · exact master** in the export dialog. The user selects a matched local master. The editor uses the saved Slow CRF 20 profile, checks every decoded picture, audio sample, video and AAC packet clock, and final HDR10+ payload, and publishes only an accepted candidate. The existing managed renderer handles unsupported projects and verification failures. The uninterrupted and restartable segment experiments remain accessible through their qualification commands.

## Second source format on the original timeline

Original frames [2400, 2736) contain a 300-picture PNG hold and 36 pictures from a different rotated SDR camera, with standalone music and camera audio. This PNG stores an RGBA channel layout with fully opaque alpha. Synthetic tests exercise fractional alpha, opacity, rotation and masking. At eight x265 pool workers, the matched managed export took 299.533 s. The optimized delivery including independent checks took 105.708 s. All 336 coded and decoded pictures, 336 HDR10+ records and 268,800 PCM sample positions matched. The lowest of six uncompressed visual samples was 59.466 dB.

## Contiguous 936-picture first export

The edited source interval contains three EXIF-rotated P3-D65 photographs, standalone 44.1 kHz audio, and a rotated HEVC SDR camera with its own 48 kHz audio. The managed control took 552.828 s. The indexed camera and prepared-still route reached the authored master in 245.599 s and completed its own checks in 293.290 s. Independent decoding and coded-picture comparison extended elapsed time to 324.872 s, 41.2% below the original managed delivery time even with this extra check. Both trials peaked near 5.09 GiB of sampled process-tree working set.

All 936 coded pictures, 936 independent picture decodes, 936 HDR10+ records, static declarations and 748,800 decoded PCM samples per channel matched the managed master. The provider separately checked all 36 original camera selections, including four repeated PTS selections. The lowest of 13 comparisons with uncompressed input was 52.457 dB. The three eligible static holds and a one-picture still interval accounted for 190.138 s of picture encoding. Indexed camera encoder feed and wait consumed 27.678 s. Final metadata authoring took 25.726 s.

A separate managed control wrote all 23,290,675,200 bytes of the canonical uncompressed Main10 sequence, encoded them in one x265 context and authored a second master. Independent decodes measured the squared error over every Y, U and V sample in both masters. All 936 pictures passed 50 dB in each. The edit-boundary encode measured 52.457 dB minimum at local frame 899 and 57.026 dB overall. The uninterrupted encode measured 54.727 dB minimum at frame 905 and 56.875 dB overall. The two encoder layouts reconstructed 296 identical pictures. Creating the disk-backed uninterrupted control took 812.87 s through its master, followed by 203.22 s for the two full raw audits.

The accelerated mixed providers streamed the same 23,290,675,200 input bytes into one uninterrupted encoder. The input hash, 936 coded pictures, 936 final decodes, 936 dynamic metadata records and 748,800 PCM sample positions matched that control. The master was ready at 239.837 s and publication after verification took 311.319 s. Its process tree peaked at 5.83 GiB. The disk-backed control includes preparation of the uncompressed oracle, so the two times measure different amounts of work.

Cold serial encoding and verification of five independent segments took 484.527 s. They began on IDRs at local pictures 0, 300, 600, 899 and 900. The four joins preserved all 936 original coded segment pictures and all 936 isolated decodes. The fully authored result matched the managed edit-boundary master. Against the uninterrupted encode, the minimum per-picture PSNR was 53.13 dB and overall PSNR was 59.934 dB. The two layouts had 296 identical decodes and 300 matching dynamic records. Every record in the delivered master matched the edit-boundary oracle for the same final picture.

The cold two-worker run produced a byte-identical complete master in 361.713 s, a 25.3% reduction. The segment stage fell from 320.311 to 199.132 s. Its sampled process-tree working set rose from 5.19 to 9.84 GiB. Final audio encoding, assembly, authoring and the two independent master comparisons still ran serially. Worker admission checks the available system memory against the observed serial requirement.

The 936-picture recovery test restored four durable, verified checkpoints into a fresh trial directory. A new exporter used those four and actually encoded the final 36 camera pictures. An injected process exit after the final artifact rename and before its verification receipt returned code 47 after 53.907 s. The four checkpoints still matched their hashes and no master had been published. The test truncated the unreceipted artifact to 4,096 bytes. A new process reused exactly the four verified sections, rendered the fifth again, checked both masters and published a byte-identical file in 201.383 s. This exercises an owner exit at the publication boundary. Physical power loss and device removal are separate open tests.

## Balanced 600-picture camera and photograph comparison

Original frames [6901, 7501) supply a more balanced throughput measurement. The first 300 pictures contain one P3 photograph, standalone music and the one-picture silence boundary. The next 300 are the first five seconds of the 30,682-picture camera interval and include eight repeated source PTS selections. At eight x265 workers the managed export took 500.274 s. The accelerated export reached its authored master in 204.714 s, finished its own checks in 265.165 s and completed the additional independent comparison in 286.465 s, a 42.7% wall-time reduction. Both routes produced the same 600 coded pictures, 600 final decodes, 600 HDR10+ records and 480,000 decoded stereo sample positions. The accelerated process tree peaked at 5.07 GiB against 5.47 GiB managed. The camera feed and encoder wait took 154.632 s, still encoding took 32.520 s and authoring took 16.142 s.

All 600 pictures in each encoder layout passed the full raw audit. The edit-boundary encode measured 52.457 dB minimum at frame 299 and 56.580 dB overall. The uninterrupted eight-worker control measured 52.761 dB minimum at frame 595 and 56.563 dB overall. The two layouts produced identical decoded pixels in 289 pictures. Preparing the separate uninterrupted control took 545.567 s through its master and both independent raw decodes took another 122.124 s.

## Full-project scope

The saved edit has 78,427 pictures, 62,741,600 stereo sample positions and 30 original render intervals. Camera footage supplies 72,427 pictures (92.3%). Static photographs supply 6,000. Six individual intervals exceed the 3,600-picture qualification budget, including one 30,682-picture camera interval. The longest mixed comparison is photograph-heavy. The balanced 600-picture comparison samples five seconds of the longest camera interval. A full-project delivery estimate still needs a sustained, camera-dominant run with recoverable subdivisions.

Inspecting all 18 still files found a second form of Display P3 profile in the closing PNG. Its ICC v4 matrix contains the D50-adapted P3 colorants, with no separate chromatic adaptation tag. The importer now additionally recognizes that numeric matrix, both D50 white declarations and the sRGB transfer curves. All 18 still files pass color admission, 11 as Display P3 and seven as sRGB. Four swatches bearing the actual closing PNG profile agreed with independent LittleCMS relative colorimetry to within 0.543 cd/m² per linear Rec.2020 component. This class has a tighter matrix tolerance of 0.0003. Unknown matrices and alternate transforms are rejected.

The first 24 pictures of that final photograph, original frames [77827, 77851), passed a separate export with the saved soundtrack. The prepared still matched the uninterrupted full-graph control on all 24 coded and decoded pictures, 24 HDR10+ records and 19,200 PCM samples per channel. All 24 pictures exceeded 61.7 dB against the uncompressed Main10 input.

Before starting the full render, qualify subdivisions of an actual long camera interval with original seek and resampling context, repeat owner-loss recovery inside that long camera interval, and measure sustained shared-memory and scratch use. The prior 3,600-picture camera gate and the current mixed gates cover different parts of the saved edit. Physical device loss, other drivers and creative multilayer timelines remain open. The complete project was not rendered.

The final workstation run passed 283 Python tests without skips in 118.485 s. All 34 JavaScript tests passed. The optional Windows package reproduced the real 48-picture mixed master inside the offline editor and cancelled a separate running export with zero owned processes left. The MSI administrative installation contained the checked application code, export runtimes and approved icons. The final SHA-256 comparison matched all 24 linked media files and both saved documents. [Windows and installer checks](../VERIFICATION.md) · [Initial measurements](benchmarks/studio-3.6.0-mixed-export.json) · [Additional measurements and per-picture scores](benchmarks/studio-3.6.0-mixed-qualification.json).

## Reproduction on private media

Prepare the contiguous longer excerpt from the pinned managed v4 copy of the full edit.

```powershell
python benchmarks/phase3a_mixed_range.py $originalManagedV4 $excerpt 6301 7237
python benchmarks/phase3a_mixed_range.py $originalManagedV4 $excerpt 6301 7237 --check
```

The original interval [6301, 7237) preserves 900 pictures across three JPEGs and 36 pictures from a rotated SDR recording. The audit matched all camera packet floors to the managed decoder, preserved each still's source and EXIF orientation, and matched all 748,800 stereo PCM samples per channel to the corresponding intervals on the original timeline. The standalone track ends at frame 7200. Frame 7200 retains the last photograph with 800 silent samples per channel before the next camera and its own audio start at frame 7201.

The actual HDR-to-SDR cut is at frame 50134. The next still starts at 57821, 7687 frames later. The 3600-picture camera minute covers that real cut. The 48-picture fixture combines both camera formats and the photograph, while the 936-picture contiguous range covers the original photo and audio boundaries.

The provisional interval [6283, 7219) failed the audit. Its first seek is 50 ticks beyond the camera's video endpoint on a 1/90,000 clock. The original scene holds the last picture while its audio continues. The rebased managed seek produced too few pictures, and the original and rebased PCM differed in the first 18-picture interval. A later candidate [57785, 59657) also changed PCM when seeking into an ongoing camera span. The tool verifies sample values across the original render contexts before it writes an excerpt.

An excerpt starting at 7200 would have to represent a one-picture 60 Hz photograph hold on the saved 25 Hz still clock. That duration cannot be represented exactly in the v4 document. Starts at 7189 and 7177 have representable static holds. The range builder now keeps a photograph's zero source in-point and shortens its hold, including a cut wholly inside a static image. After that correction the two real ranges still failed independently on PCM when seeking into the music. Starting at the original edit boundary at 6901 preserved all 480,000 original audio sample positions through frame 7501.

The independent managed control supports the authored edit boundaries and an explicitly uninterrupted encoder. The latter records one x265 invocation and a hash of the complete prepared Main10 sequence. Separate worker-pool settings require independently rendered matched controls.

```powershell
python benchmarks/phase3a_mixed_reference.py $project $managed --pool 8 --author-dll $author
python benchmarks/phase3a_mixed_project.py $project $trial "$managed/reference.mp4" $project $worker $runtime --reference-sha256 $managedHash --pool 8 --fast-raster --author-dll $author
python benchmarks/phase3a_mixed_reference.py $project $continuous --continuous --author-dll $author
python mixed_continuous.py $project $continuousDelivery $continuousTrial $worker $runtime $continuous --reference-sha256 $continuousHash --author-dll $author
python benchmarks/phase3a_raster_throughput.py $cameraProject $profile $worker $runtime --frames 103 139
```

Use the uninterrupted managed control to check every decoded picture against the prepared Main10 input. Supply each already encoded comparison master with a separate `--compare-raw-master` argument.

```powershell
python benchmarks/phase3a_mixed_reference.py $project $quality --continuous --pool 8 --audit-raw --compare-raw-master $assembled --author-dll $author
```

The audit checks the canonical raster SHA-256 and the expected picture clock for each input. It records per-picture PSNR, overall PSNR from total sample error, all pictures below 50 dB, and both frames at every seam. Decoded equality to the uninterrupted master is reported independently. The raw file remains temporary. The control and its receipt are retained when the quality gate fails, and the receipt separates time through master delivery from audit time.

The segment experiment pins the project, sources, tooling, color contract, encoder configuration and comparison masters. Each checkpoint binds its verified picture payload and audio sample interval to the exact frame range. Recovery checks the artifact hash before reuse. Assembly renders audio once across the original span schedule, encodes one AAC track, authors the final metadata, and checks every frame. The uninterrupted encode measures the quality effect of encoder state across the joins. A two-worker run requires a passed serial comparison against that same control.

```powershell
$trialArgs = @($project, $scratch, '--frames', 0, 48, '--reference', $reference, '--reference-sha256', $referenceHash, '--continuous-reference', "$continuous/reference.mp4", '--continuous-sha256', $continuousHash, '--author-dll', $author, '--mixed-worker', $worker, '--runtime', $runtime)
python benchmarks/phase3a_segment_resume.py @trialArgs --stop-after 1
python benchmarks/phase3a_segment_resume.py @trialArgs
python benchmarks/phase3a_segment_resume.py @trialArgs --workers 2
```

OpenReel's planner keeps its frame ranges independent of worker count. Its parallel export declines HDR/10-bit delivery. The VlogCraft experiment builds its own HDR checks around existing edit boundaries and a single final audio and metadata timeline. [Upstream planner](https://github.com/Augani/openreel-video/blob/7591221d483b45e98694b02662e66bc1fb33994a/packages/core/src/export/segment-plan.ts) · [Upstream implementation review](phase3a-indexed-export.md)
