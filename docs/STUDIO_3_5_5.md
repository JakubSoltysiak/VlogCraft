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

The approved original artwork is unchanged. The ICO now crops outside the alpha-4 artwork bounds with a 3.5% border, then uses premultiplied-alpha scaling for all seven resolutions. Only near-invisible fringe falls outside the crop. The source/ICO pixel checks pass. Actual Windows installer and shell-resource verification follow on the combined 3.5.5 build.
