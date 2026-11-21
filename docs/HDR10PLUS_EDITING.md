# HDR10+ and real-world editing qualification

## Starting point and acceptance

The development branch starts at PR #8 head 7d1b2b4. PRs #1–#8 remain open drafts. The starting tree is clean. The installed executable SHA-256 matches the recorded 3.5.1 package built from production commit 3487af7. The 3.4 label in the interface does not identify that source revision.

Issues #9 and #10 describe an invalid native MP4 filter, a reproduced PNG demux/loop failure on FFmpeg 7.1, scene-boundary-only export progress and interactive editing limitations. The owner separately reports a successful repaired 21m47s UHD60 HEVC AMF export in about 2h41m. That result is field evidence and does not benchmark this branch. Preserve historical playback, audio and memory results.

- A. Verify installed Save As, cancellation, overwrite/source protection and Unicode destinations. Decode representative UHD60 mixed-media exports, including metadata-bearing PNG, transparent PNG and JPEG. Measure actual frame/stage progress and export throughput against a frozen workload.
- B. Verify cancellable per-frame HDR10+ indexing, timestamp mapping and conservative metadata reuse. Require independent decoded picture, timing and metadata checks for any HDR10+ output claim. Keep the existing HDR10 and SDR paths.
- C. Deliver testable editing improvements with save/reopen, undo/redo and picture/audio checks. Record incomplete requirements from issue #9.
- D. Measure affected interactive workflows and retain every failed attempt. Use short runs to isolate individual defects. Keep private sources, saved projects and local diagnostic logs outside Git.

Each checkpoint is published separately as it becomes reviewable. Production changes require a freshly built and verified development installer.
