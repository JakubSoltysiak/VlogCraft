# Playback consistency — 3.4.8 development

Continues verified 3.4.7 commit 429f7b11270238d01c77ef5583876aaa7d12e370 on codex/studio-3.4.8-consistency. The approved visual asset update is isolated in commit 46df8f9 and [ICON_UPDATE.md](ICON_UPDATE.md). PRs #1–#4 stay unmerged. The canonical main roadmap, including its later optional enhancement backlog, is preserved.

## Conditions and method

Owner workstation: ASUS Zenbook S16 / Ryzen AI 9 HX 370 (12 physical,24 logical), Radeon 890M driver32.0.32015.7029,32GiB RAM,Micron NVMe,Windows11 build26300. AC and nominal120Hz were locally rechecked; Balanced power plan stayed unchanged. Temperatures and trustworthy GPU occupancy were unavailable. No affinity, global priority, timer-resolution, power, firmware or display settings were changed.

The primary workload remains125seconds,three original4K H.264 video streams,three audio tracks,1,500clips,960×540 composition and a small356×200 presentation surface; no proxies or intermediate encoded picture preview. This is not native-resolution4K output. Each trial opens a fresh frozen application and repeats source offsets; OS filesystem caches are unmanaged. The historical FPS denominator, including the end-observation polling tail, is retained. Native Present calls/distinct sequence submissions are not physical scanout.

Ten complete unchanged-engine trials required eleven attempts. Present rates:59.371,59.525,59.495,59.536,59.766,58.782,59.782,59.679,59.851,59.849FPS. Skips:50,47,48,7,20,128,19,5,8,12. Median59.608FPS,worst58.782,best59.851; seven of ten reached59.5FPS. Every completed trial had6,000,000samples and zero underruns. The incomplete eighth attempt closed its WebView page around5.57seconds. The owner confirmed they did not close it. No matching Windows application-crash event was found. It remains an unexplained reliability failure; it is not discarded or claimed fixed.

## Confirmed critical-path findings

A WebView thread used about78% of one logical core in one baseline; aggregate CPU was not evidence that adding decoder workers would help. The30second browser control measured3,581layouts,17.021s main-task work,1.142s layout and.479s style work. Native GPU composition remained roughly.7–.8ms. CSS/DOM playhead and meter updates repeatedly invalidated layout on the120Hz desktop.

A telemetry-only125second control retained scheduling/image behavior and added playback-only p99 timing. It measured59.624FPS/14skips,p95 Present interval18.5ms,p9930.2ms,max59.9ms. Miss events distinguished large clock-anchor corrections (roughly83–195ms at some misses with short source/Present work) from blocking Present calls around33–41ms. Zero GPU-slot starvation was observed in that control. These are measured associations, not proof of the origin of every driver/clock delay. Lifetime timing includes initial paused preparation; the new playback-only interval excludes that gap.

The improved UI translates the playhead on a compositor layer and avoids duplicate native sequence-frame paints. Audio peaks are still sampled at every animation callback, accumulated, and painted at30Hz; a unit test verifies a transient survives between display updates. Monitor geometry is cached with resize/DPI/ancestor-scroll invalidation, excluding unrelated timeline scrolling. Required picture effects, source timestamps, audio processing and export quality are not disabled.

The final30second UI diagnostic measured11.317s main-task work,.586s layout and.214s style work versus17.021/1.142/.479 in the control. Its first125second pilot measured59.902FPS,five skips,zero underruns and6.05% CPU versus the ten-run baseline median8.895%. That pilot is not repeated-run acceptance.

## CPU workers and export

Three repeats each of one,two,four hardware-decoder workers produced offscreen medians95.98/98.70/98.51FPS. This is an unlimited offscreen diagnostic, not playback FPS. Frame threading became active for2/4 workers, increasing hardware pools37→39/41frames per source and increasing lock-wait tails. The default remains one worker; no all-core affinity/priority policy was introduced.

Alternating3second UHD H.264 exports kept codec,preset,CRF,rate,pixel format and source fixed. Decode/filter/encode configurations1/1/4,1/1/8,2/1/4,1/2/4 had medians6.409/4.748/5.931/5.685seconds. Eight encoder workers were faster in all three trials; worst5.563s versus7.105s. All180frames decoded. Minimum SSIM against the original was.997753 at4 and.997805 at8. The two-decoder configuration worsened the worst time to7.877s despite a better median and was rejected. Filter concurrency remains one, preserving the independent-stream drain design.

