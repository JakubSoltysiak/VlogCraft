# Phase 3B qualification handoff

## Scheduler and sharing handoff

Resume from the published head of draft #21 on `codex/studio-3.6.0-phase3b`. The current evidence is in `input_buffer_investigation` in the [ledger](benchmarks/studio-3.6.0-phase3b.json). The preceding checkpoint is `2251870cd2f936c6f982f50432c5ec8ae4529a25`. The playback worker still comes from `d247b6a615ae115296ff834e4214f71b186a5b64`, SHA-256 `3c2651afa4c611b81ae11f3e6b56a859e55f8716e40f3f793e69bac6314c9f1b`. The last physically tested MSI comes from `b42e37630810e880a38dda2b111168b9bd5d11f9`, SHA-256 `8047cde8308fe394abc2fa2c6543d6c02f8b5dd2dc6ed7accfdb34e76daa0cf5`.

**Next decision, GPT-6.2 Astra High.** The 35.196 ms input acquisition spent 35.118 ms waiting. Its operating-system wait object is unknown. A second device read exact NV12 and P010 samples from the true 35-slice decoder pool. Whole-array keyed ownership prevented simultaneous access. The next architectural question is whether an already-decoded slice can remain available while its producer enters the next slow video call. Test this in isolation with directional producer/consumer fences, a retained AVFrame through consumer completion, and documented same-adapter sharing support. Require measured resource bounds, stale-generation suppression, actual pending cancellation/teardown, and byte-exact results on both formats. If a separate GPU copy or allocation is necessary, quantify its per-layer cost and residency before changing the playback path. Preserve the shared-context fallback.

The earlier R→F recorder-off pair failed the gap limit. For a changed worker run the focused floor/rewind, concurrent successor, liveness, seek, cancel and shutdown checks first. Then run one ordinary R→F pair, followed by F→R only after a pass. Keep every attempt. A passing pair and reversal unlock a new MSI and its physical package gates. The ordered 600-second playback, editing smoke and 30-minute editing tests follow those short gates. Use Sol High for bounded qualification once ownership is settled. Treat cache publication at 268 characters and cold mixed-preview preparation as independent work.

### Reproducing the scheduler measurement

The reviewed `inputbuf1` results are complete. A repeat requires a new question and a fresh directory. Set `$py`, the pinned SDK, generated fixtures, MSI paths and hash-verified corrected worker as below in the earlier handoff. These two shells were used for the successful capture. Only the WPR shell requires Administrator privileges. The application stays in the normal desktop session.

```powershell
# Normal shell, once for a fresh cohort. The corrected binary is reused.
$name = 'inputbuf2'
$run = "build/qa/phase3b-watch/$name"
& $py benchmarks/phase3b_stall_campaign.py --results $run refill-prepare --latest-msi $cand4Msi --prior-msi $cand3Msi --diagnostic-worker $worker --media $media --comparison poll-order --hold-arm D
if ($LASTEXITCODE -ne 0) { throw 'Preparation failed' }
```

```powershell
# Administrator shell, at the worktree root. Start only this named collector.
& ./benchmarks/windows/collect-decoder-scheduler.ps1 -RunName inputbuf2
```

```powershell
# Normal shell, as soon as the collector has signalled readiness.
if (!(Test-Path "$run/scheduler.ready")) { throw 'Scheduler has not started' }
& $py benchmarks/phase3b_stall_campaign.py --results $run decoder-attribution
# Wait for the Administrator command to finish saving its ETL before reduction.
& $py benchmarks/phase3b_gpu_events.py "$run/api-gpu.private.etl" "$run/api-attribution-d-stall.private.jsonl" --scheduler-etl "$run/scheduler.private.etl" --output "$run/correlated.json"
```

WPR uses a named instance, 512 × 1024 KiB memory buffers and a 120-second deadline. It stops on the attempt receipt or timeout. The normal runner owns a separate 1536 MiB circular GPU/API trace and stops its own session on exit. Verify zero event loss and same-call coverage before interpreting results. Raw ETLs and acquisition addresses stay local. The reviewed run requires no further elevation.

### Reproducing the isolated probes

