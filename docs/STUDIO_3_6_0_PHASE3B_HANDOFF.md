# Phase 3B qualification handoff

Use [draft PR #21](https://github.com/JakubSoltysiak/VlogCraft/pull/21) and its published head on `codex/studio-3.6.0-phase3b`. The [current playback report](STUDIO_3_6_0_PHASE3B_PLAYBACK.md) gives the diagnosis and short-gate status. The [benchmark record](benchmarks/studio-3.6.0-phase3b.json) records the build commit, native-source digest, development MSI hash and extracted host and playback worker hashes for the tested candidate in `readiness_investigation.candidate_identity`. The previous tests remain in `freeze_investigation`.

**Long qualification remains blocked.** The revised MSI missed 59.5 FPS in all three protected trials. The third also exceeded the 100 ms active-gap cap. Preserve every attempt and the existing wall-time definition. Begin with an onset-centered comparison at the ordinary 958 × 539 preview, which also failed on both revised MSI candidates. Compare Present duration, the refill-hold state and each acquired successor. Test a bounded refill deferral only if it addresses the observed interval and protects existing VFR, rewind and audio semantics.

The packaged implementation for this follow-up is `7086ed380d279855b2d81f87d4d2105e268b6335`. Its MSI SHA-256 is `2f9de210fe88a2e4903e679bb61e081201973b073f20bba2bce3cf14bc0b8266` and playback worker SHA-256 is `2251ac360af922971b0fbcde1a08eb2b4693e7f994e8bf77bf44d1897c0f36a6`. For comparing to the previous published checkpoint, use `cand1` and its MSI `4d82887f41389b458278056970e12a49319850b0fb13df281c1f36fe947e9bd4`. The older `b817372` image is a separate historical control.

## Decision and fixtures

Use the same Windows workstation and Phase 3B worktree. Select GPT‑6.2 Sol with High reasoning for the subsequent local qualification. Keep the workstation on AC and the editor visible, foreground and unobscured. Keep user projects and the installed app out of the run. Use a fresh editor process and project for each attempt with the frozen administrative MSI image. Leave OS file caches unmanaged and run without competing builds, exports or other measurements.

The local QA scripts and receipts are in the worktree's ignored `build/qa/phase3b-watch` directory. The three original generated clips are `h264-4k60-{0,1,2}.mp4` in `build/qa/architecture/media` of the main checkout. The 30-minute driver is [benchmarks/phase3b_editing_qualification.py](../benchmarks/phase3b_editing_qualification.py). The local launcher resolves Python and the fixture paths through the retained trial driver. The private original manifest and its paths remain in the prior local QA tree.

```powershell
$commonGit = git rev-parse --path-format=absolute --git-common-dir
$py = Join-Path (Split-Path -Parent $commonGit) '.venv/Scripts/python.exe'
$handoff = 'build/qa/phase3b-watch/handoff.py'
$candidate = 'cand3'
& $py $handoff plan --candidate $candidate
```

Use the published candidate trial prefix as `$candidate`. The plan lists each failed or missing prerequisite. If any is listed, the next run is a protected 60-second diagnostic. Reopen the longest relevant native recorder window and line up the last returned submission, current renderer or decoder stage, packet and queue progress, and device lock state. Check recorder discontinuities, torn observations, transition flags and recovery coverage. When the recorder leaves the interval unresolved, repeat the same-binary capture with the specific missing observation added. A short arm that lost AC or visibility must be repeated under the declared conditions.

```powershell
$campaign = 'build/qa/phase3b-watch/campaign.py'
& $py $campaign diag-build --label nextdiag
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $py $campaign diag-setup --label nextdiag
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $py $campaign diag-on --label nextdiag --slot 1
```

Use a fresh campaign label or an unused slot in a retained diagnostic cohort for the next bounded experiment. Review each capture before scheduling another.

## Recorder campaign from a fresh checkout

Point `$frozenMsi` to the development MSI with SHA-256 `4d82887f41389b458278056970e12a49319850b0fb13df281c1f36fe947e9bd4`. Point `$media` to the established generated fixture directory and `$py` to the QA Python environment. Build the diagnostic worker at the implementation under review. The command uses the pinned Zig 0.17.1 and FFmpeg 9.0.2 shared SDK from the existing architecture tool setup.

```powershell
# Set up the pinned toolchain if the checkout does not have it.
& $py tools/setup_architecture_lab.py --component zig --component ffmpeg-shared
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$sdk = (Resolve-Path 'build/tools/architecture').Path
$zig = Join-Path $sdk 'zig/zig-x86_64-windows-0.17.1/zig.exe'
$ffmpeg = Join-Path $sdk 'ffmpeg-shared/ffmpeg-9.0.2-full_build-shared'
$workerFolder = New-Item -ItemType Directory -Path 'build/qa/phase3b-next-worker'
$worker = Join-Path $workerFolder.FullName 'VlogCraftNative.exe'
& $zig c++ -std=c++17 -O2 -target x86_64-windows-gnu native/player.cpp "-I$ffmpeg/include" "-L$ffmpeg/lib" -lavformat -lavcodec -lavutil -lswscale -ld3d11 -ldxgi -o $worker
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
git rev-parse HEAD
Get-FileHash -Algorithm SHA256 -LiteralPath $worker
$run = 'build/qa/phase3b-next-recorder'
$campaign = 'benchmarks/phase3b_stall_campaign.py'
& $py $campaign --results $run prepare --frozen-msi $frozenMsi --diagnostic-worker $worker --media $media
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $py $campaign --results $run trial frozen --slot 1
& $py $campaign --results $run trial off --slot 1
& $py $campaign --results $run trial on --slot 1
```

The preparation verifies the frozen MSI and binaries and keeps a separate diagnostic image with a single replacement worker. It hashes the generated clips during setup. Each trial starts the unchanged protected workload. Retain every attempt, including failures, and compare recorder-on and recorder-off runs with the same worker. Repeat recorder-on with slots 2 through 6 until the campaign reaches its limit or a native gap of at least 500 ms has reviewed before, during and recovery coverage. The recorder may trigger on a shorter stall while waiting for that stopping condition. The pre-fix campaign stopped at its third recorder-on trial after capturing a 1.039-second submission gap at frame 2307.

```powershell
& $py benchmarks/phase3b_stall_evidence.py "$run/on-1-stall.private.json" --output "$run/on-1-stall-summary.json"
```

For an interrupted worker, inspect the `.live` mirror when present. The reducer reports relative times, coverage exclusions, observed lane and device overlap, source readiness and GPU progress. Its paired observations tolerate gaps of at most 30 ms and exclude torn lanes. Intervening device events and thread scheduling remain unobserved. Per-lane durations overlap. Keep full captures, identifiers and supervisor logs local.

## 600-second playback and 30-minute editing

Run the following only when the plan passes. The launcher checks the published package identity against the retained MSI and extracted image, verifies the native source digest, and uses the same serial lock as the short campaign. Use a fresh `--label` for a retry.

```powershell
& $py $handoff endurance --candidate $candidate --label long1
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $py $handoff editing-smoke --candidate $candidate --label long1
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $py $handoff editing --candidate $candidate --label long1
```

On a fresh checkout, use the tracked drivers directly after reviewing every short prerequisite in the published record. Point `$candidateMsi` and `$exe` to the retained MSI and the corresponding verified administrative image executable.

```powershell
$evidence = (Get-Content -Raw 'docs/benchmarks/studio-3.6.0-phase3b.json' | ConvertFrom-Json).readiness_investigation
$identity = $evidence.candidate_identity
$native = Join-Path (Split-Path $exe) '_internal/engine/native/VlogCraftNative.exe'
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $candidateMsi).Hash -ne $identity.msi_sha256 -or
    (Get-FileHash -Algorithm SHA256 -LiteralPath $exe).Hash -ne $identity.host_sha256 -or
    (Get-FileHash -Algorithm SHA256 -LiteralPath $native).Hash -ne $identity.worker_sha256) {
    throw 'Candidate artifact fingerprint mismatch'
}
$run = 'build/qa/phase3b-long1'
if (Test-Path $run) { throw 'Use a fresh result directory' }
Remove-Item Env:VLOGCRAFT_STALL_CAPTURE,Env:VLOGCRAFT_NATIVE_TRACE_FILE -ErrorAction SilentlyContinue
& $py benchmarks/run_qa.py --timeout 740 --results "$run/playback-supervisor" --status "$run/status.json" -- $py benchmarks/native_playback.py $exe $media "$run/playback" --seconds 600 --width 3840 --rate 60/1 --cut .5 --layers 3 --window-mode visible --trace
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

Review the long playback receipts against the endpoint and timing criteria below before starting the editing runs.

```powershell
& $py benchmarks/run_qa.py --timeout 180 --results "$run/editing-smoke-supervisor" --status "$run/status.json" -- $py benchmarks/phase3b_editing_qualification.py $exe $media "$run/editing-smoke" --smoke
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $py benchmarks/run_qa.py --timeout 2100 --results "$run/editing-supervisor" --status "$run/status.json" -- $py benchmarks/phase3b_editing_qualification.py $exe $media "$run/editing"
```

| Run | Required observations |
| --- | --- |
| 600-second playback | Three picture and three audio layers at 3840 × 2160 and 60/1 with the original synchronized cuts and source offsets, 356 × 200 physical preview, final completed frame 35,999, and exactly 28,800,000 PCM sample frames with zero underruns. Track all 36,000 expected sequence positions and report any skips. Review the existing 59.5 distinct FPS and 100 ms active-gap screens alongside p95/p99, fixed-width throughput windows, visibility, power samples and zero owned survivors. |
| 90-second editing smoke | Nine edit batches on the existing 125-second editable timeline. Exercise playback resets, at least one committed ruler drag, round-trip persistence, zero observed segment underruns and process release. |
| 30-minute editing | 180 edit batches, exact reopening of the project with 80 undo entries, correct edit and undo/redo contents, one recovery checkpoint per measured ruler drag, zero observed segment underruns, visible operation on AC and zero owned survivors. Each transport restart has its own audio generation. Preserve the segment sample and underrun counters. Record natural idle for 60 seconds and measure native/worklet release on stop. |

Retain `long1-endurance600/native-playback.json`, its decision and supervisor receipts, and `long1/editing-1800/{memory,memory-summary}.json` under the watch directory. Keep working set, private commit, WebView role, JavaScript heap and potentially overlapping GPU allocation measures separate. Review the 30-second medians and late-slope intervals, and compare active, stopped, natural-idle and native-released points. Report an unresolved memory trend if sustained growth persists. The transport bounds remain three live decoders, two idle owners, one pending cold initialization and 896 MiB inactive texture reservation, with at most four queued pictures per producer including incoming and outgoing rewind pictures. Report each attempt with its package identity and observed conditions.

## Separate Windows cache-path task

Run this in its own Sol session. The frozen implementation and the follow-up used the same cache-publication code. The retained mixed monitor fixture rendered, then reported Windows error 3 in `PreviewCache._render` at `os.replace(dest, job['path'])`. The absolute temporary path was 226 characters and the cache destination was 268. The cache directory was 199 characters, with `range-xxxxxxxx/program.mp4` on one side and the 64-character cache key plus `.mp4` on the other. The short-path control rendered and played; the 149.75-second cold readiness cost remains a separate observation.

```powershell
& $py $handoff cache-probe --label cache1
```

The launcher uses the frozen `b817372` administrative image and the existing mixed preview fixture. It runs the short-path control before the 140-character benchmark output path that recreates the 226-to-268 boundary. It verifies the three original hashes and modification times before and after media access. Inspect the private supervisor logs and retain the exact error code and both lengths in sanitized evidence.

Keep a targeted regression that creates a genuine short render, exercises publication at and around the failing Windows boundary, verifies the ready status, decoded picture count and cache re-open, then checks cancellation and temporary cleanup. Recheck the packaged process and the same short-path control. Preserve atomic replacement, cache integrity checks and normal eviction. The long playback, long editing, physical GPU recovery, calibrated HDR display and full 60-second mixed HDR10+ delivery remain separate qualification work.
