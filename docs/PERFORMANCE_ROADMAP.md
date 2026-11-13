# Performance implementation gates

The canonical requirements remain [TODO.md](../TODO.md). These are engineering milestones, not a promise of dates or complete professional readiness.

| Order | Work | Acceptance evidence before switching behavior |
|---|---|---|
| 1 — this draft | Guarded opaque base; range dependency cache; deterministic index shutdown | Decoded output, cache restart/stale/corrupt/budget cases, launch/cancel race, native-close child ownership, full regression and package checks. Measured scope in ENGINE_BENCHMARKS. |
| 2 | Continuous native scheduler behind an experimental switch | Existing project snapshot in; exact frame/PTS out. Bounded ring of GPU surfaces, generation cancellation, audio clock and direct display. First/last frame IDs through B-frame/VFR cuts; no effects silently omitted. |
| 3 | Shared effect evaluator | Source-time animation, rotation/scale/alpha, LUT/curves, masks, chroma, wipes, titles, track ordering and nests. Golden images/alpha at edges, SDR transfer/range tests, reference fallback for unsupported operations. |
| 4 | Clock and decoder reuse | 3 video + 3 audio original4K sources, rapid independent-file cuts, seeks while playing, source steps, mixed rational rates/VFR. Measure cold/warm/cache-miss seek, actual composed/presented frames, gaps, audio sample/clock drift. |
| 5 | Sustained qualification | Owner-approved camera folder read-only; 10/30/60-minute runs, >5 GiB independent imports, long export, SHA-preserved originals, bounded queues/cache/memory trend, cancel/disk-full/corrupt/device-reset recovery. No manual intermediate build tests required. |
| 6 | GPU export | Hardware capability/format probes, high-precision surfaces to supported encoder, CPU fallback. Compare decoded quality/PTS/sample count and repeat the 100-case historical drain fixture. |
| 7 | Managed high precision | Explicit working primaries/transfer, float linear composition, 10-bit originals/proxies/reference parity, Windows SDR/HDR display transforms. Ramp charts plus calibrated monitor and metadata validation. |
| 8 | HDR/Log and multichannel | Actual device/mode evidence, Samsung Log transform sources, HDR10/HLG and frame-mapped HDR10+ mastering policy; channel-layout graph, sample-accurate buses and lawful passthrough. No fake Atmos or copied invalid HDR payloads. |
| 9 | Release | Real-camera acceptance, multiple Windows/GPU configurations, clean install/runtime provisioning, DPI/accessibility, code signing, provenance/license choice and corresponding-source compliance. Owner approves release/merge. |

Full ten-minute generated playback/export and two independent >5 GiB native checks now have scoped passing functional results. The playback rate remains below target; they do not close real-camera/hour-long/native4K acceptance.

## Next slice in concrete terms

Keep UI commands and project persistence. Add a versioned local engine interface with create(snapshot), seek(frame), play, pause, cancel(generation), metrics and close. The current prototype owns the decoder/device/surfaces but has no sequence scheduler or audio callback. Build those before a large effect catalogue. A frame queue must retain original PTS/timebase and output sequence frame IDs, release all AVFrame/COM references on generation replacement, and fall back to the existing compiler for a whole unsupported range.

Replace the deliberately blocking per-frame completion query with a bounded asynchronous ring. Measure completed GPU work separately from submissions, and DXGI/physical presentation separately from decode. Test source exhaustion, held VFR frames, late/early frames, audio underrun, seek cancellation and device removal. A successful 120-frame SDR surface demonstration is insufficient for the default transport.

## Additional investigations

- MLT 7.42 placebo module on Windows, matched GPU effect/color path; current 7.41 CPU result is not a benchmark of it.
- D3D12 or Rust only if a concrete ownership/interop/tooling/performance advantage can be demonstrated.
- Adaptive proxies based on measured codec decode cost, bit depth/color description, timeline load, GPU memory and SSD space; never replace final originals.
- Lazy timestamp indexing by verified GOP pages, with correct B-frame reorder and VFR step behavior.
- Unified cache quotas, disk-pressure behavior, restartable analyses and background priority. Current program-cache budget excludes in-flight temporary files and other cache families.
- Large independent asset library and thumbnail/waveform scrolling; current UI profile uses 32 assets and 1,500 clips.
- WPR/ETW or vendor profiler for trustworthy decoder/encoder occupancy and physical disk I/O. PDH near-zero counters are not reliable hardware utilization on this driver.

## Stop conditions

If parity, source PTS, sample counts, approval/undo, recovery, original integrity or cancellation regresses, retain the existing renderer and do not enable the candidate. A measured bottleneck justifies targeted work; it does not justify discarding the rest of the editor.
