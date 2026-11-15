# Root-cause hypotheses — 3.4.10 continuation

Starting checkpoint1ab1e62, same branch and draft PR #7. Historical failures remain open. This matrix was published at206387e before instrumentation changes. At that point no production correction was justified. Subsequent scoped fixes and measurements follow below.

| Hypothesis | Observed evidence | Missing discriminator / next action |
|---|---|---|
| Source availability / demux / I/O starvation |1137 skips were source-wait-associated;1061 skipped-counter increments occur before recorded late occlusion | Sticky source-wait association is not time attribution. Enable existing bounded native missed-event recorder: source-selection duration, loop gap, prior Present, context wait, clock age and GPU-wait flags. It does not itself separate demux from disk/CPU scheduling. |
| Present/context/GPU stall |4.629s interval,1.408s individual Present maximum,0GPU-queue-associated skips | Need event context rather than unrelated lifetime maxima. Correlate native missed-event records with bounded UI/audio acknowledgements; retain independent clock origins and uncertainty. |
| Audio starvation / main-view delivery pause |657 underruns in one600s diagnostic; a150s attempt did not reproduce | Ring history before/after an underrun: queued samples, consumed/sent samples, audio context end, UI/native clock observations. Preserve processor counters and buffers. |
| Observer/CPU contention | PDH calls can be expensive; failures also appear in frozen348 | Use detached observation with native event recording, no PDH sampling; report this changed observer as attribution only, never a replacement protected score. |
| Renderer JS/DOM/media retention | Renderer commit614→1406MiB; short natural idle reclaims149–194MiB | Separate sampled JS allocation stacks and DOM counters from private commit/UMA; profile in a separate short run so profiling does not contaminate stall timing. No active GC. |
| Legitimate undo/cache/allocator high water |80undo states retained; post-stop heap~48MiB; native caches bounded | Active allocation profile cannot establish an unbounded leak or allocator ownership alone. Keep caches/history intact; compare natural idle before any explicit GC. |
| PCM graph-preparation lock convoy | Code holds Controller.guard during snapshot deepcopy, graph compilation and process creation for every8s PCM range; clock/status delivery uses the same guard | Deterministic compiler barrier can prove whether clock/Stop are blocked. If reproduced, shorten the lock around immutable snapshot capture and generation-checked process registration. This would fix a demonstrated concurrency defect without assigning it as the historical stall cause. |

Necessary accumulation experiment: one600-second generated7200-clip program, observed continuously through420seconds to cover historical364–390seconds. Seeking to minute six would not reproduce accumulation. Exact program-end sample count is not asserted for this partial diagnostic. Audio counters, actual elapsed, physical/composition sizes, visibility, code/binary identity and event context will be retained. No new30-minute editing test is planned.

## Candidate checkpoint at 7767d09

The420s detached flight completed with held visibility,0underruns,64skips and140.562ms maximum active interval. It did not reproduce the4.629s historical stall. Its larger missed events include clock corrections254.9–323.8ms near sequence phases6.23–6.32 modulo8seconds, matching the two-second-ahead prefetch boundary of8s PCM ranges. Small previous Present/context times do not explain those particular jumps. This correlation does not establish the cause of every old stall.

Code review found PCM snapshot copying and graph compilation inside the same guard as clock/status delivery. A deterministic compiler barrier reproduced blocked clock delivery; the retained initial fixture also exposed a cleanup assertion issue, corrected before verification. The production candidate captures an immutable snapshot reference under the guard, prepares outside it, then rechecks generation/snapshot/closed state and process budget before launching/registering. Clock and Stop barrier tests now pass, including no encoder launch after a concurrent Stop. PCM byte budgets, commands and two-stream limit remain unchanged. OS process startup still occurs under the registration guard; no blanket zero-latency claim follows.

Separate90s allocation sampling found62,655,300 sampled bytes attributed to `updateMeter`,23,766,784 in `request`,7,471,668 in `rateValue`. This includes collected objects and measures churn, not retained size. Candidate meter iteration uses indexed typed-buffer access with the same peak/absolute-value arithmetic and paint cadence. Meter tests pass; at this checkpoint a matched allocation recheck was still pending. No compact clock response, forced collection, queue/cache/history reduction or precision change is introduced.

Two lock tests, existing PCM/transport tests and full offline regression passed at this checkpoint. Installer qualification was then pending. Subsequent results are below; historical stalls,657underruns and long-session active growth remain open.