```powershell
$sdk = (Resolve-Path 'build/tools/architecture/ffmpeg-shared/ffmpeg-9.0.2-full_build-shared').Path
$zig = (Resolve-Path 'build/tools/architecture/zig/zig-x86_64-windows-0.17.1/zig.exe').Path
$out = (New-Item -ItemType Directory 'build/qa/input-buffer-probes-next').FullName
$env:PATH = "$sdk/bin;$env:PATH"
& $zig c++ -std=c++17 -O2 -target x86_64-windows-gnu benchmarks/windows/decoder-buffer-probe.cpp -ld3d11 -ldxguid -o "$out/buffer-probe.exe"
if ($LASTEXITCODE -ne 0) { throw 'Calibration build failed' }
& $py benchmarks/windows/calibrate_decoder_buffer.py "$out/buffer-probe.exe" "$out/calibration"
if ($LASTEXITCODE -ne 0) { throw 'Calibration failed' }
& $zig c++ -std=c++17 -O2 -target x86_64-windows-gnu benchmarks/windows/decoder-array-sharing.cpp "-I$sdk/include" "-L$sdk/lib" -lavformat -lavcodec -lavutil -lswscale -ld3d11 -ldxgi -o "$out/array-picture.exe"
if ($LASTEXITCODE -ne 0) { throw 'Sharing probe build failed' }
foreach ($fixture in @('h264-4k60-0.mp4','hevc10-4k5994.mp4')) {
    & $py benchmarks/run_qa.py --results "$out/$fixture-result" --timeout 30 --status "$out/status.json" -- "$out/array-picture.exe" (Join-Path $media $fixture)
    if ($LASTEXITCODE -ne 0) { throw 'Sharing probe failed' }
}
```

The following sections preserve historical campaigns and their original gates.