The adopted encoder budget is eight only for libx264,3840×2160,at most60FPS,on16+ logical processors with at least4GiB currently available RAM. Other codecs,dimensions,rates and constrained machines retain four. It changes worker count, not user codec/quality options. Long-form and other-hardware speedup are not established by these short trials.

## Memory and diagnostics

Counters now expose hardware-pool frames,retained texture arrays and an allocation-size estimate alongside bounded queues/cache/views. The estimate is not allocator/VRAM truth. Summed working sets may count shared UMA pages more than once; per-process private commit and per-thread CPU are recorded separately. Native texture-view ownership remains bounded; no general leak-free claim follows from one session.

The local benchmark framework now retains per-core load,anonymous per-thread CPU,private commit and one/ten-second counter windows. Counter windows are sampled estimates,not physical display intervals. Regression gates consider worst results as well as medians and require an observer contract. New failure handling preserves partial data and local app/native shutdown logs. Browser-process failure and window-close reasons are logged locally without source names/paths.

## Final packaged ten-run comparison

The six remaining trials completed after the interruption. No passing trial was restarted. All ten use the packaged candidate, without injected UI functions. Rows pair chronological completed runs, not simultaneous matched pairs. Baseline required eleven attempts; its failed attempt remains separately reported above.

| Completed trial | 3.4.7 FPS | Skips | 3.4.8 FPS | Skips | Candidate peak RSS MiB |
|---|---:|---:|---:|---:|---:|
| 1 | 59.371 | 50 | 59.800 | 14 | 3387.0 |
| 2 | 59.525 | 47 | 59.750 | 10 | 3252.0 |
| 3 | 59.495 | 48 | 59.872 | 2 | 3501.4 |
| 4 | 59.536 | 7 | 59.821 | 2 | 3343.9 |
| 5 | 59.766 | 20 | 59.637 | 16 | 3413.7 |
| 6 | 58.782 | 128 | 59.857 | 3 | 3338.2 |
| 7 | 59.782 | 19 | 59.777 | 2 | 3279.5 |
| 8 | 59.679 | 5 | 59.858 | 5 | 3464.1 |
| 9 | 59.851 | 8 | 59.670 | 4 | 3377.4 |
| 10 | 59.849 | 12 | 59.848 | 3 | 3317.4 |

| Across completed trials | 3.4.7 unchanged engine | 3.4.8 packaged candidate |
|---|---:|---:|
| Best / median / worst FPS | 59.851 / 59.608 / 58.782 | 59.872 / 59.810 / 59.637 |
| Across-run fifth percentile FPS | 59.047 | 59.652 |
| Population standard deviation FPS | .30348 | .07742 |
| Runs at least 59.5 FPS | 7/10 | 10/10 |
| Skips minimum / median / maximum | 5 / 19.5 / 128 | 2 / 3.5 / 16 |
| Runs below 30 skips | 6/10 | 10/10 |
| Median machine CPU | 8.895% | 6.185% |
| Median peak summed working set | 3373.8 MiB | 3360.7 MiB |
| Median peak summed private commit | 4775.4 MiB | 4739.6 MiB |
| Median native first-ready | .980 s | .899 s |
| Median frozen application-ready | 2.240 s | 1.985 s |
| Worst active sampled 1 s / 10 s | 32.967 / 53.375 FPS | 56.545 / 59.156 FPS |

All twenty completed trials reached exactly 6,000,000 stereo sample frames with zero underruns. The initial investigation target passes, but skipped frames and presentation tails prevent a stall-free or physical-sync claim. CPU median fell 30.47%; peak memory is essentially unchanged, rather than a large memory optimization. Neither temperature nor energy was measured. The arms were sequential; the short encoder experiments alternated configurations, but temperature/cache drift remains a limitation of the ten-run comparison.

Candidate active Present-interval p50 is 16.7 ms; per-run p95 spans 17.7–17.9 ms (median 17.8), p99 spans 21.3–33.7 ms (median 25.1), and the longest interval is 60.221 ms. Histogram quantiles are 0.1 ms bucket upper bounds. The variance **across ten run-mean intervals** is .00013185 ms² (SD .011483 ms); the per-frame variance was not retained and cannot be reconstructed from these quantiles. Unchanged 3.4.7 lacks p99 and its lifetime maximum includes paused preparation, so no fabricated matched p99/maximum improvement is claimed.