## Completed targeted investigation and production correction

PCM graph preparation was a confirmed lock convoy: snapshot deepcopy and graph compilation held the same guard as clock/status delivery every eight-second audio range. The deterministic compiler barrier failed on the old code with blocked clock delivery and passes after the correction. Preparation now runs outside that guard; registration revalidates closed state, generation, snapshot identity and the two-process budget. Four tests cover clock, Stop, seek and concurrent admission. Stale preparations cannot launch after the control operation. Popen still takes the registration guard, so a bound on all clock latency has not been proved. PCM sample budgets, full clock responses, compiler/export logic and buffers are unchanged.

The flight recorder is opt-in QA, not a shipping component. Its preallocated256×9 numeric ring samples existing main-view acknowledgements at at most10Hz, with extra trigger records, at most16events and five-second context. Native instrumentation records missed events in bounded storage and writes on shutdown. CDP detaches during flight; PDH/profiling are disabled. Native wall time, view performance time and AudioContext have independent origins, and native status is delivered asynchronously. Tuples bound observations; they do not precisely align execution events. Native lifetime records may include preparation and Stop tails. The correction maxima below are over **recorded misses**, not all clock updates. Source-wait flags associate a miss with a condition, not exclusive time attribution. Percentiles are histogram upper bounds; maximum active interval is not an individual Present duration or physical scanout measurement.

The old-host420s accumulation experiment covers the historical364–390s failure window without seeking past accumulation:64skips,0underruns,140.562ms maximum active interval,19.0/26.9ms p95/p99. It does not reproduce the old4.629s stall. Several missed events show254.9–323.8ms clock corrections at sequence phases6.23–6.32 modulo8s, consistent with two-second-ahead PCM prefetch. Their small prior Present/context times do not explain those clock jumps; other events have longer Present times. This supports investigating/removing the convoy, not assigning every historical miss to it.

## Matched short playback results — every run retained

Identical generated original4K H.264 sources, three video plus three audio tracks,600s/7200-clip program,960×540 composition,356×200 physical child surface at1.75DPR. Observe60s continuously from the beginning; detached CDP, existing bounded recorders, no PDH/heap sampling. All four have held sampled visibility and AC power, advancing audio,0underruns and no browser errors. Available RAM and sampled system CPU are retained in the [numeric record](benchmarks/native3410/root-cause-results.json); thermal throttling is not observable. Probe commit identifies driver source, while host/native SHA256 identify executed binaries: the frozen349 host remains distinct from3410 despite the same probe commit.

| Order / case | Host | Skips | Active mean ms | p95 / p99 ms | Maximum active interval ms | Largest absolute clock correction at recorded miss ms |
|---|---|---:|---:|---:|---:|---:|
|1 baseline60|Frozen349|202|17.6714|25.6 /41.9|557.042|487.692|
|2 fixed60|3410 candidate|35|16.8339|25.0 /40.4|93.710|90.441|
|3 reverse-fixed60|3410 candidate|27|16.8021|25.0 /39.7|66.659|52.074|
|4 reverse-baseline60|Frozen349|32|16.8253|24.6 /33.7|115.052|300.603|

No run is discarded. The candidate has lower maxima in both pairs, but the baseline varies202→32skips and the reverse candidate has worse p99. These two pairs establish neither equality to the protected348 ten-run cohort nor universally smoother4K60. They are attribution diagnostics at reduced preview resolution, not new protected consistency scores. No new physical A/V drift or full-resolution qualification follows. No unexplained host closure occurred in these completed probes; earlier target losses and visibility failures remain in the historical reports.

## Memory allocation and retention

Separate matched90s sampling (128KiB interval, includes collected objects, no forcedGC) attributes62,655,300 sampled bytes to old `updateMeter` and **zero attributed samples** to the indexed candidate, verified over the entire raw tree, not only the top30 summary. This supports retaining the low-risk iteration correction for churn reduction. It does not mean literally zero allocations or a demonstrated reduction in retained/private memory. Request/rateValue allocation remains. Sampling perturbs execution: old3skips versus candidate25, both0underruns; these results are retained and are not acceptance-score replacements.

