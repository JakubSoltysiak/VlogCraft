# 3.4.10 targeted stabilization

## Current continuation result

The root-cause continuation now includes two minimal production changes: PCM graph preparation outside the clock/status guard and indexed meter iteration to reduce measured allocation churn. The local MSI is now version 3.4.10, SHA256 `8d8cd097de5d2dfd67bb14c0c2c6a16f5750a6a9c004da8ee0371acf844821d2`. Installed playback/fallback, recovery, exact 80-state history, export correctness, source/bundle/icon and upgrade/uninstall/reinstall checks pass. Long-session stabilization is still incomplete. The candidate allocation run has higher WebView private commit than its baseline despite fewer attributed meter samples; there is no aggregate RAM reduction claim. See the [current root-cause report](ROOT_CAUSE_3_4_10.md) and [sanitized numeric evidence](benchmarks/native3410/root-cause-results.json).

## Historical diagnostic checkpoint through 1ab1e62

The following sections describe the earlier diagnostic-only checkpoint and its unchanged 3.4.9 installer. They are retained as history; current installer and production status are above.

Continues exact 3.4.9 checkpoint b2df1cf on codex/studio-3.4.10-stabilization, stacked on PR #6. Production playback/audio/resource code and the installed 05bcdbd 3.4.9 MSI remain unchanged. No root cause is assigned to the old 4.629-second gap,657 underruns or positive late WebView growth without reproducible evidence.

Confirmed diagnostic correction: observer_memory used one full sleep per loop iteration, adding sampling cost to nominal duration. It now uses a monotonic wall deadline, records actual observation and reconnection/query-tail times separately, and samples natural post-stop idle before diagnostic garbage collection. Slow callbacks can still overrun the deadline; actual elapsed time is retained. Four focused scheduling tests pass. Earlier measurements are not rewritten or reclassified as passing.

Targeted attached/detached observations will use the unchanged installed host, generated original-media workload,45 seconds active plus30 seconds natural idle. These are attribution diagnostics, not new ten-run/endurance/4K60 qualification. All new tests report through build/qa/status.json. No private footage is needed. Shipping cache/undo capacities and full clock replies remain preserved. No periodic GC is introduced into the editor.

Qualification remains incomplete. The existing 3.4.9 report and historical failures remain authoritative until additional evidence supports a narrower conclusion. No new installer is warranted for diagnostic-only changes.

## Measured findings

The offline extractor reconstructs all1,203 skipped-counter increases from the retained endurance trace. Its five largest increases total1,061 frames around native elapsed364–390s; the first recorded visibility violation is507.642s. Native/window clocks have different origins and are not precisely aligned. These records do not timestamp individual Present calls, but their broad separation rejects attributing the earlier burst solely to the later recorded occlusion. Decoder availability, context contention and presentation/scheduling remain unresolved; no renderer change is justified yet.

In the failed600s memory diagnostic, first/last active renderer private commit is614.28→1406.15MiB, GPU process368.92→450.87MiB, browser43.72→47.63MiB. This locates most observed growth in the renderer process, without identifying a V8/DOM/network/media allocation stack or proving a leak. No native cache reduction follows from this observation.

New45s controls on the unchanged installed349 host both pass sampled visibility, advancing audio and0underruns. Attached observation45.032s, query tail.012s; detached observation45.500s, reconnect/query tail.155s. These partial-playback counters are not exact full-sequence budgets or a125s consistency comparison.

| WebView private commit MiB | Attached | Detached |
|---|---:|---:|
| Immediately after Stop |1125.344|1043.520|
| After30s natural idle, before explicit GC |930.930|894.457|
| After subsequent diagnostic GC |927.266|892.133|

Approximately194.4/149.1MiB reclaims naturally before explicit GC, versus3.7/2.3MiB afterward. This demonstrates reclaimable allocations in these short workloads. It does not explain all late-session growth or establish an active plateau. Historical positive30-minute slopes and failed windows remain unchanged. [Selected numeric evidence](benchmarks/native3410/evidence.json).

Four scheduler tests and three extraction tests pass, including the focused loopback-only run. Process ownership checks leave0owned survivors/new terminal windows in all three new observations. A single150s probe of the original600s/7,200-clip memory workload passes with0observed audio underruns, held sampled visibility and no browser errors, covering the old90–120s interval. [Audio observations](benchmarks/native3410/audio150.json) retain actual sample counters. This is partial playback, not a full-sequence exact-sample/endurance qualification; the historical657-underrun failure remains unexplained. No new ten-minute or30-minute test was needed to validate these diagnostic-only changes.

## Delivery boundary

The implementation fix is diagnostic scheduling and measurement separation. No production root cause for long stalls, occasional underruns or late renderer growth has been established. No speculative renderer/audio optimization is adopted. Published348/349 performance cohorts remain unchanged and are not compared as if these short probes used identical geometry, duration and observers. The active-memory plateau and full stability gates remain open; production HDR adoption remains on hold.

The unchanged installed349 MSI and its approved icon/fallback/recovery/80-state history retain their prior qualification. No3410installer is built or relabelled. Relevant exact-head Windows CI receipts are recorded in draft PR #7. PRs #1–#6 remain unmerged. New QA cases, heartbeats, outcomes and historical results persist in build/qa/status.json.
