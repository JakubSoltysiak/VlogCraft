# Mixed camera, photograph and audio export

The private UHD60 edit contains 10 camera clips, 18 PNG/JPEG stills and four standalone audio clips. The [previous camera qualification](phase3a-camera-raster.md) covers 600 and 3,600 pictures on Radeon 890M. All workstation experiments below use the saved HEVC Main10 Slow CRF 20 profile, BT.2020/PQ and software x265. Each performance trial runs separately on AC.

## What changed

The opt-in mixed provider walks the existing render boundaries. A neutral opaque camera span can use the existing indexed D3D11 decoder and reference-equivalent zimg raster. The managed picture graph handles a photograph's color interpretation, EXIF orientation, framing, alpha and opacity. Original source PTS stay on the original timeline even when camera spans are separated by a photograph. The normal renderer owns the audio graph and AAC delivery. The provider checks each independently encoded span for an IDR start, compatible decoder configuration and exact local picture clocks. HDR10+ is authored from the assembled final decoded pictures.

The faster path keeps three FP32 color planes for an opaque rotated camera and reuses constant letterbox margins. An eligible static still needs one fully composed, quantized Main10 picture per span. The enhanced provider repeats that picture before x265, retaining its original frame count and clock. Per-picture creative changes use the full graph. The fast verifier independently re-renders each selected static-still instant through the original graph. A separate decode compares every exported picture with the matched managed master.

## Archived 48-picture control and photograph color

The archived 48-picture mixed excerpt used 12 photograph pictures with standalone audio, 18 rotated PQ camera pictures and 18 upright SDR camera pictures. Its original managed export took 136.190 s. The initial mixed provider reproduced all 48 coded/decoded pictures, all dynamic records and 38,400 stereo samples per channel. Its delivery took 132.370 s, including 55.456 s of first-export checks. This established equivalence with the archived edit.