| Aggregate WebView private commit MiB | Frozen349 |3410 candidate |
|---|---:|---:|
|Prepared|1429.078|1425.352|
|Active end|1173.117|1346.672|
|Stopped|1164.000|1338.828|
|30s natural idle, noGC|993.449|1353.508|
|Native released|987.633|1352.262|

Candidate private commit remains higher despite less sampled meter churn. Baseline nodes5045→9271→4999 and listeners525→1135→627 (prepared/active/idle); candidate5046→9151→5002 and525→1135→627. Idle JS used heap is10.03MiB baseline/10.58MiB candidate, much smaller than private commit. Some DOM/JS churn reclaims naturally, while aggregate browser pools/media/GPU/external allocations are not attributed. Neither an unbounded application leak nor a stable active-session plateau is established. No effective cache, history, queue or precision capacity is reduced to improve these figures.

## Installed validation and preserved failures

- Full loopback-only regression:124/124passed in33.506s before the last two race tests were added; all four lock tests subsequently pass in0.017s. Existing actual PCM/seek/cancel tests, two meter tests, three recorder tests and two allocation-summary privacy tests pass. Final local JavaScript suite22/22 and evidence-binding2/2 pass. The final CI target includes126Python tests per normal/offline run and22JavaScript tests; actual exact-head receipts belong in PR #7.
- Installed native playback/seek, PCM transport, resize/modal alignment and renderer-failure/unsupported-effect fallback pass. Renderer/browser fault injection restores drafts and paused position, preserves exact content of all80undo states and exact tracks/output, and verifies undo/redo, retry and observer detach behavior. No checkpoint format or history capacity changes.
- Matched UHD60 libx264 export correctness: baseline7.148s, candidate7.354s, each180frames fully decoded,SSIM0.997805,48kHz AAC and0endpoint difference. One pair cannot demonstrate a speedup or establish a throughput regression; no export optimization was introduced in this continuation.
- MSI upgrade/uninstall/reinstall each exit0, preserving protected project/settings data. Packaged/installed modules, web code, native runtime and approved icon resources match source. MSI version3.4.10 SHA256 `8d8cd097de5d2dfd67bb14c0c2c6a16f5750a6a9c004da8ee0371acf844821d2`. Native binary remains `ac206038cea559f87d784e0ec4fc8485bdebd1421b7c4a78853e7ea037e3f72a`. Frozen349 host/MSI remain intact. This is a local development installer, not public binary redistribution or a signed stable release.
- Completed supervised cases report0owned survivors/new visible terminal windows after cleanup. This does not prove no fleeting intermediate window or all driver resources across an extended session.
- Retained failures include the first recorder-injection smoke failure before playback (Playwright invoked a returned installer with null options), a malformed initial PCM test fixture, and the valid old-code compiler-barrier failure. A superseded-stream cleanup assertion in the repro was corrected. A full-suite wrapper with no captured test output is not counted; only the subsequent direct124-test output is verification. Historical performance/visibility/underrun failures are untouched. Passing command exit status is never substituted for missing per-test evidence.

All new playback evidence uses generated media. Existing camera,348/349ten-run and endurance results remain historical qualification, not newly repeated acceptance of3410. No originals, frames, metadata, raw profiles or identifying paths are published. Final private-source hash/history audit and exact-head Windows CI are recorded with delivery. Production sources/bundle are frozen at7767d09; subsequent changes add tests, documentation and evidence binding only.

## Remaining blockers and next discriminating experiment

The confirmed convoy is corrected, but the historical4.629s gap/657underruns and late active renderer growth are unresolved. These results do not qualify full-resolution4K60, long physical synchronization, extended editing, clean-machine/multiple-driver behavior or a memory plateau. The current development build is suitable for controlled exploratory editing with recovery protections, not a qualified long/unattended production workload. HDR production development should remain gated on stabilization.

Next stall experiment, if authorized in a later continuation: one corrected-host continuous accumulation run with this detached bounded recorder, covering the historical364–390s window, and a failure-triggered local Windows CPU scheduling/D3D presentation trace. Calibrate monotonic/QPC origins before comparing execution events; identify whether lock-free clock delivery continues during any Present/source gap. Do not seek past accumulation or repeat unrelated ten-run cohorts first. For memory, compare renderer heap retainers/detached nodes with browser media/GPU/shared-memory resource ownership at prepared/active/idle on that workload; allocation sampling alone cannot assign retained private commit. No additional30-minute loop is justified until these discriminators exist.
