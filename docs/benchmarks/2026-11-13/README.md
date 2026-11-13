# Curated numeric evidence

These JSON snapshots come exclusively from locally generated media. Personal paths, process IDs, projects, frame pixels and dependency binaries are excluded. The full local logs, graphs, captures and media remain under ignored build/qa/architecture. Values have not been replaced with target FPS or zeroes for unavailable measurements. Public raw data is a scoped engineering record, not camera qualification.

- comparison-current: 20 matched video-only configurations × 3 runs, compiled current native source/binary SHA-256, actual processed frame counts, startup-inclusive wall time and per-process resource samples. Earlier complete comparison retained separately.
- export-before / export-opaque: three repeated production single-stream original4K60 exports per version, stage timings, input hash/metadata and decoded checks.
- cache: one paired integration trial, unrelated caption edit, identity and output byte equality.
- filters / filters-extra / services: three repetitions except explicitly shorter samples (first index/audio extraction); no controlled cold filesystem cache.
- ui: 30 measurements per operation, 1,500 clips, 32 source assets.
- native-host / raw-* / precision-audio / pictures: actual opt-in engine output and readback/precision/channel checks, with scope limits in the report.
- index-before / index-after: actual native close while original PTS indexing is active; no surviving owned child after the fix.
- cut-smoke / cut-installed-long: program callbacks, browser quality, buffering, resource history and bounded complete cache. These are reduced-resolution generated-source tests, not physical scanout or acoustic drift.
- windows-installed / windows-over5gib / lifecycle / encoding-final: final installed workflow, large native imports, source-offset export, installer retention and decoded encoder results, where present.

The authoritative narrative, uncertainty, failures and unqualified cases are in [ENGINE_BENCHMARKS.md](../../ENGINE_BENCHMARKS.md) and [VERIFICATION.md](../../../VERIFICATION.md). Missing files/results are not inferred as passed. Source/binary hashes establish the experiment implementation; driver/power/file-cache variation still affects throughput.

The optional generator and all measurement programs are under benchmarks and experiments. No camera folder was supplied for this run. Reproduce with generated media on equivalent hardware; do not publish unreviewed private-camera logs.