The raw minimum one-second candidate counter window was 33.771 FPS. Inspection located it at the terminal held frame, including paused status after sequence completion. The historical values remain in the JSON. A separately labeled active-window analysis excludes frame-zero preparation and terminal paused status in both arms; an automated regression covers that distinction. Whole-run FPS retains its original denominator. Candidate run 5 remains the worst full-run result (59.637 FPS, 16 skips), despite meeting the target; no outlier is discarded.

The bounded missed-frame trace for worst candidate trial 5 attributes 12 of its 16 missed deadlines to prior Present calls of 28.5–47.3 ms. Four coincide with positive clock-anchor corrections of 23.8–41.0 ms and short Present calls. Source selection was below .068 ms and context-lock wait below .003 ms at those recorded misses; neither source nor GPU-slot starvation was flagged. This locates those misses in presentation/clock delivery, rather than shader throughput, without proving a driver-level cause.

## Preview resolution matrix

All five 30-second cases used three original 4K sources and three audio tracks, no proxies, and a 356×200 physical surface. Each reached exactly 1,440,000 samples with zero underruns.

| Composition | Present calls/s | Skips |
|---|---:|---:|
| 960×540 | 59.664 | 0 |
| 1280×720 | 59.627 | 0 |
| 1920×1080 | 59.539 | 0 |
| 2560×1440 | 59.509 | 0 |
| 3840×2160 | 59.581 | 3 |

These short results establish selectable composition modes, not ten-minute full-size 4K presentation. Manual preview choices remain independent of export dimensions. Sustained 4K output and the highest consistently practical full-size preview quality require longer display-qualified trials.

## Endurance, failure retention and memory

The original FULL runner passed its first thirteen steps, including all ten consistency trials and all five resolutions, then failed endurance with TargetClosedError around95.4s (last persisted checkpoint95.1s). It had24skips and zero underruns before losing the target. The host was still alive when cleanup began and exited normally afterward; the only application log entries were the two-phase normal close. No WebView ProcessFailed or matching Windows application-crash/resource-exhaustion event was observed. Post-Playwright page-closed state cannot establish that the physical window closed. Neither this failure nor baseline attempt8 is silently reclassified as a pass. New observer-event/lifecycle diagnostics distinguish intentional disconnection and teardown; a successful retry is not proof of a repair.

The standalone600s retry completed in600.123s: **59.886 distinct/Present FPS,59skips,28,800,000 samples,zero underruns**, final completed frame35999. The historical3.4.7 endurance was59.872FPS/62skips; the small difference is not a statistically established speedup. Active interval p50/p95/p99=16.7/17.9/33.6ms,max191.769ms,three intervals≥100ms. Worst sampled1s/10s windows were50.531/58.123FPS. These tails remain real qualification concerns despite the whole-run average.

Peak summed working set was3451.8MiB. First30s→last30s medians were2862.3→3385.5MiB RSS and4141.7→4657.9MiB private commit. Per-process grouping locates nearly all sustained growth in WebView: median private commit975.3→1492.0MiB; native2282.4→2292.0MiB; host870.3→874.3MiB. Three retained texture arrays estimated1317.04MiB,48views,source queues≤4,GPU in-flight peak4≤6 and six cached frames/source remain bounded. This is not a general browser/native leak-free proof, and UMA RSS/private commit are distinct accounting measures.

A subsequent diagnostic used the same 600-second timeline for two 150-second arms, with the CDP automation observer attached and deliberately detached. External process sampling remained active; the detached host continued playback and was reattached before stopping. These are memory diagnostics, not additional FPS acceptance trials.

| WebView private commit | Observer attached | Observer detached |
|---|---:|---:|
| First 30-second median | 965.8 MiB | 1026.9 MiB |
| Last active 30-second median | 1171.6 MiB | 1136.6 MiB |
| After stop and forced GC | 983.9 MiB | 978.1 MiB |

