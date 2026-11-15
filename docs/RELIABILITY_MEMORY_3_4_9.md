# WebView reliability and memory ownership — 3.4.9

**WORK IN PROGRESS — QUALIFICATION INCOMPLETE.** Finalization checkpoint preserves the existing 3.4.9 work before further qualification. Final installed MSI: `05bcdbd1abaa0e68f1ac2ad6df73511f5acdfcf60b8dfc07f369f667a7eb9fe4`. The final ten workload attempts per arm are retained, including focus failures; long memory stability is unproven. The persistent offline QA tracker is implemented and has focused automated/GUI checks; final delivery qualification remains incomplete. See [QA progress instructions](QA_PROGRESS.md). No stable release or HDR readiness is claimed.

Development continues verified PR #5 / `6a5532e6efa091d31e1baf633af03864316e63d3` on `codex/studio-3.4.9-reliability`. PRs #1–#5 stay unmerged. Original media, the approved artwork, project format, FFmpeg renderer and 3.4.8 scheduling/cache/encoder policies are preserved. This milestone adds no HDR or AI features.

**Current acceptance is incomplete.** The earlier ten-pair cohort passed its FPS/audio gates, but subsequent guarded controls and frozen-baseline endurance failed. Those results remain separate and included. Both completed 30-minute editing attempts also fail strict focus qualification and retain positive late WebView memory slopes. Investigation continues; neither a complete milestone nor readiness for HDR development is claimed.

## Historical incidents and classification

The earlier 5.57-second baseline and 95.4-second endurance target losses remain unexplained. Their surviving evidence cannot establish a renderer crash, browser crash, controller disposal, navigation, resource exhaustion or an observation-connection loss. No matching WER event or ProcessFailed record established a cause. Later successful tests do not retroactively explain them.

Local lifecycle JSONL now correlates UTC and monotonic timestamps for process failures, exit reason/code, browser exit, control attachment/disposal, authorized/blocked navigation, recovery stages and window closure. It records event categories and numeric data, not source/project identifiers or URLs. The automation observer separately records disconnect/crash/page events, host exit state and visible owned-window presence. Private raw logs remain ignored; public records are selected aliases and measurements.

## Recovery implementation and safety boundary

Genuine renderer exits reload the existing view. Browser exits dispose and recreate only the WebView control, retaining the host, backend and project lock. Main native video/PCM and program-preview workers are stopped first. Project data is validated through the existing atomic store. The editor restores acknowledged draft changes, undo/redo and view choices, then resumes **paused**. It does not silently restart the application or resume playback.

User edits enqueue a local recovery checkpoint through the existing pywebview bridge. One coalescing writer atomically publishes the latest state and view/history; the bridge acknowledges only after publication. It captures no media or API credentials. There is one outstanding frontend submission and one latest pending snapshot. No periodic recovery polling or forced garbage collection runs in the product.

Each replacement view has a new epoch. Save requests from obsolete views are rejected under the project lock, preventing a late failed-view request from overwriting recovered changes. A newer completed save takes priority over an older draft. Startup drafts are bound to the published project's digest; external revisions are not overwritten. Invalid/unreadable checkpoint bytes are retained separately while the published project remains intact.

Automatic attempts are limited to three in a minute; a timed-out/budget-exhausted recovery shows a native Retry button. Explicit retry initiates one attempt. Normal close drains checkpoint writes and existing owned workers. Acknowledged checkpoints are recoverable in the tested faults; a change not yet delivered to the host cannot be promised durable, and power loss/storage failure is not a zero-loss guarantee.

The implementation follows the documented distinction between [renderer reload and browser-control recreation](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/process-related-events). Runtime-specific device/GPU recovery and broad Windows deployment remain separate qualification.

## New reproducible startup-close race

A final qualification attempt attached CDP after the HTTP target appeared but before Playwright had enumerated its page. The old fixture raised `StopIteration`, then requested close while pywebview was initializing. Cleanup exited with .NET/pythonnet `InvalidAsynchronousStateException`/type-allocation failure (0xe0434352), correlated with a normal close request and controller attachment. An independent close-as-soon-as-visible fixture reproduced this on source. This is a newly explained **startup/cleanup** failure; it does not explain the old playback incidents.

The observer now waits for target enumeration and retains original exceptions and failure artifacts before cleanup. Product close waits on an event for initial bridge readiness on its close worker (no blocked Windows message thread); timeout presents the existing native recovery path. Late UI dispatch/attach/ready callbacks are fenced after closing starts. Diagnostic writes and failed checkpoint drains cannot abort worker cleanup. Frozen 3.4.8 also reproduced the identical early-close exit code. Three source and three final-installed early-close cycles then passed with no owned children left running. Installed checks and the failed attempts are retained separately.

