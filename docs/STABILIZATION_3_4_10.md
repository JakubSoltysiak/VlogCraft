# 3.4.10 targeted stabilization

Continues exact 3.4.9 checkpoint b2df1cf on codex/studio-3.4.10-stabilization, stacked on PR #6. Production playback/audio/resource code and the installed 05bcdbd 3.4.9 MSI remain unchanged. No root cause is assigned to the old 4.629-second gap,657 underruns or positive late WebView growth without reproducible evidence.

Confirmed diagnostic correction: observer_memory used one full sleep per loop iteration, adding sampling cost to nominal duration. It now uses a monotonic wall deadline, records actual observation and reconnection/query-tail times separately, and samples natural post-stop idle before diagnostic garbage collection. Slow callbacks can still overrun the deadline; actual elapsed time is retained. Four focused scheduling tests pass. Earlier measurements are not rewritten or reclassified as passing.

Targeted attached/detached observations will use the unchanged installed host, generated original-media workload,45 seconds active plus30 seconds natural idle. These are attribution diagnostics, not new ten-run/endurance/4K60 qualification. All new tests report through build/qa/status.json. No private footage is needed. Shipping cache/undo capacities and full clock replies remain preserved. No periodic GC is introduced into the editor.

Qualification remains incomplete. The existing 3.4.9 report and historical failures remain authoritative until additional evidence supports a narrower conclusion. No new installer is warranted for diagnostic-only changes.
