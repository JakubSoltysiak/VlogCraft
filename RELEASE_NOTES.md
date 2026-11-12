# VlogCraft Studio 3.0 — Kenya Edition

**Major new editing engine** (compared with the prior single-track VlogCraft 2):

- Multiple independent video/audio tracks and layered FFmpeg composition.
- Drag-and-drop local file importer that streams arbitrary file sizes in 8 MiB chunks.
- Native no-copy source-linking as an alternative to the browser's copy-on-drop.
- 64-bit byte-range streaming so previews can seek into files above 4 GiB.
- Move/trim/split/duplicate, undo/redo, snapping, time ruler, locked/muted tracks.
- Picture-in-picture transforms, opacity, color presets, titles, independent audio gain, fades, speed.
- Manual 720p proxy generation, 4K 60 FPS export and HDR-tagged source tone mapping.
- Retained optional AI Director: local review/ChatGPT handoff and opt-in API with edit approval/undo.
- Redesigned custom dark professional editing UI.

**Validation performed:** Python compiler checks; JavaScript syntax check; tests of normal export with audio/title tracks; HDR-tagged source transcoding; 64-bit upload chunk offset and byte-range tests above 4 GiB; headless Chromium editing interactions (split, undo/redo, title splitting, drag).

**Not validated:** actual 4.5+ GB complete transfer, Windows build, complete long 4K/60 project, accurate browser preview for every codec, Premiere Pro feature parity.
