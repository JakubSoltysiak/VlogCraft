# VlogCraft Studio 3.4 for Windows

> **[MASTER TO-DO LIST & PRODUCT ROADMAP](TODO.md)** — shared living backlog for the owner, Codex and ChatGPT. Check priorities and update it with each feature PR.

Windows 11 x64 development project. The local development installer is **release/VlogCraft-Studio-3.4-x64.msi**, currently version 3.4.6 (experimental native-playback development build). The installer adds VlogCraft Studio to the Start menu and offers a desktop shortcut. Python, FFmpeg, FFprobe and OpenCV are bundled. WebView2 is required and was present on the qualification machine. Source and preserved tags are on the public repository, with 3.4 development reviewed in pull request 1. [GitHub repository](https://github.com/JakubSoltysiak/VlogCraft), [development PR](https://github.com/JakubSoltysiak/VlogCraft/pull/1).

## Experimental native playback — 3.4.6

The **Native GPU · experimental** preview choice integrates original-media libav/D3D11 decoding, bounded float16 composition and a stereo PCM audio clock into the existing Windows editor. The production FFmpeg renderer remains available and the default is unchanged. Supported cuts, transforms and keys use the native path; unsupported effects switch the whole SDR program to the reference compositor. PQ display requires active Windows HDR and never silently tone-maps to SDR.

A 125-second, 1,500-clip, three-original4K/three-audio test completed with exact audio sample count and no underruns, but presented about **57.2 FPS at 540p**, still below 60 FPS. Three private camera recordings supplied additional PTS, precision, orientation and audio checks. Actual HDR display, full effect parity, hour-long/acoustic sync and real device-reset acceptance remain open. See the [3.4.6 integration report](docs/NATIVE_PLAYBACK_3_4_6.md), [verification](VERIFICATION.md) and [feature matrix](FEATURES.md). PRs #1 and #2 stay unmerged drafts; this milestone is [stacked draft PR #3](https://github.com/JakubSoltysiak/VlogCraft/pull/3), not a stable release.

## Architecture investigation — historical 3.4.5

The investigation preserves the editor and PR #1. The [architecture audit](docs/ARCHITECTURE_AUDIT.md), [measured comparisons](docs/ENGINE_BENCHMARKS.md), [decision](docs/ARCHITECTURE_DECISION.md) and [next implementation gates](docs/PERFORMANCE_ROADMAP.md) document the working FFmpeg, MLT and native D3D11 experiments. At that checkpoint native GPU composition was the preferred next slice; 3.4.6 now exposes a limited opt-in preview. Full effect/VFR/audio/HDR parity remains open.

3.4.5 adds a conservative opaque-picture render fastpath, range-dependent persistent preview caching with bounded pending work, and deterministic source-index child shutdown. The matched three-second 4K60 single-stream export improved from 7.326 to 6.101 seconds in the tested fixture; unrelated caption edits reuse unaffected preview ranges. See VERIFICATION.md for exact scope, failures and current package checks. [Reproduction scripts](benchmarks/README.md) use generated media; no private camera files or dependency binaries are published.

Final scoped qualification includes a complete ten-minute generated sequence (1,500 clips/32 distinct sources), decoded long low-resolution export with exact frame/sample counts, two independent >5 GiB native originals and Windows installer retention. Sustained playback averaged 51.76 callbacks/s and still misses 60 FPS. Current source and installed bytes match; detailed evidence and limits are in VERIFICATION.md. The earlier two development PRs remain unmerged drafts.

## Editing

- Drag files from Explorer into the editor to link their original paths. **Link files** opens the native picker. Multiple files are processed with progress and cancellation. The library **+** and browser-only drops create local copies through bounded chunks. There is no application file-size ceiling.
- Open a library item's **Source** monitor to mark a range. **Inspect frame**, **Previous frame**, **Next frame**, **I** and **O** use original presentation timestamps. The out-point excludes the following frame. Place a range using append, insert or overwrite.
- Choose exact sequence rates in project settings, including **24000/1001**, **30000/1001**, **60000/1001** and **120000/1001**, plus integer rates through 120 fps. Timecode uses a non-drop frame counter.
- Ctrl-click clips to select across tracks. **Edit…** provides rolling, slip, slide, selection movement, camera-audio separation and linking, and nesting. Linked timing edits move both partners. Expand a nested sequence to edit its child tracks. Track **⋯** controls naming, color, gain, solo, height and order.
- The inspector contains transforms, fades, directional entrance wipes, chroma key, an ellipse mask, curves, color wheels, SDR cube LUT import and audio controls. Keyframe animation supports position, scale, rotation, opacity, gain, mask radius and primary effect parameters. Motion analysis creates editable source-time keys for point tracking or translation/rotation stabilization.
- **Composited preview** buffers eight-second program ranges through the export compositor and plays one combined audio/video stream. It renders ahead, reuses matching source decoders, cancels obsolete work and limits complete cache files. The default is 540p. Preparation and cache misses can pause playback. Live layers remains the initial interactive mode.
- **Reference** renders a paused program frame with the export compositor. Paused scopes display that same frame. Interactive playback uses browser compositing, automatic 720p proxies, an audio master clock and bounded decoder reuse. Effects and audio processors have approximation differences during interactive playback.
- Audio channel strips provide gain, pan, low/high shelves, compression and a master peak meter. Peak normalization and dialogue-track-driven music ducking measure original audio and write editable gain changes. A 48 kHz, 16-bit stereo FLAC preview cache avoids reading an entire video container for each independent audio track.
- **Export film** renders original media to 8-bit SDR MP4 and stereo AAC. The dialog explicitly states PQ/HLG-to-SDR delivery; managed HDR and multichannel export remain unavailable. Select dimensions, exact frame rate, CPU encoder or an accelerator that passes a real local encode probe. Hardware failure automatically retries the corresponding software encoder. The compositor remains CPU-based.

Space toggles playback. Arrow keys step sequence frames. **S** splits. Ctrl+Z and Ctrl+Y undo and redo. Ctrl+D duplicates. Delete removes the selection and Shift+Delete closes its track gap. Ctrl+S saves.

## Projects and privacy

Projects default to %LOCALAPPDATA%\VlogCraft Studio\Projects. Project → New, Open and Save as open independent project windows. Original media stays linked. Keep the project, its .data folder and the referenced media together. Offline media can be relinked.

Schema 2 and 3 projects open in 3.4. Saving uses schema 4 with rational frame/tick coordinates. The first schema-4 save preserves the prior document in a permanent **.v3.bak** file. The ordinary **.bak** keeps the last valid revision for recovery. Older editor versions require the prior-format copy. A failed save reports an error and retains the published revision.

AI Director supports offline review MP4 and multitrack frame packs. Choose the current program frame or let the pack sample the sequence. Its manifest includes every track, nested child, lock, source bound, link and keyframe. Paste the proposal from the review into the editor, preview its exact changes and explicitly approve it. Undo and redo work for approved edits.

The existing optional API connection continues to use its legacy main-track analysis. Core editing and all release tests work offline without a credential. The API action requires the user's explicit invocation and may incur charges. Media sharing through a conversation remains manual.

## Release status and maintenance

Read **FEATURES.md** for implementation and qualification status, **VERIFICATION.md** for measured tests and release blockers, and **ENGINEERING.md** for architecture and continuation work. This remains a development release. Sustained full-quality multitrack playback, managed HDR and professional interchange need further engineering.

Git preserves studio-3.0-original, studio-3.1-verified, studio-3.2-source and studio-3.3-verified. See CONTRIBUTING.md for build/test commands, PUBLICATION_AUDIT.md for the publication review and THIRD_PARTY.md for dependency provenance. No new project redistribution license has been granted. The extracted README_EN.md, README_PL.md and QA_SUMMARY.txt describe the original archive.

Build with Python 3.11 x64, packaging/requirements.txt, FFmpeg/FFprobe 9 and WiX 3.14.1. Run python packaging/build_windows.py --wix <WiX-directory>. The MSI is in release and the self-contained application directory is dist/VlogCraftStudio. Keep its files together.

Automated qualification entry points are unittest discovery in tests, node --test tests/timeline_commands.test.js, tests/windows_workflow.py, tests/windows_release.py, tests/playback_benchmark.py, tests/encoding_benchmark.py and tests/encoder_smoke.py. Their generated media, logs and measurement JSON remain under build/qa.
