# VlogCraft Studio 3.5.7 HDR editing

Starts at verified draft PR #13 head `8b7b394795f8a1b085ac789453851d3a43c3995b`. Issues [#9](https://github.com/JakubSoltysiak/VlogCraft/issues/9) and [#10](https://github.com/JakubSoltysiak/VlogCraft/issues/10) cover the original timeline, library and Windows export failures. The 3.5.6 installer and all prior verification evidence remain the comparison baseline.

Qualify managed stills and titles in the existing scene compositor first. Its working space, existing PQ conversion and frame-by-frame metadata authoring remain the reference. Then qualify boundary transitions and audio timing, storage ownership and installed workflows in separate checkpoints. Use deterministic generated pictures and audio and verify decoded output before considering the 60-second workload. Source recordings and the owner's project remain private and read-only.

## Managed photographs, titles and transforms

Managed PNG/JPEG uses explicit image demux, EXIF orientation and sRGB interpretation for ordinary stills. RGB and alpha are promoted separately. Premultiplied float32 resizing and inverse geometry avoid edge halos, and masked compositing retains luminance above SDR white. The first implementation exposed both alpha-associated nonlinear conversion and clipping in a float RGB format converter. The final graph uses direct planar extraction and merging and leaves the existing opaque video path intact. It decodes a still once per render segment and caches only the title raster in that render job. [sRGB encoding](https://registry.color.org/rgb-registry/srgb), [FFmpeg filters](https://ffmpeg.org/ffmpeg-filters.html).

The existing clip timeline, title editor, fit and motion keys drive the same managed compositor for Reference, Composited and export. The authoring stage analyzes their final PQ pictures. The supported scope adds scale, position, rotation, opacity, basic feathered rectangle/ellipse, contrast and saturation. Arbitrary paths, unsupported embedded photo profiles, chroma key, HLG/Log and SDR creative LUTs remain gated. The first decoded fixtures passed oriented JPEG at 200 cd/m² reference white, translucent PNG over a 1,000 cd/m² source, animated title/edited HDR10+ and an animated 800 cd/m² masked video layer. Thirty focused HDR tests passed.

## Cut boundaries and PCM

Transitions are stored on an incoming clip with the outgoing clip ID, integer duration and easing. The centered interval requires genuine video/audio source handles. Stills can hold their one source picture. Invalid handles and overlapping pairs are reported. Original cuts, source range edits and sequence duration remain intact. A dissolve renders both alternatives over the same lower-layer picture before blending float32 light. Dip to black and dip to configured SDR reference white are available in managed color. The Composited monitor partitions its video preview at transition endpoints and uses the same audio envelope over the full range. Live Layers and Native route to Composited for these projects.

Independent audio boundaries provide linear and equal-power crossfades. Embedded or aligned linked camera audio can explicitly follow a video transition. Envelope endpoints use rounded sequence-frame-to-48-kHz sample budgets. The focused 29.97 fps stereo PCM fixture matched contiguous output and concatenated export segments sample for sample for both curves. The managed HDR dissolve passed decoded linear value checks and per-frame metadata verification, and both dips passed the midpoint check. The first compiler refactor failed a closure assertion before its fix. The real preview cache then passed the segmented-video path with explicit per-phase progress. In the source Windows app the timeline marker, undo/redo, saved reopen and matched static/HDR10+ delivery passed on a mixed photo/title/video sequence of 18 frames.

## Export scratch ownership

New export jobs lease their own registered scratch directory. Normal success, failure and cancellation use the recorded folder identity. The Storage action can reclaim abandoned registered scratch after confirmation. It rejects live leases, reachable media workers, linked source paths in the current project, reparse points, hard links and unexpected contents. Legacy unregistered folders and full proxy and preview cleanup remain outside this action. Three focused tests covered concurrent claims, an actual abruptly terminated owner, current-project source protection, a retained foreign file and failed/cancelled cleanup.

## Installed qualification and unchanged-path control

The Windows MSI was built from `9eb1160bf8569a277febafc27b01d411eb21c971`. SHA-256 is `c6963b94160c796b4650c2a1ecb4e7d8af7ae844c4f27d6540203e98e538f90d`. Local upgrade from 3.5.6, uninstall and reinstall preserved seven protected files. Installed code, web assets and native binaries matched the source bundle. MSI, executable and editor version labels all report 3.5.7.

- The installed editing fixture exported 18 mixed-media pictures over 0.75 seconds with decoded static/HDR10+ equality, valid per-picture dynamic metadata, Unicode destination, a measured 200/400/600/800 cd/m² dissolve, undo and redo, and saved reopen.
- The 129-asset library test passed list scroll/resizing, protected active media, removal/undo/restore and thumbnail regeneration. Camera separation produced the same 38,400 decoded PCM bytes. The inputs remained unchanged. General missing-media workflow is inherited.
- Installed HDR10 monitoring and WebView renderer/browser recovery passed with exact 80-state history. Preserve Original, icon resources, and native Save As/cancel also passed. AMD HEVC SDR produced 324 pictures with matching 5.4 s video/audio endpoints.
- The local loopback suite passed 165 Python tests and the JavaScript suites passed 29 tests. All three retained private original hashes matched. The owner’s project and original media were outside the test fixture.

| Same six-frame UHD60 fixture | Verified 3.5.6 | Installed 3.5.7 |
|---|---:|---:|
| Static HDR10 | 16.6 s | 17.5 s |
| Samsung HDR10+ | 17.4 s | 16.5 s |
| YouTube HDR10 | 15.2 s | 15.1 s |

Both builds independently decoded all six full-resolution pictures and preserved their audio/video clocks. The 3.5.7 static and Samsung decoded streams matched exactly. Media-worker working set peaked around 1,160 MiB in the 3.5.7 runs. The single-trial timings vary and do not establish a speed change. Actual Samsung playback and YouTube transcoding remain open. The prior renderer could not execute the new mixed still/title/transition workload, so this compatible control is separate from the new workload.

## Mixed HDR10+ workload

The generated scene combines two PQ camera videos with embedded AAC, an SDR JPEG, transparent PNG, animated title, two dissolves, a camera audio crossfade, exposure and background music. They use 60 FPS, CPU x265, 48 kHz stereo and the same independently decoded static picture and audio as the edited master input. The test kept all media local. It emitted one ST 2094-40 record per picture, preserved exact decoded picture/PCM and checked intended endpoints.

| Case | Result | Static render | HDR10+ stage | Peak summed process RSS | Peak sampled scratch |
|---|---|---:|---:|---:|---:|
| 120 frames, 1280 × 720, spatial photo motion | Timed out in scene 7 of 7 at 190.109 s | — | — | — | — |
| 48 frames, 640 × 360, spatial photo motion | Passed | 21.094 s | 0.515 s | 281.9 MiB | 274,560 bytes |
| 24 frames, 3840 × 2160, UHD sources, photo opacity motion | Passed | 140.109 s | 4.656 s | 5.16 GiB | 297,081 bytes |

The UHD60 run maintained the 19,200-sample endpoint and all 24 metadata associations, with 14 distinct average maxRGB values. Whole-run throughput was 0.166 output FPS. Sampled CPU time was 156.36 CPU-seconds. FFmpeg/render process startup and cleanup are included in timing. Working sets across the process tree can count shared RAM more than once. Scratch results come from unusually compressible synthetic video and are not useful space estimates for a long project. GPU utilization was not sampled.

The supervisor observed work until the 720p timeout and cleaned all owned processes. That run has no completed output or peak-memory report. The two controls verify geometry at reduced size and the rest of the workflow at full size. The full UHD case uses opacity motion rather than spatial photo motion, so it does not resolve the throughput issue. The 60-second workload was not attempted and remains unqualified. The measured bottleneck in the completed UHD control was picture rendering, with about 3.2% of elapsed time in the later HDR10+ stage. [Raw sanitized observations](benchmarks/studio-3.5.7-hdr-editing.json).

The retained local failures also include the initial nonlinear alpha fixture, a direct float-plane negotiation failure, and a transition compiler closure failure. Their focused retries passed after correction. All earlier evidence remains in the QA ledger.

## Pre-3.6.0 readiness

| Gate | Result |
|---|---|
| A. HDR10+ | The installed mixed project and independently decoded fixtures qualify descriptive metadata, sRGB stills, title animation, basic geometry, masks, contrast and centered dissolves. Creative curves/LUTs, wider photo profiles, HLG/Log and the remaining transition kinds stay gated. |
| B. Editing | Verified one boundary through the desktop UI, with undo/redo and reopen, timeline geometry, exact linear/equal-power audio mapping, grouped camera audio separation and 129-asset handling. Batch/default boundaries and recursive motion are implemented. The installed boundary check used a single selected cut. |
| C. Export | Local installed path, Save As, cancel, format signaling, picture/PCM equality and registered scratch ownership passed bounded cases. General proxy/preview/legacy scratch cleanup is open. |
| D. Workload reliability | The two-second 720p mixed spatial workload exceeded the 190-second cap with work still observed. Production throughput with animated 4K stills and the 60-second gate remain open. Historical WebView/native playback and long-session resource problems stay separate. |

**Verdict: Not ready for a general 3.6.0 hand-off.** The targeted 3.5.x follow-up should address the new mixed spatial workload, then independently qualify the full-size path on a 60-second sequence before expanding the optimization campaign. No picture-quality reduction or implicit HDR downgrade is used to pass a timing test.
