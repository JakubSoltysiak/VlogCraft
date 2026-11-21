# VlogCraft Studio 3.5.5

PR #11 head fb48c7d is the starting point. The clean local tree and remote head agree. The existing 3.5.4 MSI SHA-256 matches its delivery receipt. Issues #9 and #10 and the stacked HDR drafts define the earlier export fixes and the remaining editing scope.

The first checkpoint will compare encoded HEVC HDR10+ payloads against the cached FFprobe frame records at original presentation timestamps. Classify the camera observations separately from decoder support and product reuse policy. Validate any output against independent decode and the source picture association. Preserve the existing output paths and require explicit selection for any HDR10+ mode.

Next qualify a coherent editing subset through project persistence, preview and export. Keep earlier failures and private media evidence local. Publish each development checkpoint on its own commit. Build a fresh development MSI after production changes and record actual verification scope.

## A. Encoded metadata and preservation

An independent reader used MP4 sample offsets and presentation timestamps from FFprobe, then parsed the original HEVC SEI payload bytes. For each of 7,619 samples it compared exact integers against the prior decoded SQLite metadata, including repeated histogram entries, luminance and normalized curve fields. Camera 1 had 4,674 invalid blocks and Camera 2 had 2,945. All invalid blocks had a nonzero value in the reserved 5% slot. There were zero valid, unsupported or implementation-limited blocks and zero scaling or field differences in this corpus. Raw per-frame observations remain private. The test reused the previous indexes, and took 1.216s and 0.757s. Version 1 allows at most nine Bézier anchors. The reuse gate also handles the special 10% slot separately from the histogram.

