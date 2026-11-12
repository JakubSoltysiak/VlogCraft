# VlogCraft Studio 3.1 for Windows

Private development build for Windows 11 x64. Double-click **release/VlogCraft-Studio-3.1-x64.msi**. The installer adds **VlogCraft Studio** to the Start menu. The feature-selection screen includes an optional desktop shortcut. The local FFmpeg, FFprobe, Python runtime and OpenCV components are bundled. The window uses the Microsoft Edge WebView2 runtime supplied on the tested Windows 11 system.

## Edit a film

1. Open VlogCraft Studio. Drag files from Explorer into the editor to link them and append them to the timeline. **Link files** opens the Windows file picker. The small **+** in the library explicitly copies selected files. Browser-only drops also use local chunked copying.
2. **Source** opens a library item for preview and source in/out marking. Choose **Append to timeline** for the marked range. Drag library items to other tracks. Click a clip to edit it in the inspector. The timeline ruler seeks, arrow keys step through sequence frames, **S** splits and **Shift+Delete** closes the gap on the selected track.
3. The **⋯** in a track header opens its name, color, height, order, gain and solo settings. Drag the divider above the timeline to resize the edit surface.
4. **Automatic proxies** schedules a 720p proxy on desktop import for 4K, large or less browser-compatible video. **Original media** switches the monitor back to the source. Browser support for some original codecs requires a proxy. The library footer shows progress and cancellation. The exporter reads original media paths.
5. Select a clip and open **Keyframe animation** to set position or gain keys at the playhead. The graph supports click-to-seek, key values and interpolation editing, custom Bézier handle coordinates and curve copy/paste. Source-time keys follow media trims and speed changes. **Track / stabilize** analyzes the selected source range. For tracking, select a textured detail and an overlapping target layer. **Apply keyframes** writes an undoable edit. Applying motion replaces the target's position curves.
6. **Export film** writes SDR MP4 with AAC audio. Choose a preset or custom even dimensions, frame rate, encoder and optional bitrate. The encoder menu tests actual local devices. A zero bitrate uses CPU quality mode or a 35 Mb/s hardware target. Existing projects default to CPU H.264. Rendering needs scratch space beside the destination. Review video uses an independent 720p H.264 preset.

## Projects and privacy

The first project is stored under `%LOCALAPPDATA%\VlogCraft Studio\Projects`. Use **Project → New project**, **Open project** or **Save as** to work in separate project windows. Save as creates a linked copy of the timeline. Keep each project with its `.data` directory and referenced media. Autosave retains a validated previous revision in a sibling `.bak` file. When both revisions are unreadable, opening reports the failure and preserves the files. Offline media appears in the library with **Relink**. A replacement must cover all used source out-points.

The AI Director can export a local review MP4 or a ZIP with sampled frames, timeline metadata and editing instructions. Uploads in the conversation workflow are manual. For track-addressed JSON use the schema and IDs in the review ZIP. Review the proposed edits, approve them, and use **Undo last AI apply** to revert. The optional API action sends sampled images and metadata when explicitly invoked and may incur charges. No credential is needed for offline editing or the test suite.

## Engineering and verification

See **ENGINEERING.md** for architecture decisions, **FEATURES.md** for implementation status and sequenced remaining work, and **VERIFICATION.md** for measured results. The tag `studio-3.0-original` preserves the extracted source. README_EN.md, README_PL.md and QA_SUMMARY.txt describe the original archive.

For a maintainer build, use Python 3.11 x64, the pinned modules in `packaging/requirements.txt`, FFmpeg/FFprobe 9 on PATH and WiX 3.14.1. The build script expects the FFmpeg package's LICENSE one directory above its bin directory. Run `python packaging/build_windows.py --wix <WiX-binaries-directory>` in the repository. The generated MSI is in `release` and the self-contained application directory is in `dist/VlogCraftStudio`. Keep all files in that directory together.