Inspecting the ICC tags disclosed a shared color error in that reference. The real JPEGs use P3-D65 colorants and sRGB transfer curves. The old renderer recognized “sRGB” in the ICC description and selected BT.709 primaries. Reproducing its pixels alone could not detect the mistake. These legacy measurements remain comparisons to that historical interpretation. The corrected managed and accelerated qualification uses the actual embedded primaries, including the three EXIF-orientation-6 photographs in the longer range. Generic transparent PNGs, a nontrivial opacity and the saved explicit sRGB interpretation have separate regression coverage. The numeric checks use the registered Display P3 primaries, D65 white and piecewise transfer function. [ICC Display P3 definition](https://registry.color.org/rgb-registry/displayp3) · [FFmpeg zscale mapping](https://ffmpeg.org/doxygen/trunk/vf__zscale_8c_source.html).

## Raster and encoding measured separately

One 36-picture interval from the failing historical encoder span supplied the same actual Main10 input on disk to each encoder. Capturing the indexed source planes took 1.693 s. The control raster including sequential raw output took 39.496 s. The RGB-only raster with cached margins took 34.114 s and produced identical bytes. Encoding the prepared pictures without the raster took 31.318 s with two pool workers and 9.101 s with eight. Both used two frame threads, WPP and the same mastering declarations. These are isolated stage timings. Rasterization and encoding overlap during delivery.

FFmpeg could not negotiate a float-RGB `pad` filter. Four-thread zimg conversion also changed the quantized input. Isolating four threads separately at input linearization, bilinear resize and final PQ conversion changed pixels in each case on the twelve-picture control. The selected optimization retains single-thread zimg kernels. Prior results, including the rejected packed-GPU exports, remain in the [encoder-input report](phase3a-camera-raster.md).

## Independent delivery measurements

All 48 pictures matched their corrected managed master in both the original edit-boundary encoder and the single uninterrupted encoder. The latter also matched every byte of the independently prepared Main10 encoder input. The first export with edit-boundary encoders reached the authored master in 65.337 s and used 50.116 s for additional verification. Its total was 115.474 s, followed by 3.721 s for independent comparison. The managed edited control took 88.789 s. These small jobs spend a substantial fraction of delivery on verification.

| Corrected mixed excerpt | Delivery or qualification time | Sampled peak process-tree working set |
|---|---:|---:|
| Managed, original edit boundaries | 88.789 s | 3.41 GiB |
| Indexed camera and prepared still, including independent checks | 119.205 s | 2.50 GiB |
| Managed, one uninterrupted x265 context with a disk-backed raw oracle | 96.957 s including control preparation | 2.72 GiB |
| Indexed camera and prepared still, one uninterrupted context with full checks | 117.920 s | 2.98 GiB |
| Cold independent segments, serial, both references checked | 103.764 s | 2.50 GiB |
| Cold independent segments, two workers, both references checked | 75.778 s | 3.65 GiB |

Independent segments started at pictures 0, 12 and 30. The joined output preserved all 48 original segment packets and isolated segment decodes. Against the uninterrupted encode, the minimum per-picture PSNR was 54.24 dB and overall PSNR was 55.892 dB. All 48 pictures matched the separately managed encode with the same cuts. Its 48 HDR10+ records matched exactly. The uninterrupted encode reconstructed slightly different pixels in every frame, and its 48 dynamic records accordingly differed. PCM, sample endpoints and static HDR matched both references.

A separate serial export was stopped immediately after its first verified segment. Restart reused that segment, encoded the other two, and passed both references. The declared two-worker memory check requires twice the observed serial segment process-tree working set to be available.

The optional project-export runtime exposes **Mixed cameras and stills · exact master** in the export dialog. The user selects a matched local master. The editor uses the saved Slow CRF 20 profile, checks every decoded picture, audio sample, video and AAC packet clock, and final HDR10+ payload, and publishes only an accepted candidate. The existing managed renderer handles unsupported projects and verification failures. The uninterrupted and restartable segment experiments remain accessible through their qualification commands.

## Contiguous 936-picture first export

The edited source interval contains three EXIF-rotated P3-D65 photographs, standalone 44.1 kHz audio, and a rotated HEVC SDR camera with its own 48 kHz audio. The managed control took 552.828 s. The indexed camera and prepared-still route reached the authored master in 245.599 s and completed its own checks in 293.290 s. Independent decoding and coded-picture comparison extended elapsed time to 324.872 s, 41.2% below the original managed delivery time even with this extra check. Both trials peaked near 5.09 GiB of sampled process-tree working set.

All 936 coded pictures, 936 independent picture decodes, 936 HDR10+ records, static declarations and 748,800 decoded PCM samples per channel matched the managed master. The provider separately checked all 36 original camera selections, including four repeated PTS selections. The lowest of 13 comparisons with uncompressed input was 52.457 dB. The three eligible static holds and a one-picture still interval accounted for 190.138 s of picture encoding. Indexed camera encoder feed and wait consumed 27.678 s. Final metadata authoring took 25.726 s.

## Reproduction on private media

Prepare the contiguous longer excerpt from the pinned managed v4 copy of the full edit.

```powershell
python benchmarks/phase3a_mixed_range.py $originalManagedV4 $excerpt 6301 7237
python benchmarks/phase3a_mixed_range.py $originalManagedV4 $excerpt 6301 7237 --check
```

The original interval [6301, 7237) preserves 900 pictures across three JPEGs and 36 pictures from a rotated SDR recording. The audit matched all camera packet floors to the managed decoder, preserved each still's source and EXIF orientation, and matched all 748,800 stereo PCM samples per channel to the corresponding intervals on the original timeline. The standalone track ends at frame 7200. Frame 7200 retains the last photograph with 800 silent samples per channel before the next camera and its own audio start at frame 7201.

The actual HDR-to-SDR cut is at frame 50134. The next still starts at 57821, 7687 frames later. The 3600-picture camera minute covers that real cut. The 48-picture fixture combines both camera formats and the photograph, while the 936-picture contiguous range covers the original photo and audio boundaries.

The provisional interval [6283, 7219) failed the audit. Its first seek is 50 ticks beyond the camera's video endpoint on a 1/90,000 clock. The original scene holds the last picture while its audio continues. The rebased managed seek produced too few pictures, and the original and rebased PCM differed in the first 18-picture interval. A later candidate [57785, 59657) also changed PCM when seeking into an ongoing camera span. The tool verifies sample values across the original render contexts before it writes an excerpt.

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