A separate active-export test initially used an async `wait_for_function` predicate. The driver treated its Promise as truthy rather than repolling the resolved condition, so the assertion ran before export finished. The resulting close-confirmation timeout obscured diagnostics. The test now explicitly polls the job result and preserves logs/cancels only its own test jobs on failure. The rerun recovered the renderer, preserved its acknowledged draft and fully decoded a completed 720-frame 3840×2160 60/1 export. No export failure was established by that original harness error.

## Confirmed unnecessary retention

Twenty repeated native seeks in the unchanged 3.4.8 package created 21 AudioWorklet nodes and destroyed none. Heap object queries found 21 wrappers after diagnostic collection and after Stop. The candidate created and destroyed all 21, retained one while active, and retained zero after Stop. Both CDP WebAudio lifecycle events and object queries agree on this fixture.

Replacement/disposal now explicitly stops the processor, releases its PCM ring, clears the message callback, closes its port and disconnects the node. Pause keeps the current node/queue for correct resume. This addresses the confirmed repeated-seek ownership leak without shrinking queues or caches. The [Web Audio lifetime rules](https://www.w3.org/TR/webaudio/) explain why an always-active processor and open message channel must be explicitly released.

The stopped native backend also releases its project snapshot and joins the status reader before closing its pipe. Active decoders, cached original frames, texture pools and GPU completion slots keep their existing budgets. The working frame cache was not reduced to obtain a lower memory number.

## Redundant allocation and ownership accounting

The unchanged 600-second memory diagnostic transferred approximately 163.2 MB of clock responses. A compact unchanged-status experiment reduced duplicate serialization, but its later 600-second / 7,200-clip diagnostic recorded 11,194 underruns and failed. In equivalent 90-second observations the frozen3.4.8 package recorded 544 and the compact candidate 1167; neither control is presented as a pass. WebView's busiest observed thread approached 93% of one logical core versus about 49% in the earlier successful baseline diagnostic. A local 20-second resource probe measured approximately 1-second audio first-byte waits, slow clock outliers and a 179 ms long task. These locate load/timing problems, not a proven TCP, driver or original-incident cause.

A candidate full-status diagnostic arm completed 90 seconds with zero underruns, including 15 seconds of CPU profiling. The profiler mostly attributed time to native `(program)` activity rather than one JavaScript function; profiling is not a performance-acceptance observer. Compact responses were conservatively **reverted**, preserving full baseline replies, command/error semantics and buffers. A fresh unprofiled source control and final packaged requalification are required below. No transport-byte reduction is claimed as a shipping gain.

Working set and private commit are reported separately. Summed RSS may double-count shared UMA mappings and is not physical RAM consumption. GPU-pool estimates are not added again to process totals. Live JS heap/DOM/worklet counts, native queues/pools, backend snapshots, bounded undo/checkpoint data and browser allocation pools have different ownership and lifetimes. Diagnostic GC occurs only after stopping, never as a shipping memory-management policy.

## Verification completed so far

- Portable recovery tests passed atomic-ack ordering, failed-write preservation, coalescing, stale-epoch rejection, late-save priority, draft/undo/position restoration, restart binding and unreadable/invalid checkpoint retention.
- All 75 offline Python tests and 15 JavaScript tests passed before packaging. Focused native transport and worklet tests passed after their changes.
- Source and installed Windows tests passed two renderer terminations, browser-process termination, unpublished acknowledged draft preservation, undo/redo, seek-position restoration, paused recovery, observer detach without recovery, unexpected-navigation blocking, stale-save rejection, automatic-attempt budget and the real manual Retry button.
- The first source fault test reached successful automatic recovery but failed locating Retry on the Python launcher rather than the actual owned window process. The selector was corrected to the owned process family; the failed attempt is retained and the complete fixture passed afterward. No application change was made to hide that harness error.
- The initial 3.4.9 MSI upgrade/uninstall/reinstall and installed 24-module/desktop/web/native/icon consistency checks passed. No public binary release is created.

## Initial compact-response playback comparison (retained, superseded for final qualification)

All ten initial candidate trials completed; their compact-response variant was subsequently rejected by long stress. These rows are retained rather than silently replaced. A new final ten-run qualification is required after rollback. The comparison uses the same generated independent original H.264 sources, 125 seconds, 1,500 clips, three video/three audio tracks, 960×540 composition and 356×200 surface, no proxies or encoded preview, AC/Balanced and the same driver. It is reduced-resolution composition from 4K60 originals, not native-resolution UHD60 qualification. The archived 3.4.8 record did not capture its WebView runtime; current matched controls use runtime 157.0.4341.57 in both arms.

| Run | 3.4.8 FPS | Skips | 3.4.9 FPS | Skips | 3.4.9 peak summed RSS MiB | p95 / p99 upper ms |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 59.800 | 14 | 59.818 | 7 | 3249.6 | 18.0 / 33.7 |
| 2 | 59.750 | 10 | 59.796 | 9 | 3474.8 | 17.8 / 25.1 |
| 3 | 59.872 | 2 | 59.897 | 3 | 3366.7 | 17.8 / 23.7 |
| 4 | 59.821 | 2 | 59.653 | 7 | 3354.9 | 18.0 / 37.6 |
| 5 | 59.637 | 16 | 59.819 | 6 | 3427.3 | 18.0 / 41.1 |
| 6 | 59.857 | 3 | 59.814 | 5 | 3461.5 | 18.0 / 38.3 |
| 7 | 59.777 | 2 | 59.695 | 3 | 3278.2 | 18.0 / 38.6 |
| 8 | 59.858 | 5 | 59.851 | 4 | 3473.5 | 17.9 / 33.6 |
| 9 | 59.670 | 4 | 59.816 | 4 | 3457.5 | 17.9 / 33.6 |
| 10 | 59.848 | 3 | 59.723 | 25 | 3493.8 | 17.9 / 33.7 |

3.4.8 → 3.4.9: median FPS 59.810 → 59.815; worst 59.637 → 59.653; best 59.872 → 59.897; across-trial FPS population SD 0.07742 → 0.07088. Both achieved 10/10 ≥59.5 FPS and zero underruns, with exactly 6,000,000 audio samples per run. Median skips increased 3.5 → 5.5 and maximum 16 → 25. Median peak summed RSS increased 3,360.7 → 3,442.4 MiB; median machine CPU 6.185% → 6.35%. Thus the FPS/audio gate passes; exact preservation of the skip baseline does **not** pass unconditionally.

Run 10 remains included. Nineteen of its 25 skipped frames occurred before sequence frame 37; 16 were source-wait classified, with no GPU-slot starvation. Prior source-wait Present calls included 42.0/44.0/72.0 ms; its longest active Present interval was 153.601 ms (archived ten-run maximum 60.221 ms). AC remained connected and peak sampled system CPU was 41.7%. This associates the outlier with startup/source/Present timing, without establishing an OS/driver root cause. Histogram p95/p99 values are bucket upper bounds, not exact quantiles or physical scanout timing. Candidate median p95/p99 upper bounds are 17.95/33.7 ms versus archived 17.8/25.1 ms. Current-runtime controls also show variable p99 (baseline34.8/26.5/25.3 versus candidate35.9/23.3/41.1 ms); a broader tail-equivalence claim is not established. Exact per-frame variance was not retained; across-run FPS SD and interval summaries must not be relabelled as it.

Three additional matched alternating pairs on the current runtime produced baseline FPS/skips 59.845/4, 59.834/4, 59.910/2 versus candidate 59.837/6, 59.898/3, 59.819/8. All had zero underruns. The 25-skip event did not reproduce; overlapping ranges and +2 median skips do not prove equivalence or explain the outlier. No failed or poor trial was silently replaced.

The initial ten used the first 3.4.9 package. Subsequent fixes are download-anchor routing, recovery inspector restoration and storage-failure handling on close/diagnostics and startup-close callback fencing. Native C++ and worklet ownership code are unchanged; the clock response path was subsequently restored to full baseline replies. Matched controls used the download/UI-corrected package; affected recovery/native/Windows checks and long tests use the final package. Retained ten-run evidence is scoped to those unchanged performance paths, not represented as ten runs of the final EXE bytes.

## Superseded full-response package qualification

This superseded package restored full clock responses; no compact marker path remained in the frontend, server or controller. MSI SHA-256: `19f33f295597fe8268402f678268c684675aebb9449c75ee7e0f64fdbbe95de3`. Its installed/source/bundle checks passed, including 24 Python modules, native dependencies and approved branding. The native runtime remains `ac206038cea559f87d784e0ec4fc8485bdebd1421b7c4a78853e7ea037e3f72a`. The following ten are **runs of that full-response, uncompressed-history package**, not the final compressed-history MSI or a relabelling of the rejected compact variant.

| Run | 3.4.8 FPS | Skips | Corrected 3.4.9 FPS | Skips | Peak summed RSS MiB | p95 / p99 upper ms |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 59.800 | 14 | 59.818 | 3 | 3449.4 | 18.1 / 36.0 |
| 2 | 59.750 | 10 | 59.779 | 5 | 3231.7 | 18.1 / 37.9 |
| 3 | 59.872 | 2 | 59.826 | 10 | 3422.4 | 18.3 / 39.5 |
| 4 | 59.821 | 2 | 59.870 | 5 | 3402.2 | 18.1 / 36.9 |
| 5 | 59.637 | 16 | 59.804 | 5 | 3405.7 | 18.1 / 41.4 |
| 6 | 59.857 | 3 | 59.796 | 9 | 3359.6 | 18.2 / 40.6 |
| 7 | 59.777 | 2 | 59.896 | 5 | 3399.3 | 18.2 / 39.0 |
| 8 | 59.858 | 5 | 59.715 | 2 | 3352.7 | 18.1 / 39.7 |
| 9 | 59.670 | 4 | 59.704 | 8 | 3474.2 | 18.2 / 36.9 |
| 10 | 59.848 | 3 | 59.825 | 14 | 3493.4 | 18.1 / 37.9 |

All 10/10 reached ≥59.5 FPS, exactly 6,000,000 audio samples and zero underruns, with no failed trial. Best/median/worst: 59.896277/59.811261/59.704324; across-trial population SD 0.056994; across-trial p05 59.709288. Skips min/median/max2/5/14 versus archived 2/3.5/16. Median peak summed RSS 3403.95 MiB versus 3360.65 MiB; median CPU 6.685% versus 6.185%. Current frozen3.4.8 controls were 6.50%/6.82%, so the historical CPU difference alone does not establish new-code overhead.

Corrected active Present p95/p99 medians 18.1/38.45 ms, longest 62.7992 ms. The archived values were 17.8/25.1 ms, longest 60.221 ms. This historical p99 increase remains explicit. Current-runtime frozen3.4.8 controls had p99 values 39.7/38.3 ms, so a candidate-specific cause is not established. The controls measured 59.762560 FPS / 0 skips before and 59.538417 FPS / 49 skips after. Both had zero underruns. The after-control's 177.406 ms active interval and 49 skips are retained as an outlier: 22 source-wait-associated, 27 without a queue wait, 0 GPU-slot starvation; peak sampled system CPU 52.3%, AC throughout. Its missed-event trace has a largest 57.13 ms loop gap, so the histogram maximum must not be described as a proven 177 ms GPU/Present-call stall. No OS/driver/root-cause explanation is invented.

The FPS/audio gate and archived maximum-skip bound pass; the median has 1.5 more skips and exact historical p99 preservation is unproven. Current control variability, physical scanout/acoustic sync and broader tail behaviour remain qualification limits.

## Recovery history allocation and responsiveness

The first full-response package serialized all 80 large undo snapshots into every edit checkpoint. At 1,500 clips this produced a 40.47 MiB checkpoint and a confirmed save responsiveness regression: matched edit/save medians were 0.964 seconds in unchanged 3.4.8 and 9.727 seconds in that candidate. Three candidate batches finished and acknowledged their drafts, but the old host subsequently required forced close after 20 seconds. The available log identifies host-close entry, not the blocked cleanup owner. This failed attempt is retained.

The final candidate losslessly compresses only the recovery history with the browser's native gzip stream, with a JSON fallback for older runtimes. Immutable document/history snapshots are captured before compression; one submission runs at a time, and a UI-only update cannot discard a pending draft. The backend stores the encoded history without expanding or repeatedly copying all 80 states. Decompression and validation occur at restoration. Existing raw-history checkpoints remain readable. Corrupt history is retained separately and reported, while the project draft remains recoverable. Failed publication retains the latest pending work and retries on the next editing checkpoint, without a permanent retry loop.

The packaged final matched test completed normally: edit/save medians 1.202 seconds in 3.4.8 and 1.321 seconds in 3.4.9; full pause/seek/edit/save/resume batch medians 2.074 and 2.303 seconds. All 80 undo entries and durable acknowledgements were verified. The encoded checkpoint is approximately 4.3 MiB for this fixture. This does not reduce undo depth, effective frame-cache capacity or preview quality. Renderer and browser termination tests separately restored an unpublished draft, all 80 undo states, paused position and exact canonical timeline values; physical preview placement errors were zero pixels.

## Off-center preview investigation

The automation harness had forced a 1.0 browser device-pixel ratio while Windows used 175% scaling. The existing native bounds calculation correctly multiplied browser geometry by its reported ratio; the emulated ratio therefore placed the physical child surface too small and toward the upper left. This is a reproduced test-harness geometry defect, not evidence of changed source framing or camera orientation.

The default session now clears device-metric emulation. An independent Win32 check compares the actual child HWND rectangle with DOM geometry converted using the real window DPI. Installed native playback, modal/resize and fault recovery checks pass with zero-pixel placement error at 168 DPI / browser DPR 1.75. A declared legacy flag remains solely for reproducing historical timing. Protected benchmarks keep a 356 × 200 **physical** surface using DPI-aware CSS sizing; the composition remains 960 × 540. The final ten-run cohort and fresh 3.4.8 controls use this corrected placement. Earlier cohorts retain their measurements and are not visual-placement qualification.

## Retained uncontrolled-window ten-run failure

All ten trials of the compressed-history package completed during the interruption. The process exit/audio checks passed, but the **playback consistency acceptance failed**: only 4/10 reached 59.5 FPS. Best/median/worst FPS were 59.801100/59.482012/58.989933, population SD 0.253051. Skips were 41, 115, 13, 17, 16, 11, 13, 38, 97 and 47 (median 27.5, maximum 115). All ten retained exact 6,000,000-sample budgets and zero underruns. No trial is excluded or relabelled as a successful consistency result.

| Run | FPS | Skips | Audio underruns |
|---:|---:|---:|---:|
| 1 | 59.452160 | 41 | 0 |
| 2 | 58.989933 | 115 | 0 |
| 3 | 59.801100 | 13 | 0 |
| 4 | 59.483018 | 17 | 0 |
| 5 | 59.626638 | 16 | 0 |
| 6 | 59.762530 | 11 | 0 |
| 7 | 59.732314 | 13 | 0 |
| 8 | 59.481006 | 38 | 0 |
| 9 | 59.123200 | 97 | 0 |
| 10 | 59.413471 | 47 | 0 |

Run 2's longest active presentation interval was 1,300.36 ms; 87 of its 115 skips were associated with one source-wait-classified event near sequence frame 2355. That association does not establish decoder, driver or Windows root cause. A later independent spot check found the test window visible/not minimized but neither foreground nor hit-test-visible at the preview center: another window covered it. There was no continuous visibility trace for this cohort, so it would be incorrect to claim all ten were identically occluded or to explain every outlier from that spot check.

Controlled follow-up tests keep only the owned QA window above other windows, or create a local opaque test cover over the preview/whole editor. Win32 hit tests, foreground state, native DPI and browser visibility are recorded throughout. The controlled experiments use the same package, native binary, sources, tracks, duration, composition, physical surface and quality. Covered results remain separate and public; visible measurements cannot erase the failure above. The test-only topmost/cover state is removed on cleanup and no global Windows settings are changed. Qualification is still in progress.

## Natural Windows ten-pair comparison

The earlier compressed-history MSI was `3d13547f0e9d4fee453f84b7bed176fdf3c891146a6469500a6ac288d2978d30`. No application or native C++ change was made during that measurement-isolation cohort. The frozen 3.4.8 host and installed 3.4.9 host ran ten alternating pairs with identical generated originals, three video/three audio tracks, 1,500 clips, 125 seconds, 960 × 540 composition and a 356 × 200 physical monitor. No proxies, encoded program intermediate, generated frames or quality reductions were used. Every decoder retained its six-frame prefix budget/37-frame pool and every renderer retained six GPU slots.

Playwright 1.65.1's default CDP attachment enables artificial page focus. The final protocol uses `no_defaults=True` and real Windows DPI, with Windows foreground, browser focus and physical coverage observed separately. A denied Windows foreground request was reproduced even when the QA window had a topmost style; a scoped input-queue handoff focused only the owned test window and was detached immediately. Terminal-minimization experiments did not establish valid visibility and were restored. No global Windows settings were changed. The corrected visible and actual browser-unfocused smoke tests both passed with exact audio budgets and zero underruns. The earlier emulated-focus controls and failed fixtures remain separate evidence.

| Pair | Frozen 3.4.8 FPS | Skips | Current 3.4.9 FPS | Skips |
|---:|---:|---:|---:|---:|
| 1 | 59.912493 | 2 | 59.796408 | 3 |
| 2 | 59.694310 | 7 | 59.830767 | 11 |
| 3 | 59.798559 | 7 | 59.695804 | 12 |
| 4 | 59.712792 | 6 | 59.731309 | 6 |
| 5 | 59.537387 | 8 | 59.668892 | 3 |
| 6 | 58.974128 | 107 | 59.733701 | 3 |
| 7 | 59.697238 | 2 | 59.667220 | 5 |
| 8 | 59.771076 | 4 | 59.929974 | 2 |
| 9 | 59.649665 | 6 | 59.744329 | 5 |
| 10 | 59.892296 | 3 | 59.736042 | 5 |

All twenty maintained their requested physical visibility/focus condition, reached the exact 6,000,000-sample budget and reported zero underruns. 3.4.8 → 3.4.9 best/median/worst FPS: 59.912493/59.705015/58.974128 → 59.929974/59.734871/59.667220. Runs ≥59.5 FPS: 9/10 → 10/10. Across-run population FPS SD: 0.252983 → 0.076262. Skips min/median/max: 2/6/107 → 2/5/12. Median peak summed RSS: 3,403.15 → 3,477.15 MiB; median machine CPU: 6.400% → 6.365%. RSS sums can duplicate shared UMA pages.

Active interval p50/p95/p99 medians: 16.7/18.1/38.6 ms → 16.7/18.0/38.95 ms; longest active interval: 775.66 → 65.4884 ms. Histogram quantiles are upper bounds. Exact per-frame variance was not retained; across-run FPS SD must not be presented as that variance or as physical scanout timing.

Pair 6's frozen-baseline failure remains included. Eighty-three of its 107 skips were source-wait-associated, none GPU-queue-associated; the largest missed event lost 47 frames near frame 2700. The full caches/pools were retained, minimum sampled available RAM was 5,045 MiB and peak sampled system CPU was 46.9%. This demonstrates a substantial tail in unchanged 3.4.8 under valid controls. It rejects an explanation confined to 3.4.9 or occlusion alone, without identifying a decoder, driver, scheduler or memory-pressure root cause. The candidate's earlier 1,300.36 ms gap is still not explained.

The longest **individual** Present calls were 130.603 ms in the uncontrolled candidate outlier, 77.1311 ms in the controlled baseline outlier, and 93.7485 ms in final candidate endurance. Their longest **active intervals between presentations** were 1,300.36, 775.66 and 322.13 ms respectively. GPU composition maxima were 3.830, 4.634 and 4.660 ms. These distinguish a scheduling/source/completion gap from a measured single-call D3D11 stall; they do not isolate the ultimate cause. GPU completion-observation maxima (248.735/193.839/130.159 ms) are observations, not calibrated GPU execution durations. Native C++ is byte-identical in both arms. Covered-window counters cannot qualify visible physical scanout.

The unchanged protected wall-time FPS includes endpoint observation latency. One earlier visible 3.4.8 control scored 59.4207 FPS with eight skips while its active mean Present interval was 16.6846 ms; its observed wall duration was 126.0672 seconds. Active cadence/window summaries are reported alongside original scores rather than replacing them. The archived 3.4.8 ten-run median 59.810478 and skip median 3.5 remain historical targets with different viewport/focus conditions. The final candidate's wall median is 0.126% below that archive and 0.050% above the current matched control; its skip median 5 still misses the strict archived 3.5 target. The historical p99 increase also appears in current frozen 3.4.8. No unconditional equivalence or zero-stutter claim follows.

The final candidate's 600-second playback run completed at 59.876059 FPS with 66 skips, exact 28,800,000 samples and zero underruns. Active p50/p95/p99 were 16.7/18.2/38.1 ms, maximum 322.13 ms with two intervals above 100 ms. This is a retained long-tail limitation. A matched natural-focus frozen-baseline endurance control is scheduled; the old uncompressed package's shorter tail is not substituted for the current build.

## Matched memory diagnostics

Both current natural-focus 600-second memory diagnostics completed with zero observed underruns. Full clock replies remained enabled: 39,034 requests in frozen 3.4.8 and 38,869 in 3.4.9. Post-stop diagnostic collection returned live JS heap to 10.11 and 9.80 MiB respectively. Neither a small live heap nor a one-time memory reduction proves a stable total-memory plateau.

| Private commit owner | 3.4.8 first/last 30 s median MiB | 3.4.8 warmed slope MiB/min | 3.4.9 first/last 30 s median MiB | 3.4.9 warmed slope MiB/min |
|---|---:|---:|---:|---:|
| Host | 873.73 / 877.45 | 0.567 | 889.77 / 891.61 | 0.236 |
| WebView | 1,003.01 / 1,896.51 | 81.044 | 997.03 / 1,880.46 | 80.956 |
| Native | 2,284.16 / 2,288.17 | 0.555 | 2,281.98 / 2,283.25 | 0.056 |
| Total | 4,207.85 / 5,060.72 | 82.201 | 4,206.75 / 5,055.25 | 81.053 |

WebView warmed-slope approximate 95% intervals overlap: 68.56–93.53 versus 69.02–92.89 MiB/min. These use actual timestamps, 30-second medians, a 60-second warmup and two-lag Newey–West covariance in one session per arm. The common ten-minute growth remains real; its allocation/observer attribution and longer plateau are still being investigated. Host/native growth is much smaller. The completed attached and detached 30-minute results follow below; both retain strict-focus failures and positive late WebView slopes.

## Retained attached 30-minute editing failure

The final compressed-history candidate completed 180 editing batches across approximately 1,806 seconds: playback/pause, seeks, selection, inspector updates, timeline scrolling, opacity edits, saving and alternating preview resolutions. It retained the capped 80 undo states and reported zero accumulated audio underruns, no browser errors, no lost target and a normal host exit (0) without forced cleanup. Batch min/median/p95/max was 2.282/3.452/4.897/5.716 seconds. These include seek, save, resolution changes when applicable and playback prebuffering, rather than isolated input latency.

The attempt **failed qualification** because two samples at approximately 347–349 seconds found the editor unfocused and seven samples failed while surfaces were being replaced. All 1,099 condition samples and the failing exit remain retained. The observer now records a child-destruction transition and checks the still-owned editor if its enumerated native child disappears before rectangle lookup; other API failures retain their error category. This correction does not retroactively pass the original attempt or suppress a genuine visibility change.

Private-commit first/last 30-second medians were host 854.44/873.09 MiB, native 2,383.75/2,421.22 MiB, WebView 921.83/2,130.11 MiB, and total 4,177.98/5,426.99 MiB. In the final 15 minutes, slopes and approximate 95% intervals were host −0.395 [−0.623, −0.167], native −0.037 [−1.375, 1.301], and WebView **12.905 [12.504, 13.305] MiB/min**. The browser therefore did not demonstrate a plateau in this observed workload. Post-stop diagnostic collection reduced live JS heap to 47.85 MiB while all 80 undo entries remained; this is compatible with intentional history plus reclaimable allocations, not proof that all browser growth is explained or fixed. Clock observation transferred approximately 419 MB over 104,240 requests.

A separate bounded 30-minute editing fixture now runs the same categories of commands in the view, with DevTools fully detached during active measurement. It uses the same original generated sources, tracks, timeline, undo cap, quality and cache policies. The change in automation delivery/observer is explicit; it is an attribution control, not a replacement passing score for the failed attempt. No active-session forced collection was added.

That detached attempt completed all 180 batches and 80 undo entries with zero accumulated underruns, no browser error and no recovery-epoch change. Its strict window gate **also failed**: 21 samples across approximately 996–1,030 seconds found the editor unfocused, while the preview remained unobscured. There were no surface-observer failures. Both long attempts remain failed qualifications; neither is silently excluded. The detached batch min/median/p95/max was 1.120/1.587/1.971/2.486 seconds.

Detached private-commit first/last 30-second medians were host 856.11/877.51 MiB, native 2,400.36/2,402.46 MiB, WebView 869.26/1,626.37 MiB and total 4,134.39/4,900.23 MiB. Late host/native slopes were 0.194 [−0.041, 0.429] and −0.309 [−1.827, 1.209] MiB/min; WebView remained **10.937 [10.409, 11.465] MiB/min**. Observers influence the measured level, but their removal does not eliminate active growth. There is no demonstrated active-session plateau and no proven attribution of all remaining growth to a specific leak.

The last editing batch finished at 1,801.831 seconds; the parent's original count-of-sleeps loop reconnected at 1,899.713 seconds. This unintended approximately 98-second gap is retained and explicitly limits post-stop timing comparisons. Before any explicit collection, the later observation showed WebView commit 1,265.76 MiB and live heap 48.98 MiB with 80 undo entries retained; after another 30 seconds idle, commit was 1,266.73 MiB; after diagnostic GC, 1,262.84 MiB/live heap 47.87 MiB. Idle/reconnection effects are not separately isolated. Native Stop released its worker and normal closure left zero job members. The parent now uses a monotonic deadline, and the corrected short fixture passed; the completed long result was not rerun or overwritten.

## QA process and terminal ownership

The repository contains no explicit Windows Terminal invocation in the inspected QA launch paths. Numerous console subprocess launches lacked a no-console policy, and failed/timeout paths did not uniformly supervise a whole descendant tree. The historical dozens of windows were not preserved with sufficient ownership records to identify each one's creator. At the resumed inventory there were no Windows Terminal instances or active VlogCraft/native/FFmpeg benchmark processes; headless console hosts with no main window are distinguished from visible terminals and are not terminated by name.

The QA-only supervisor now creates hidden console children, assigns each new suspended process to a Windows Job Object before its first instruction, then resumes its primary thread. Kill-on-job-close contains descendants even if their immediate parent exits. The job handle belongs to the executing test supervisor, not its DevTools/Codex observation connection. Exceptions, explicit cancellation, timeout or supervisor death release only job members. Logs and test artifacts remain available. Existing application close is attempted first; a host or descendant requiring forced cleanup remains a failed release check. No editor playback code or global Windows settings changed.

Six focused Windows tests pass: no-console launch and retained output; inherited hidden-child policy composed with the offline guard; exception cleanup preserving an unrelated sentinel; timeout cleanup preserving its log; abrupt-supervisor job cleanup; and continued work after an observation pipe closes. A guarded installed native test and short detached-editing fixture also pass with zero owned survivors. Before/after visible-console snapshots record counts without titles or command lines. They do not exclude every brief intermediate flash or authorize closing unrelated terminals. Final integration and terminal inventories remain pending.

The focused suite now has eight ownership tests, including diagnostic-failure cleanup and restoration of absent standard Windows profile folders. Three production launch tests independently exercise GUI FFprobe/thumbnail/render subprocess visibility without the QA hiding shim. A controlled frozen-GUI reproduction left three, then six console hosts after normal close; forced job cleanup left empty Windows Terminal windows. The production subprocesses now use `CREATE_NO_WINDOW`. Arguments, encoders, buffers and playback logic are unchanged. With owner confirmation, three initial empty test windows and six controlled-reproduction windows received graceful close requests: nine windows, zero process terminations, zero unrelated windows targeted. The following inventory found zero visible terminals and zero live console clients.

The first console-corrected package accidentally collected the QA `sitecustomize` module from the build environment; the bundle audit caught it before publication. Packaging now explicitly excludes `sitecustomize` and `benchmarks`, and bundle verification checks that exclusion. A separate QA launch environment lacked `APPDATA`; known-folder restoration now fills only absent standard values and reports key names, never paths. These are retained packaging/fixture failures, not hidden successful tests.

The corrected final MSI is `05bcdbd1abaa0e68f1ac2ad6df73511f5acdfcf60b8dfc07f369f667a7eb9fe4`. Its baseline-install/upgrade/uninstall/reinstall checks return zero and preserve protected project/settings bytes and shortcuts. Source, bundled and installed Python/web/native/approved-icon checks pass, including exclusion of QA modules. Installed renderer/browser recovery, exact canonical restoration of all 80 undo entries and the unsaved draft, zero-pixel preview alignment and three early-close cycles pass without owned survivors or new terminals. These correctness results do not establish final playback or memory acceptance.

## Resource ownership boundaries

| Owner | Required/bounded resources | Evidence and release boundary |
|---|---|---|
| Native decode/GPU | Three decoder pools, four-frame source queues, six completion slots, six cached original-PTS prefix frames/source | Protected run10 retained48 surface views/three texture pools, estimated1317MiB; decoder hardware allowance37 frames/source, effective prefix-cache hits83 in the first source. These are deliberate high-throughput allocations, not summed again into UMA process totals. Driver-resident byte attribution is unqualified. |
| Native audio | Current two-channel 96,000-frame Float32 ring (~0.73MiB), bounded sample/context segments | Pause retains it; seek/replacement/Stop explicitly dispose it. Twenty historical retained rings explain a real ownership defect, not all previous517MiB browser growth. |
| Backend | Validated state/snapshot, source indexes, subprocesses and caches | Native Stop drops its snapshot/joins reader; existing cache budgets preserved. Five generated project reopen/close sessions release every observed owned child process. |
| View | DOM, JS DTOs, timeline, capped80-entry undo/redo, one coalesced checkpoint in flight plus latest pending | Live heap/DOM/listeners and browser/renderer/GPU/utility process roles sampled separately; checkpoint/history data are intentional editing retention. Full allocation-stack attribution and every detached-DOM path remain unqualified. |
| Browser allocator | V8/DOM/media/GPU and process pools; DevTools overhead | Post-stop diagnostic GC/release comparisons and attached/detached controls distinguish some reclaimable objects from process commit. A lower live heap alone does not prove a stable total-memory plateau. |

## Qualification still running

The protected ten-run packaged comparison, matched memory measurements, extended editing, repeated project lifecycle, bounded pressure/cancellation, export preservation, private originals and final Windows/CI checks will be recorded here before publication. No pending check is represented as passed.
