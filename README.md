# VlogCraft Studio 3.3 for Windows

Private Windows 11 x64 development release. Run **release/VlogCraft-Studio-3.3-x64.msi**. The installer adds VlogCraft Studio to the Start menu and offers a desktop shortcut. Python, FFmpeg, FFprobe and OpenCV are bundled. WebView2 is required and was present on the qualification machine.

## Editing

- Drag files from Explorer into the editor to link their original paths. **Link files** opens the native picker. Multiple files are processed with progress and cancellation. The library **+** and browser-only drops create local copies through bounded chunks. There is no application file-size ceiling.
- Open a library item's **Source** monitor to mark a range. **Inspect frame**, **Previous frame**, **Next frame**, **I** and **O** use original presentation timestamps. The out-point excludes the following frame. Place a range using append, insert or overwrite.
- Choose exact sequence rates in project settings, including **24000/1001**, **30000/1001** and **60000/1001**. Timecode uses a non-drop frame counter.
- Ctrl-click clips to select across tracks. **Edit…** provides rolling, slip, slide, selection movement, camera-audio separation and linking, and nesting. Linked timing edits move both partners. Expand a nested sequence to edit its child tracks. Track **⋯** controls naming, color, gain, solo, height and order.
- The inspector contains transforms, fades, directional entrance wipes, chroma key, an ellipse mask, curves, color wheels, SDR cube LUT import and audio controls. Keyframe animation supports position, scale, rotation, opacity, gain, mask radius and primary effect parameters. Motion analysis creates editable source-time keys for point tracking or translation/rotation stabilization.
- **Reference** renders a paused program frame with the export compositor. Paused scopes display that same frame. Interactive playback uses browser compositing, automatic 720p proxies, an audio master clock and bounded decoder reuse. Effects and audio processors have approximation differences during interactive playback.
- Audio channel strips provide gain, pan, low/high shelves, compression and a master peak meter. Peak normalization and dialogue-track-driven music ducking measure original audio and write editable gain changes. A lossless stereo preview cache avoids reading an entire video container for each independent audio track.
- **Export film** renders original media to SDR MP4 and AAC. Select dimensions, exact frame rate, CPU encoder or an accelerator that passes a real local encode probe. Hardware failure automatically retries the corresponding software encoder. The compositor remains CPU-based.

Space toggles playback. Arrow keys step sequence frames. **S** splits. Ctrl+Z and Ctrl+Y undo and redo. Ctrl+D duplicates. Delete removes the selection and Shift+Delete closes its track gap. Ctrl+S saves.

## Projects and privacy

Projects default to %LOCALAPPDATA%\VlogCraft Studio\Projects. Project → New, Open and Save as open independent project windows. Original media stays linked. Keep the project, its .data folder and the referenced media together. Offline media can be relinked.

Schema 2 and 3 projects open in 3.3. Saving uses schema 4 with rational frame/tick coordinates. The first schema-4 save preserves the prior document in a permanent **.v3.bak** file. The ordinary **.bak** keeps the last valid revision for recovery. Older editor versions require the prior-format copy. A failed save reports an error and retains the published revision.

AI Director supports offline review MP4 and multitrack frame packs. Choose the current program frame or let the pack sample the sequence. Its manifest includes every track, nested child, lock, source bound, link and keyframe. Paste the proposal from the review into the editor, preview its exact changes and explicitly approve it. Undo and redo work for approved edits.

The existing optional API connection continues to use its legacy main-track analysis. Core editing and all release tests work offline without a credential. The API action requires the user's explicit invocation and may incur charges. Media sharing through a conversation remains manual.

## Release status and maintenance

Read **FEATURES.md** for implementation and qualification status, **VERIFICATION.md** for measured tests and release blockers, and **ENGINEERING.md** for architecture and continuation work. This remains a development release. Sustained full-quality multitrack playback, managed HDR and professional interchange need further engineering.

Git preserves studio-3.0-original, studio-3.1-verified and studio-3.2-source. The extracted README_EN.md, README_PL.md and QA_SUMMARY.txt describe the original archive.

Build with Python 3.11 x64, packaging/requirements.txt, FFmpeg/FFprobe 9 and WiX 3.14.1. Run python packaging/build_windows.py --wix <WiX-directory>. The MSI is in release and the self-contained application directory is dist/VlogCraftStudio. Keep its files together.

Automated qualification entry points are unittest discovery in tests, node --test tests/timeline_commands.test.js, tests/windows_workflow.py, tests/windows_release.py, tests/playback_benchmark.py, tests/encoding_benchmark.py and tests/encoder_smoke.py. Their generated media, logs and measurement JSON remain under build/qa.