Live JS heap after collection was about 10 MiB in both arms; DOM nodes returned to 4994 versus 4991 initially, and 4993 versus 4993. Both arms show reclaimable growth, with different starting allocations. Observer/caching/allocator effects may contribute; one arm per condition cannot assign all growth or prove long-term stability. No automatic GC policy or memory-pressure tweak was shipped. Intentional CDP disconnect also demonstrated that a closed automation page object does not by itself mean the physical application exited.

## Real originals and Windows qualification

Owner-identified Galaxy recordings A/B retain HEVCMain10/P010/PQ/BT2020,rotation−90,VFR and HDR10+ decode side data. Embedded device/lens/Log identification remains unavailable rather than inferred as verified. C is the owner-identified Google Earth H.264 animation with no source audio, not a Samsung recording. The three originals completed81.683/49.267/18.017s on the installed native path, exact3,920,800/2,364,800/864,800 sample frames,zero skips and zero underruns; C uses the existing silence clock. Nine bounded source-PTS seeks matched. FP16 readback was finite, with HDR RGB maxima17.953/14.352 above SDR white. No calibrated display or HDR10+ mastering claim follows.

Each private source produced a fully decoded60-frame,3840×2160/60 reference export using the **explicit existing8bit SDR delivery path**. The initial harness accepted A/B but rejected C's valid full-range yuvj420p label. The assertion now accepts that label; C's retained export was reverified without re-encoding. This is a harness correction, not a renderer repair, and the failed attempt remains recorded. Original SHA256 and mtimes match the before-test manifest; no original,frame,thumbnail,GPS,filename,source hash or identifying path is published.

The actual-DPI4K composition test passed30s at59.304 Present calls/s,zero skips,1,440,000 samples and zero underruns. Windows client2880×1676 at168DPI/175%; physical surface2545×1432. Historical3.4.7 measured59.393FPS/3skips on that scope; end-polling variation prevents a throughput-improvement claim. Original-resolution composition is distinct from physical4K scanout and long-duration4K acceptance.

Final installed tests passed two independent5,972,550,422-byte originals, native no-copy drop bridge,packet offset4,578,951,204,proxy cancel/retry,source review,grade/scopes,linked/nested undo,motion apply/undo,offline consent/approval/redo,reload and normal close. The output fully decoded84frames at3840×2160/60 with1.4s audio,RGB MAE.051. Native physical Explorer gestures are still outside automated qualification. External browser fetch was blocked through the installed test's closed-loopback proxy; frozen Python does not use the source socket guard, and no OS-firewall/physical-disconnect claim is made.

The final MSI upgrade/uninstall/reinstall returned0 and retained project/settings bytes. Its SHA256 is5ee56f789da88cf8ae765468df26f99ad16c7b8761eaf40892831f6708df7ed9. Final bundle verification matches23Python/engine modules,desktop,web,installed executable,native runtime/manifests and approved icon. The separate icon report retains exact seven-size,MSI/PE/shortcut/window/taskbar/favicon pixel checks and the unchanged master artwork.

## Regression and evidence

Initial packaged FULL source checks passed66Python and13JavaScript tests,precision,transport,rapid seeking/playback/fallback and export. The final offline Python run passed**67tests in23.106s**, including the added terminal-window regression. Historical drain stress passed20/20 with zero timeouts. All six CPU/AMD AMF H.264/HEVC/AV1 exports decoded. Installed1440p/source-mode/storage diagnostic tests passed. Precision remains877P010/PQlevels,relative PQ error.0001831,max125scRGB,and layered reference RGB MAE.008322. Seeking p50/p95 were417.1/608.6ms over12destinations; this is a completed GPU-frame endpoint, not scanout.

[Curated data](benchmarks/2026-11-14-native348) preserves numeric trial/failure/quality/resource results. [The performance record](benchmarks/studio-3.4.8-performance.json) binds all relevant production Python,web,native and packaging sources by LF-normalized SHA256. The permanent gate checks condition/observer contracts and worst as well as median results. Hosted Windows CI checks the final exact commit separately; it compiles/packages but does not qualify hardware GPU execution.


## Remaining production gates

The unexplained baseline WebView closure remains open even if later runs pass. Physical presentation/acoustic sync,actual GPU removal/reset,multiple displays/other hardware,longer memory traces,complete native effect parity,calibrated HDR/HLG/Log/mixed working spaces,HDR10+ mastering,GPU export,multichannel and signed/clean Windows deployment remain separate gates. No stable release or default-native switch is authorized by these measurements.
