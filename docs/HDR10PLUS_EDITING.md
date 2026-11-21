# HDR10+ and real-world editing qualification

## Starting point and acceptance

The development branch starts at PR #8 head 7d1b2b4. PRs #1–#8 remain open drafts. The starting tree is clean. The installed executable SHA-256 matches the recorded 3.5.1 package built from production commit 3487af7. The 3.4 label in the interface does not identify that source revision.

Issues #9 and #10 describe an invalid native MP4 filter, a reproduced PNG demux/loop failure on FFmpeg 7.1, scene-boundary-only export progress and interactive editing limitations. The owner separately reports a successful repaired 21m47s UHD60 HEVC AMF export in about 2h41m. That result is field evidence and does not benchmark this branch. Preserve historical playback, audio and memory results.

- A. Verify installed Save As, cancellation, overwrite/source protection and Unicode destinations. Decode representative UHD60 mixed-media exports, including metadata-bearing PNG, transparent PNG and JPEG. Measure actual frame/stage progress and export throughput against a frozen workload.
- B. Verify cancellable per-frame HDR10+ indexing, timestamp mapping and conservative metadata reuse. Require independent decoded picture, timing and metadata checks for any HDR10+ output claim. Keep the existing HDR10 and SDR paths.
- C. Deliver testable editing improvements with save/reopen, undo/redo and picture/audio checks. Record incomplete requirements from issue #9.
- D. Measure affected interactive workflows and retain every failed attempt. Use short runs to isolate individual defects. Keep private sources, saved projects and local diagnostic logs outside Git.

Each checkpoint is published separately as it becomes reviewable. Production changes require a freshly built and verified development installer.

## A. Export fixes in development

The native Save dialog uses the codec-neutral filter `MP4 video (*.mp4)`. The normal export panel accepts a path or browses for one, checks source aliases and requires explicit confirmation for an existing target. Export publishes the completed MP4 atomically. A new file appearing during rendering is protected when overwrite was not authorized. The last accepted directory is remembered. The panel shows CPU settings only when relevant and places HDR declarations under Advanced.

PNG and JPEG use FFmpeg image2 with literal filenames. The renderer decodes and resizes once per segment, then holds the picture before the animated filters so motion and fades still run at sequence rate. Tests check eXIf and alpha, JPEG orientation, source hashes, mixed timeline audio and decoded frames. The new fixture initially failed because the opaque background was above its alpha layer, then because downscaling blended both orientation patches. Both attempts are retained.

The state endpoint reports stage, segment count, FFmpeg frames and encoded duration, processing FPS, elapsed time, most recent progress and fallback. The overall percentage weights stage work. It is not a wall-clock projection and currently supplies no ETA. A period without reported progress is shown separately from failure. The independent stream drains and final stream-copy video mux remain in place. Concurrent proxy impact, process and disk costs on the owner’s 30-segment workload remain open.

One matched 5.4-second UHD60 generated PNG/JPEG/video + audio libx264 pair measured 69.390s frozen and 23.181s candidate, 4.669 and 13.977 processing FPS. Both decoded 324 frames with matching 5.4s video/audio endpoints. Decoded 96×54 RGB mean absolute error was 0.0. All generated input hashes matched. This is one still-heavy pair. See [the numeric record](benchmarks/p0-realworld-performance.json).

The installed 3.5.1 error reproduced. The initial 3.5.2 installer passed lifecycle and installed-bundle checks. Two packaged GUI attempts exposed an unregistered test asset, then a real missing `ultrafast` option for an existing project. The latter is corrected for 3.5.3. The requalification results are tracked separately. All 143 local offline Python tests passed before the UI-only saved-preset correction, and four focused color-control JS tests passed.

The installed 3.5.3 candidate passed the native dialog and export workflow. Cancel returned with no job. Browsing chose a Unicode filename in a Unicode directory. HEVC AMD AMF exported 324 decoded 3840×2160/60 frames in 25.1s, with 5.4s A/V endpoints, yuv420p and preserved camera audio. In-scene FFmpeg frame progress was observed, original hashes matched, and the completion control exposed the output-folder action. The test used the installed offline WebView session. Output-folder shell launch and the repeated confirmation dialog were not driven in this test. The separate atomic publication test covers the no-clobber and authorized overwrite paths.

The local 3.5.3 MSI passed upgrade, removal and reinstall, retaining project/settings data. Installed source, native runtime and approved icons match. MSI SHA-256 `d6ff9b50336a09af65010f1d14a6dfbf089af23b2aa68fec751dfb61f4f2c30f`. See [sanitized installer and export receipt](benchmarks/p0-installed-export.json).

## B. HDR10+ source metadata index

Technical Input Color offers a local scan of original Rec.2020 PQ HEVC files. It caches presentation ticks and bounded decoded metadata on disk. It streams FFprobe XML to preserve repeated fields that may collide in object-like output. A single cancellable low-priority worker publishes a completed index atomically and reuses it while source identity and schema match. It leaves the source and its embedded metadata intact. Tests exercise late metadata, VFR holds, trimming, clip moves, speed changes, malformed data, duplicate timestamps and cancellation.

