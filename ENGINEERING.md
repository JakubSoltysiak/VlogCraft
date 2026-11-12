# Architecture audit and implementation order

The 3.0 archive is preserved at the Git tag studio-3.0-original. Its server owns a single global dictionary, reads a broken project as a new empty project and shares jobs and caches between requests. Uploads already stream through bounded buffers and HTTP Range uses Python integers. Browser drops create a second copy. A nominal 50 TiB cap, track and clip ceilings and a four-hour limit are separate application restrictions.

The HTML editor supports layered browser playback, independent audio, trim, split, local undo, titles and grades. Its timing model stores decimal seconds. Snapping includes the candidate itself in the minimum-distance comparison. The monitor uses independent HTML media clocks with periodic correction and CSS grading. It cannot serve as the reference compositor. The timeline rebuilds all clips on selection and playback scans every track. The interface hides the inspector at narrow widths.

FFmpeg already probes original sources, creates proxies and composites overlapping tracks. Each cut starts a new encode and AAC priming can accumulate across joins. The baseline fails both export tests with FFmpeg 9, which removed filter_complex_script. A segment render is practical for offline delivery but has no continuous audio clock for interactive preview. MLT's producer/playlist/tractor/consumer architecture is a candidate for shared playback and export. Adopting it requires testing Windows codec packaging, timestamp mapping and effect parity. OpenCV is suitable for feature analysis in background workers, with results stored in the project and rendered separately.

Keep the existing 3.0 UI, import endpoints, compatible project documents and the optional AI bridge while building the desktop host. Use WebView2 for the editing surface and native Windows drops. Keep FFmpeg and FFprobe in separate processes. The optional online bridge remains opt-in. Core regression uses only local fixtures.

## Delivery order

1. Repair and measure render timing. Validate a real, allocated large source and 4K60 output.
2. Add durable saves with recoverable revisions and failure tests. Expose relinking and versioned project operations.
3. Wrap the editor in a Windows desktop host. Link Explorer drops to originals, keep browser chunk upload as a fallback, automate proxies and expose source/proxy selection.
4. Build a private per-user installer and test installation, desktop launch and removal in an isolated test data directory.
5. Advance frame-based edits, timeline controls, shared preview/effect evaluation and regression coverage. Qualify larger changes with the feature matrix before release.
