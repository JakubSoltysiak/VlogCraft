# VlogCraft Studio 3.5.7 HDR editing

Starts at verified draft PR #13 head `8b7b394795f8a1b085ac789453851d3a43c3995b`. Issues [#9](https://github.com/JakubSoltysiak/VlogCraft/issues/9) and [#10](https://github.com/JakubSoltysiak/VlogCraft/issues/10) cover the original timeline, library and Windows export failures. The 3.5.6 installer and all prior verification evidence remain the comparison baseline.

Qualify managed stills and titles in the existing scene compositor first. Its working space, existing PQ conversion and frame-by-frame metadata authoring remain the reference. Then qualify boundary transitions and audio timing, storage ownership and installed workflows in separate checkpoints. Use deterministic generated pictures and audio and verify decoded output before considering the 60-second workload. Source recordings and the owner's project remain private and read-only.