The index distinguishes structural rejection from version 1 distribution conformance. It records supported decoded fields as observations. Metadata with nonconforming distribution values remains in the cache for diagnosis and is rejected by the frame mapping for reuse. ST 2094-40 §8.5.4 gives the 5% and 10% entries special meaning when they appear in the specified positions. The first real-source attempt used an overly broad monotonicity assumption. Both the failure and the follow-up conformance checks are retained. See [SMPTE ST 2094-40](https://pub.smpte.org/pub/st2094-40/st2094-40-2020.pdf) and [FFprobe XML output](https://ffmpeg.org/ffprobe.html#xml).

Frame mapping associates output sequence frame numbers with original PTS using rational clip placement, time and speed. A held picture retains its own metadata. A new picture with no decoded metadata stays untagged. Mapping is a development capability. It is not wired to encoding, and it does not authorize reuse after picture changes. HDR10+ export remains explicitly unavailable. The supported HDR10 path is unchanged. Exposure, titles, transitions, scaling and other image changes require qualified regeneration. x265's dynamic metadata input can carry prepared creative intent, but does not author that intent for the picture. See [x265 encoder options](https://x265.readthedocs.io/en/latest/cli.html).

Separate future delivery gates cover a Samsung HDR10+ master with verified frame association and compatible TV playback, and a YouTube 4K60 PQ Main10 upload master with valid static signaling. Neither preset is exposed as a completed profile. YouTube’s own encode and playback behavior requires separate verification.

Two full-original attempts exceeded their 210-second per-source harness deadline with one decoder thread and produced no qualified complete index. The final candidate uses three low-priority decoder threads and reports the decoded-frame count during the scan. Bounded stream-copy samples beginning at the two private PQ recordings decoded 105 and 99 frames with three distinct input tick intervals each. All 204 frames preserve structurally decoded metadata. All 204 were blocked from reuse by the distribution conformance check. Sample jobs took 7.106s and 4.246s on this workstation while other QA was active. Cache reuse and cancellation without partial index publication passed. The 1.5s sample trim was performed by packet copy and can include additional retained frames. See [the sanitized source result](benchmarks/p0-hdr10plus-source-index.json).

## C. Timeline and sequence controls

Magnetic snapping supports clip edges and optional frame, 0.5s, 1s, 5s and 10s targets. Dragging and ruler scrubbing show a snap guide. Trimming reports live timeline in/out and duration without rebuilding the full timeline on each pointer move. The existing edit command still verifies linked or locked source constraints before committing a trim. Numeric clip duration rounds to the nearest sequence frame. At fractional FPS an exact wall-clock boundary can fall between frames.

Zoom anchors to a visible playhead, otherwise the viewport center. Ctrl-wheel uses the cursor. Follow edge/center/off is separate and pauses temporarily after manual timeline interaction. Ruler drag submits at most one different-frame seek per animation frame and coalesces intervening pointer events. This reduces request opportunities. It does not measure decoder latency, sustained FPS or memory stabilization.

Project Inspector supports 16:9, 9:16, 1:1, 4:3, 21:9 and custom even dimensions. The canvas changes through undoable project settings and preserves each clip's fit and spatial transforms. Preview and render use those settings. Reframing still needs visual review when canvas proportions change.

The local desktop source test linked 32 generated assets. It verified a real mouse trim snapping an eight-second photo to exactly 600 frames at 60 FPS, live feedback and guide, undo/redo, zoom anchor within 0.15 CSS px, portrait preview shape and custom dimensions across a separate project reopen. Two earlier attempts remain retained. One detected a missing inspector helper during development and the other tested the selection after undo deliberately cleared it. See [the numeric record](benchmarks/p0-timeline-editing.json). Installed qualification follows on the combined development build.

Still open from issue #9: project-wide/default animation presets and transition authoring, keyframe editor redesign, Media Library sizing/layout and undoable removal, clearer source-audio separation, taskbar artwork occupancy, and a storage-management panel. Existing export scratch cleanup is retained. Unresolved long-playback stalls, audio underruns, active WebView memory behavior, proxy contention and full-resolution playback need matched measurements. The owner’s full project was not opened or re-exported.

## Combined 3.5.4 development installer

Local development MSI SHA-256 `2371a0ce72a6aca7a7e1e75feb7bb79d427e43825e5b0bbcf7aa6cb002d0ab80`. Upgrade, uninstall and reinstall exited successfully and preserved project/settings data. The installed bundle matches the source, approved icon and native runtime. The installed AMD AMF retest took 26.1s for 324 frames at 3840×2160/60 with 5.4s matching A/V endpoints. The installed timeline mouse and reopen checks pass. The installed HDR10 control test also scans a generated PQ original with no dynamic metadata, validates genuine 10-bit HDR10 delivery and checks exact 80-entry history and draft after renderer/browser recovery. Three protected originals pass final hash and mtime verification.

[Sanitized final installer and local attempt ledger](benchmarks/p0-realworld-final.json). The published A/first C CI histories record a canonical-path fixture assertion and FFmpeg 9.1 deviation in the existing opaque-base decoded-color gate. CI now pins the verified 9.0.2 Gyan package and publisher archive SHA-256 to match the local runtime. The decoded-color tolerance remains unchanged. Support for 9.1 remains open. Final-commit Actions results are recorded in the draft PR.
