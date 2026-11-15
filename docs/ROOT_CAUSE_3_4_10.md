# Root-cause hypotheses — 3.4.10 continuation

Starting checkpoint1ab1e62, same branch and draft PR #7. Historical failures remain open. This matrix precedes instrumentation changes. No production correction is justified yet.

| Hypothesis | Observed evidence | Missing discriminator / next action |
|---|---|---|
| Source availability / demux / I/O starvation |1137 skips were source-wait-associated;1061 skipped-counter increments occur before recorded late occlusion | Sticky source-wait association is not time attribution. Enable existing bounded native missed-event recorder: source-selection duration, loop gap, prior Present, context wait, clock age and GPU-wait flags. It does not itself separate demux from disk/CPU scheduling. |
| Present/context/GPU stall |4.629s interval,1.408s individual Present maximum,0GPU-queue-associated skips | Need event context rather than unrelated lifetime maxima. Correlate native missed-event records with bounded UI/audio acknowledgements; retain independent clock origins and uncertainty. |
| Audio starvation / main-view delivery pause |657 underruns in one600s diagnostic; a150s attempt did not reproduce | Ring history before/after an underrun: queued samples, consumed/sent samples, audio context end, UI/native clock observations. Preserve processor counters and buffers. |
| Observer/CPU contention | PDH calls can be expensive; failures also appear in frozen348 | Use detached observation with native event recording, no PDH sampling; report this changed observer as attribution only, never a replacement protected score. |
| Renderer JS/DOM/media retention | Renderer commit614→1406MiB; short natural idle reclaims149–194MiB | Separate sampled JS allocation stacks and DOM counters from private commit/UMA; profile in a separate short run so profiling does not contaminate stall timing. No active GC. |
| Legitimate undo/cache/allocator high water |80undo states retained; post-stop heap~48MiB; native caches bounded | Active allocation profile cannot establish an unbounded leak or allocator ownership alone. Keep caches/history intact; compare natural idle before any explicit GC. |

Necessary accumulation experiment: one600-second generated7200-clip program, observed continuously through420seconds to cover historical364–390seconds. Seeking to minute six would not reproduce accumulation. Exact program-end sample count is not asserted for this partial diagnostic. Audio counters, actual elapsed, physical/composition sizes, visibility, code/binary identity and event context will be retained. No new30-minute editing test is planned.
