# First export of a saved camera range

The Windows qualification tool runs the existing Phase 3A D3D11 pipeline against a continuous excerpt from the audited minute of the saved vlog. It preserves UHD60, libx265 Slow, CRF 20, the saved 60 Mb/s field, the managed color contract, and the existing audio graph. It adds upright limited-range BT.709 HEVC Main 4:2:0 to the probed source formats for this experiment. Clockwise HEVC Main10 PQ retains its existing source support. Admission requires one or two opaque straight-cut camera clips on one visible track, at most 120 pictures, and the existing Radeon 890M delivery checks. The new policy is available through the benchmark command.

A single picture span connects the native worker's binary stdout directly to FFmpeg's stdin. At UHD60 that removes the Python read/write relay for 24,883,200 bytes per frame. Two spans use the existing relay to enforce the split between their x265 encoders. The encoder, picture-clock checks, native completion receipt, independent PCM check, decoded-picture HDR10+ authoring, and the sampled 50 dB threshold still govern delivery. Rejected candidates fall back to the managed renderer. The pipeline still reads packed pictures back from the GPU and encodes them on the CPU with x265.

The tool accepts a v4 saved test copy with the audited PQ mastering contract and explicit square-pixel interpretation. It starts at an original render-span boundary, preserves the original clip starts, and permits shortening the end of a clip on its source tick grid. It rejects an opening trim inside an active clip to preserve video preroll and audio history. Before starting the worker, the tool maps every planned request to its original managed span seek. During the GPU export the independent FFmpeg cadence trace checks every selected source PTS. The tool checks project bytes and linked-file identities at the end.

## 48-picture result on Radeon 890M

| Measure | D3D11 first export | Managed reference |
|---|---:|---:|
| Export through verification and publication | 84.183 s | 105.123 s |
| Delivered bytes | 675,727 | 678,911 |

The D3D11 first export took 19.9% less wall time. The independent full comparison took 3.590 s and measured 54.59 dB overall and 53.47 dB minimum PQ PSNR. Both deliveries had matching picture PTS, static HDR, 48 HDR10+ picture records and decoded stereo PCM through exactly 38,400 samples per channel. The native and software cadence checks agreed on all original source pictures. The pinned project and the linked media identities matched after both exports.

Preparation took 9.573 s. The native worker spent 3.949 s including direct pipe backpressure, with 0.054 s in resident decode and 0.221 s of source normalization, and reported zero CPU source-frame transfers. The render took 58.924 s, including 58.359 s feeding and waiting for x265. Authoring took 1.930 s and the additional first-export delivery checks took 13.743 s. x265 reported CRF 20 and an average video rate of 6,495 kb/s for the native encode. This export still runs below one output picture per wall second. The pair measures resident rendering and direct transport together.

The initial 120-picture PQ attempt reached the 90-second software source probe limit and entered the reference workflow. The managed fallback delivered in 190.193 s. The failed attempt and fallback took 280.266 s together. Late HEVC MP4 trims now have an experimental bounded packet index. The index sorts integer presentation timestamps into display order and rejects missing, duplicate, discarded or negative clock records. The resident decoder checks every decoded prefix PTS before it can use the index. The independent software cadence and picture-quality checks remain in force.

## Serial qualification on Radeon 890M

Set `$section` to the retained one-minute run’s `section/source-project.json`. Set `$sdk` to the directory containing the previously built resident `VlogCraftProject.exe`, `hdr-statistics.dll`, and FFmpeg shared runtime. Run these from the export worktree after other playback and export workloads have released the workstation.

```powershell
$worker = Join-Path $sdk 'VlogCraftProject.exe'
$runtime = Join-Path $sdk 'ffmpeg-shared/ffmpeg-9.0.2-full_build-shared/bin'
$stats = Join-Path $sdk 'hdr-statistics.dll'
$run = Join-Path 'build/qa' ('camera-qualification-' + (Get-Date -Format yyyyMMdd-HHmmss))

python benchmarks/phase3a_camera_range.py $section (Join-Path $run 'sdr48') --frames 2314 2362 --worker $worker --runtime $runtime --author-dll $stats
```

Inspect `sdr48/qualification.json` before the second arm. The GPU attempt runs first without a comparison master. The matched reference runs next with the same settings and author. The final check compares every decoded PQ picture, video PTS, static HDR, per-picture dynamic metadata count and decoded PCM. Both overall and minimum per-frame PQ PSNR must reach 50 dB. The two export times exclude this additional independent comparison, which is timed separately. If the GPU attempt is rejected, the receipt records the fallback and any rejected master available for the comparison.

```powershell
python benchmarks/phase3a_camera_range.py $section (Join-Path $run 'pq-cut120') --frames 0 120 --worker $worker --runtime $runtime --author-dll $stats
```

The second range covers a cut between two trims of the rotated PQ source. It retains both original seeks and avoids the six terminal holds documented in the separate HDR-to-SDR cut. The current source preparation cap and requirement for a successor picture remain in force. The first and second ranges expect 38,400 and 96,000 samples per audio channel respectively.

To reuse the measured fallback for the independent post-export comparison, set `$prior` to the completed fallback's run directory, `$pin` to the original project and linked-file identity receipt, and `$referenceHash` to the recorded SHA-256 of that fallback's `first-export.mp4`. The harness checks the source identity, byte-identical range project, settings, range bounds and file hash after the candidate finishes.

```powershell
python benchmarks/phase3a_camera_range.py $section (Join-Path $run 'pq-cut120-packets') --frames 0 120 --worker $worker --runtime $runtime --author-dll $stats --retained-reference $prior --pinned-sources $pin --reference-sha256 $referenceHash
```

After a successful SDR arm, this command exercises the same direct pipe with injected device removal. The qualification compares the delivered fallback with a separately rendered reference and checks that the worker reported the injected fault.

```powershell
python benchmarks/phase3a_camera_range.py $section (Join-Path $run 'sdr12-fault') --frames 2314 2326 --worker $worker --runtime $runtime --author-dll $stats --fault-frame 2
```

The original generated Phase 3A control remains available through the existing CLI. Use the 48-picture saved Phase 3A fixture and its retained matched reference for the full comparison.

```powershell
python benchmarks/phase2d_project_export.py $phase3a48 (Join-Path $run 'phase3a48.mp4') --backend d3d11 --first-time --worker $worker --runtime $runtime --author-dll $stats --report (Join-Path $run 'phase3a48.json') --resources
python tests/windows_phase3a_export.py $developmentEditor $phase3a48 $phase3a48Reference (Join-Path $run 'packaged-phase3a48')
```
