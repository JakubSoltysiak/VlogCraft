# VlogCraft Studio 3 — Kenya Private Edition

A private, non-destructive, **local-first multitrack video editor** built for long 4K travel footage. It uses a polished browser-based editing UI and FFmpeg for offline rendering. It is a standalone prototype, **not a modified or redistributed Adobe Premiere or ArtCraft executable**.

## Getting started — Windows 11

1. Extract the ZIP somewhere with enough free disk space (ideally not a small system drive).
2. Run `INSTALL_WINDOWS_DEPS.cmd` once. This installs **Python 3.12 and FFmpeg** using Windows Package Manager (`winget`). These programs are free. If already installed, skip this step. Close and reopen terminals after installation.
3. Double-click `START_WINDOWS.cmd`. A local URL opens automatically in your browser. Keep the command window open while editing; close it to stop the app.
4. Use **LINK FILES** to browse and attach big files directly without making extra copies, or **drag files from File Explorer onto the window** to copy them into your local project in **8 MiB chunks**. This includes clips larger than 4.5 GB (provided you have free disk space). Drag items from the Media Library onto any compatible video/audio timeline track.
5. Edit, then click **EXPORT FILM**. Choose your MP4 filename using the native Windows Save dialog.

No Python packages, browser extensions, subscriptions, online services or API keys are required for basic editing.

## What is implemented

- **Multitrack editing:** create additional video and audio tracks; place, move and overlap clips; use picture-in-picture, overlapping footage, titles and soundtracks.
- **Large-file import:** no 512 MB / 2 GB / 4 GB application-level file limit. Video files are streamed from disk using byte ranges and do not load entirely into RAM. Browser drag/drop copies files to `workspace/media/` in 8 MiB sequential chunks. The local application never sends original clips to a cloud service.
- **Non-destructive editing:** drag, move, trim clip edges, split with **S**, duplicate, delete, undo/redo, source-in/out, zoom/scrub, keyboard frame stepping, magnetic snapping, and clip-level locking.
- **Video composition:** independent video layers, transforms (X/Y, zoom), overlay opacity, fit/fill, warm/cool/vivid/cinematic/monochrome grades, fade-ins and fade-outs, and text/title graphics.
- **Audio:** multiple overlapping audio tracks, original-camera audio, source volume, track mute, per-clip volume and fades, and AAC mixing.
- **Preview proxies:** manually generate a light 720p H.264 proxy for large HEVC/4K/HDR files using **CREATE 720p PROXY** in the selected clip inspector. The source file is used for export.
- **Output:** H.264/AAC MP4, 720p/1080p/1440p/2160p, 24/25/30/60 FPS, selectable quality/preset. Clips are composed in bounded-size render segments so many sources are not decoded simultaneously; the render runs in the background and can be cancelled.
- **HDR input:** FFmpeg detects tagged PQ/HLG input and uses an SDR BT.709 tone-mapping pipeline on export. HDR10+ dynamic metadata is not preserved; the result is SDR.
- **Project persistence:** project stored automatically as `workspace/project.json`. Source paths stay linked. Missing or moved originals must be relinked at their original path or reimported.
- **AI Director:** make a local 720p review MP4 or sampled frame ZIP for upload to *this ChatGPT conversation*; optional **OpenAI API** review explicitly sends up to eight reduced JPEGs + timeline information. Your API key is not stored. Only applied plans that have been explicitly previewed and approved modify V1; a dedicated AI undo is included. API access is billed separately from ChatGPT subscriptions.

## Importing very large videos: important distinction

**LINK FILES:** Native Windows file dialog. No copy; no application-managed size limit. Original file must stay at the same path. Recommended when footage lives on a fast SSD.

**DRAG & DROP from File Explorer:** Browser security prevents reading your real disk path. Instead, VlogCraft copies the original into `workspace/media/` in small blocks and uses the copy. A 4.5 GB file therefore requires approximately 4.5 GB of *additional local disk space*. Transfer progress and Cancel are shown. An interrupted transfer is removed when cancelled. The program does **not** read the entire file at once.

Both methods allow all supported formats. Format support depends on FFmpeg, and some camera profiles may require proxy creation for smooth browser playback.

## Keyboard shortcuts

| Shortcut | Action |
|---|---|
| Space | Play/pause preview |
| S | Split selected clip at playhead |
| Ctrl+Z / Ctrl+Y | Undo/redo timeline editing |
| Ctrl+D | Duplicate selected clip |
| Delete | Remove selected clip, preserving the original |
| Ctrl+S | Save project now |
| Left/Right arrows | Step one frame |

## Technical limitations — important

This is a **functional independent early version**, not equivalent to all of Premiere Pro's production features. It **does not yet** include nested sequences, adjustment layers, mask tracking, optical flow, stabilization, Adobe project import, motion graphics, keyframe interpolation, multicamera editing, professional audio meters, color scopes/LUT workflows, hardware-accelerated encoding, frame-accurate multiclip browser preview, ProRes export, or 10-bit HDR preservation.

Preview playback uses HTML media elements; some 10-bit HEVC/HDR sources are unsupported by your browser until a 720p proxy is generated. Preview synchronisation is best-effort, not a professional real-time playback engine. Filters and fonts may render differently in preview and final FFmpeg output. Long/hard 4K/60 timelines can be CPU- and disk-intensive. **Save and export a short test before assembling your complete vlog.**

Large-file logic has been tested using **sparse files and HTTP byte ranges above 4 GiB**, not with your actual >4.5 GB camera footage or a full-length Windows render. Short multitrack sound/video/title rendering and automated UI interactions were tested in a Linux container. Windows installation and full real-world editing remain unverified.

Your existing VlogCraft 2.0 project is not overwritten. This edition creates its own `workspace` folder, and does not alter ArtCraft settings.

## Privacy and backups

The local server binds to `127.0.0.1` on an available random port. Local imported footage and project data are never uploaded to an external service **unless you explicitly use OpenAI API analysis** (sampled still frames, not originals), or manually upload a review file into ChatGPT. Back up the `workspace` directory and your linked original footage. Review packs contain sample frames and filenames, not absolute source paths.

## Tests and troubleshooting

Run `python -m unittest discover -s tests -v` in the project folder with FFmpeg installed. Tests cover export of layered video/audio/title scenes, state validation and large-file range/64-bit offset behavior.

If a large MP4 is black in preview, select the clip in the timeline → **CREATE 720p PROXY**. If FFmpeg reports a decoder/codec error, check the source with `ffprobe -hide_banner "path-to-your-file.mp4"`. If export fails, open Export again to read the error message. Ensure enough free space for temporary segments on the destination drive. Never overwrite your original footage.