Use [draft PR #21](https://github.com/JakubSoltysiak/VlogCraft/pull/21) and its published head on `codex/studio-3.6.0-phase3b`. The [current playback report](STUDIO_3_6_0_PHASE3B_PLAYBACK.md) gives the diagnosis and short-gate status. The [benchmark record](benchmarks/studio-3.6.0-phase3b.json) records the build commit, native-source digest, development MSI hash and extracted host and playback worker hashes for the tested candidate in `refill_investigation.candidate_identity`. Earlier tests remain in `readiness_investigation` and `freeze_investigation`.

**Long qualification remains blocked.** All three protected trials missed 59.5 FPS, two exceeded the skip and active-gap limits, and the ordinary 958 × 539 preview measured a 1.193 s gap. Retain all attempts and the original wall-time definition.

The packaged implementation is `b42e37630810e880a38dda2b111168b9bd5d11f9`. Its MSI SHA-256 is `8047cde8308fe394abc2fa2c6543d6c02f8b5dd2dc6ed7accfdb34e76daa0cf5` and playback worker SHA-256 is `152866b9a0ba6d9b4722e7e567ad1299d8a10a2cba6cd7b3160117c1178452f3`. The immediate comparison is `cand3` from published `5900849`, MSI `2f9de210fe88a2e4903e679bb61e081201973b073f20bba2bce3cf14bc0b8266`. The separate earlier control is `cand1` from published `28c0abf`, MSI `4d82887f41389b458278056970e12a49319850b0fb13df281c1f36fe947e9bd4`. Keep `b817372` historical.

## Decision and fixtures

Use the same Windows workstation and Phase 3B worktree. Select GPT‑6.2 Sol with High reasoning for the subsequent local qualification. Keep the workstation on AC and the editor visible, foreground and unobscured. Keep user projects and the installed app out of the run. Use a fresh editor process and project for each attempt with the frozen administrative MSI image. Leave OS file caches unmanaged and run without competing builds, exports or other measurements.

The local QA scripts and receipts are in the worktree's ignored `build/qa/phase3b-watch` directory. The three original generated clips are `h264-4k60-{0,1,2}.mp4` in `build/qa/architecture/media` of the main checkout. The 30-minute driver is [benchmarks/phase3b_editing_qualification.py](../benchmarks/phase3b_editing_qualification.py). The local launcher resolves Python and the fixture paths through the retained trial driver. The private original manifest and its paths remain in the prior local QA tree.

```powershell
$commonGit = git rev-parse --path-format=absolute --git-common-dir
$py = Join-Path (Split-Path -Parent $commonGit) '.venv/Scripts/python.exe'
$handoff = 'build/qa/phase3b-watch/handoff.py'
$candidate = 'cand4'
& $py $handoff plan --candidate $candidate
```

Use the published candidate trial prefix as `$candidate`. The plan lists each failed or missing prerequisite. Keep endurance blocked while any prerequisite remains open.

## Matched editor-size refill diagnostic

Run the 60-second three-layer UHD60 composition at the ordinary 958 × 539 physical preview. Arm A uses the original refill deferral. Arm B sets `VLOGCRAFT_DIAGNOSTIC_NO_REFILL_HOLD=1`. Both use the same instrumented worker in a clone of the verified `cand3` administrative image. The preparation also verifies the separate `cand1` package for packaged editor-size comparisons. Start with A then B. Review that pair before starting B then A. Stop after two pairs or when the controls fail, and retain all attempts.

```powershell
$campaign = 'build/qa/phase3b-watch/campaign.py'
$cohort = 'nextdiag'
& $py $campaign diag-build --label $cohort
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $py $campaign refill-setup --label $cohort
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $py $campaign refill-pair --label $cohort --slot 1
& $py $campaign refill-review --label $cohort --slot 1
```

The review receipt is `build/qa/phase3b-watch/$cohort/pair-1-review.json`. Check both arms' window, AC, exact audio, geometry, process cleanup and flag controls. Compare wall-time FPS, active presentation gaps and skips, then check the coherent request and adjacent Present interval. Inspect the exact queued PTS headroom and the sampled wait, device lock and decoder progress across the three layers. Check torn lanes, missing requests, sampling gaps and any transport transition before attributing delay.

```powershell
# Run after the first pair's evidence has been reviewed and its controls passed.
& $py $campaign refill-pair --label $cohort --slot 2
& $py $campaign refill-review --label $cohort --slot 2
```

Use a fresh label if a later bounded experiment is warranted. If the evidence calls for a polling-order comparison, use a worker that implements `VLOGCRAFT_DIAGNOSTIC_LEGACY_POLL_ORDER=1`, then add `--comparison poll-order --hold-arm B` to `refill-setup`. Use slot 1 once. Both arms will have refill deferral disabled. Use `--hold-arm A` when the comparison instead calls for retaining the original refill behavior in both arms.

For a comparison of the original and independently expiring holds, build a worker that supports `VLOGCRAFT_DIAGNOSTIC_LEGACY_REFILL_HOLD=1`, then prepare a fresh label with `refill-setup --comparison bounded`. Use slot 1 once. Arm A sets the legacy hold and arm D uses the expiring hold in the same worker.

## Decoder input buffer investigation

The C→D and D→C comparisons are complete. Keep the existing source-first polling and independently expiring refill. The guarded rollback worker built from `d247b6a` reached 59.766 FPS, five skips and a 104.604 ms active gap in the original recorder-off editor. Its gate blocks a new MSI and both endurance stages. The older MSI identities below and in the refill section refer to their original campaigns.

Continue with the corrected worker and the existing 958 × 539 three-layer fixture. In a bounded attribution rerun, Direct3D11 GetDecoderBuffer for picture parameters took 65.95 ms while the calling decoder held the shared device. The two peers waited for at least 46.18 ms of that call. The retained ETL already shows that the previous fence-bearing packet on this thread stopped 2.83 ms into the 65.95 ms call. Reuse of the same recorded output pointer did not uniquely identify a physical input-buffer fence. No DxgKrnl CPU wait event appeared on that thread during the call. The next measurement needs context switches, ready-thread and wait-state attribution covering the very same video call, plus GPU/API events. The current non-elevated token denied kernel context-switch collection. Use a Windows trace session authorized for those providers and report any lost events and unmatched resource identities. Examine whether a supported driver readiness signal or independent device/context design can avoid blocking peer decoders while preserving documented D3D11 synchronization and zero-copy ownership. Retain the current synchronization until an isolated alternative has an exact output and cancellation test.

The following tracked commands reproduce one fixed-policy attribution run. Set `$py` to the QA interpreter, `$media` to the existing generated clip directory, and the MSI variables to the hash-verified cand4 and cand3 packages. Prepare the pinned lab Zig/shared FFmpeg SDK in the checkout first. Choose a fresh local result directory. Use the existing polling worker at revision `2e6b218` for the historical C/D comparison or the corrected implementation at `d247b6a` for the current investigation. The build receipt binds the active native inputs and worker hash.

```powershell
$runner = 'benchmarks/phase3b_stall_campaign.py'
$run = 'build/qa/phase3b-decoder-input-next'
& $py $runner --results $run refill-build
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $py $runner --results $run refill-prepare --latest-msi $cand4Msi --prior-msi $cand3Msi --diagnostic-worker "$run/VlogCraftNative.exe" --media $media --comparison poll-order --hold-arm D
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $py $runner --results $run decoder-attribution
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $py benchmarks/phase3b_gpu_events.py "$run/api-gpu.private.etl" "$run/api-attribution-d-stall.private.jsonl" --output "$run/correlated.json"
```

For a new justified correction use a fresh directory, the same build command and `refill-prepare --comparison ordinary` with both MSI paths, worker and fixtures as above. Run `refill-pair --slot 1` and `refill-review --slot 1`. Only a passing candidate qualifies for `refill-pair --slot 2 --reverse-reviewed` and its review. Keep the original thresholds, every raw receipt and each packaged baseline. The separate Windows cache publication and cold mixed-preview tasks remain below.

## Recorder campaign from a fresh checkout

Point `$latestMsi` and `$priorMsi` to the retained `cand3` and `cand1` development packages identified above. Point `$media` to the established generated fixture directory and `$py` to the QA Python environment. The command builds the original A/B diagnostic source with the pinned Zig 0.17.1 and FFmpeg 9.0.2 shared SDK.

```powershell
# Set up the pinned toolchain if the checkout does not have it.
& $py tools/setup_architecture_lab.py --component zig --component ffmpeg-shared
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$sdk = (Resolve-Path 'build/tools/architecture').Path
$zig = Join-Path $sdk 'zig/zig-x86_64-windows-0.17.1/zig.exe'
$ffmpeg = Join-Path $sdk 'ffmpeg-shared/ffmpeg-9.0.2-full_build-shared'
$workerFolder = New-Item -ItemType Directory -Path 'build/qa/phase3b-next-worker'
$worker = Join-Path $workerFolder.FullName 'VlogCraftNative.exe'
$diagnosticRef = '67c2033233d9b59733fc336c01f8e61ad52baec3'
$archive = Join-Path $workerFolder.FullName 'diagnostic-source.tar'
git archive --format=tar --output=$archive $diagnosticRef native
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
tar -xf $archive -C $workerFolder.FullName
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$workerSource = Join-Path $workerFolder.FullName 'native/player.cpp'
& $zig c++ -std=c++17 -O2 -target x86_64-windows-gnu $workerSource "-I$ffmpeg/include" "-L$ffmpeg/lib" -lavformat -lavcodec -lavutil -lswscale -ld3d11 -ldxgi -o $worker
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
git rev-parse $diagnosticRef
Get-FileHash -Algorithm SHA256 -LiteralPath $worker
$run = 'build/qa/phase3b-next-recorder'
$campaign = 'benchmarks/phase3b_stall_campaign.py'
& $py $campaign --results $run refill-prepare --latest-msi $latestMsi --prior-msi $priorMsi --diagnostic-worker $worker --media $media
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $py $campaign --results $run refill-pair --slot 1
& $py $campaign --results $run refill-review --slot 1
# Run after reviewing the first pair and confirming that its controls passed.
& $py $campaign --results $run refill-pair --slot 2
& $py $campaign --results $run refill-review --slot 2
```

The preparation verifies both MSIs and their extracted host and worker hashes, then clones the latest image with a single worker replacement. It hashes the generated clips at setup and checks fixture metadata around each run. Each diagnostic arm uses a fresh editor process and project. The earlier protected recorder campaign remains available through the tracked launcher's `prepare` and `trial` commands with `--baseline cand1` at preparation.

```powershell
& $py benchmarks/phase3b_stall_evidence.py "$run/pair-1-1-a-stall.private.jsonl" --output "$run/pair-1-1-a-stall-summary.json"
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
$evidence = (Get-Content -Raw 'docs/benchmarks/studio-3.6.0-phase3b.json' | ConvertFrom-Json).refill_investigation
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