[ST 2094-40:2020](https://pub.smpte.org/pub/st2094-40/st2094-40-2020.pdf) §8.5.4 defines the reserved pair. The finding is specific to that constraint and does not assert that other decoders or displays fail. The generated conforming-field fixture is for transport verification, not calibration or a metadata-authoring algorithm.

**Preserve original HDR10+** is an explicit export choice for a single complete unedited original with matching constant sequence cadence and dimensions, square-pixel limited PQ Rec.2020 HEVC Main10 and optional source AAC. The option copies the original compressed pictures and audio, validates packet data and timestamps, and confirms output stream and color configuration before atomic publication. Tests independently decoded and compared every picture and audio frame and inspected the metadata values by frame. The verified subset rejects orientation transforms, variable cadence, source trims, sequence effects, reordering, audio edits and unsuitable metadata. The standard renderer remains an explicit choice for SDR and supported HDR10. No automatic downgrade or edited HDR10+ authoring is exposed.

[x265](https://x265.readthedocs.io/en/latest/cli.html) supports supplied dynamic metadata, while [hdr10plus_tool](https://github.com/quietvoid/hdr10plus_tool) can inspect and insert metadata. Transport does not establish that newly authored metadata describes the edited pixels. The [AMD AMF HEVC API](https://github.com/GPUOpen-LibrariesAndSDKs/AMF/blob/master/amf/doc/AMF_Video_Encode_HEVC_API.md) documents static HDR parameters; arbitrary ST 2094-40 injection was not qualified on this workstation. Full authoring would need validated analysis of final pictures, cadence/metadata alignment, device checks and redistribution review.

## B. Batch motion and keyframes

Motion presets generate editable source-time keys for selected clips, the selected track or eligible top-level clips throughout the project. Fade, zoom, pan, slide and Ken Burns choices can replace generated motion, be cleared, or be applied by default to newly placed clips. Duration, direction and smooth or linear easing are configurable. Locked clips and conflicts with manual curves are skipped. Managed HDR allows opacity presets on video. Existing clip fit and framing settings are preserved.

The keyframe inspector lists keys, shows when the curve has too few keys to animate, and can add, update, move and remove numeric keys. It retains graph markers, Bézier and conditional copy/paste. The desktop source test applied a fade to both photos, verified undo/redo, assigned default zoom, moved a key numerically and reopened the saved sequence. Decoded output changed from RGB [14,18,26] at the first frame to [235,35,23] after the fade. The first local decoder invocation used an invalid leading-decimal seek argument and is retained as a failed harness attempt. Three focused JavaScript tests cover timing and manual curve preservation.

Automatic transitions across clip boundaries, linked audio crossfades and transitions inside nested sequences remain open. The current opacity preset is motion within a clip.

## C. Library, camera audio, storage and icon

The Media Library now offers grid and list views, a thumbnail-width control, panel sizing where the window has room, vertical scrolling and multi-selection. Remove from Project hides unused items. A geometry-aware reference check rejects clips referenced on any track or in a nested sequence. The original inventory record is retained for undo and the Removed view. Restoring or undoing makes the source available in the active library again. Source files are never deleted by this command.

Clip Inspector identifies embedded versus separated camera audio and exposes the existing independent, linked waveform track operation. The local desktop source test verified 33 assets, list scrolling and panel sizing, rejected removal of a used source, exercised removal/undo/redo and thumbnail regeneration, reopened the project, and showed byte-identical decoded 38,400-byte stereo PCM before and after separation. The test also verified all original fixture hashes.

Project Storage reports linked source and known project/cache sizes. Its confirmation-gated cleanup is limited to app-owned thumbnails for removed library entries, excluding any active cache or linked source path. Restore can regenerate those thumbnails. General proxy/preview deletion and abandoned export recovery remain open.

The approved original artwork is unchanged. The ICO now crops outside the alpha-4 artwork bounds with a 3.5% border, then uses premultiplied-alpha scaling for all seven resolutions from 16 to 256 px. Only near-invisible fringe falls outside the crop. The 16 and 64 px renders were visually checked. Installed checks matched the MSI and all seven executable resources, Start and desktop shortcuts, and the native taskbar and title-bar handles. No previous icon files were found in the installed tree.

## D. Windows qualification and performance

The MSI was built from production checkpoint `b989e344dfb0ce92d58d1cb075529fef72d5be3a`. SHA-256 is `fad30d2d2b5cad81afedb52ed0ffab66e00c4938f9ce2686b1276d4abe6b7901`. Upgrade, uninstall and reinstall exited successfully and retained seven protected project/settings files. The installed application, web assets, icon and optional native runtime matched the bundle. The MSI is a local development build.

- **Installed HDR10+.** The offline desktop Export workflow produced all 12 changing dynamic-metadata frames and exact decoded picture and audio from the generated conforming-field fixture. FFprobe inspected frame association and Main10/PQ/Rec.2020 signaling. The source file and project output settings stayed unchanged. The private-camera recheck verified three original hashes with zero changes and zero worktree/history matches.
- **Installed SDR and HDR10.** A two-photo fade produced live opacity endpoints 0 and 1, with rendered reference and decoded SDR export endpoints within two RGB code values per channel. The default and numeric key survived reopen. On the 12-frame HDR10 test, the tone-mapped reference compared to independently decoded delivery at 0.407 mean absolute 8-bit RGB code values. Renderer and browser fault injection each restored the draft, source metadata, paused position and exact 80-state history. The prior verified UHD60 AMD AMF path remains covered by the parent milestone's fixture.
- **Installed library and audio.** The 33-asset test exercised grid/list, resizing, scroll, used-source removal protection, undo/redo and thumbnail regeneration. Separation into a linked track and reopen preserved exactly 38,400 decoded stereo PCM bytes. All fixture sources stayed byte-identical.
- **Retained attempts.** The initial source motion test passed a leading-decimal seek string FFmpeg rejected. The first installed test read the server reference before the preset save completed and saw an unfaded frame. Persisting the edits before requesting server-rendered frames reproduced the normal Reference monitor path and passed on the same MSI. Early Windows run [56](https://github.com/JakubSoltysiak/VlogCraft/actions/runs/44911200507) reported frame 17 of the existing continuous-preview comparison at 7.941 RGB MAE against a limit of 7 in the offline pass. The hosted production-checkpoint regression and local final offline suite passed the unchanged test. This single intermittent failure has no demonstrated root cause.
- **Local regression.** 151 loopback-only Python tests passed in 55.004s. The supervised local desktop/build cases left zero owned processes or new terminal windows at cleanup. Child cleanup was checked at each run boundary.

### Paired Live Layers diagnostic

One visible pair used the same generated five-second original, one H.264 source layer at 3840 × 2160 and 60 FPS, with no proxy or source audio. Both ran at 175% display scaling with a 380 × 214 CSS px preview and 666 × 374 physical px. JavaScript observed browser video callbacks, actual source presentation times, and browser-reported drops. Working set was sampled across owned WebView processes. No native workers were active.

| Measurement | Frozen 3.5.4 | Candidate 3.5.5 |
|---|---:|---:|
| Seek median, six correct target frames | 553.5 ms | 467.3 ms |
| First measured seek | 412.5 ms | 267.9 ms |
| Worst seek and timeouts | 870.5 ms / 0 | 838.7 ms / 0 |
| Browser dropped frames / callbacks | 2 / 230 | 0 / 229 |
| Longest callback gap | 41.7 ms | 41.9 ms |
| WebView working set before / active / after | 635 / 1,349 / 1,353 MiB | 682 / 1,375 / 1,206 MiB |

The candidate still took up to about 839 ms to show the requested frame. The single short pair cannot establish a repeatable improvement, sustained UHD composition, first-play-frame latency, acoustic sync, a memory plateau or native GPU performance. The candidate had one FFmpeg process at the initial sample and zero during and after playback. Proxy contention, native UHD60 with audio, long-project work and hardware utilization remain open. [Raw sanitized measurements](benchmarks/studio-3.5.5-performance.json).

## Remaining release gates

HDR10+ regeneration requires generating and independently validating metadata against the actual edited pictures. Trimming, speed changes, cadence conversion and other edits remain outside the copy-only delivery mode. There is no Samsung TV master or YouTube HDR preset, and no device playback or YouTube transcode evidence. Adjacent-clip transition handles, crossfades and batch boundary editing remain open. Current batch motion does not recurse into nested sequences. General proxy/preview and abandoned-export cleanup remain open. Keep the installer as a development build and preserve the open native performance and reliability gates before any stable release.
