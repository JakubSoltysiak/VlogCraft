# VlogCraft Studio 3.6.0 rendering performance

Phase 1 starts at draft PR #14 head `05f74e7095d77b46b80f0530ab9293871dbace14`. The [3.5.7 qualification](STUDIO_3_5_7_HDR_EDITING.md) and its installer are the frozen baseline. This stacked branch targets render throughput with the same scene, frame clock, image precision and delivery profiles. It leaves native preview optimization to a later checkpoint.

| Archived 3.5.7 workload | Result |
|---|---:|
| 360p60, 48 frames, spatial photo animation | 21.609 s |
| 720p60, 120 frames, spatial photo animation | Timed out at 190.109 s |
| UHD60, 24 frames, photo opacity animation | 144.765 s, including 4.656 s for HDR10+ authoring |

The matched runs use the same synthetic sources, codec and output geometry. Process timing and filter ablations are collected separately from end-to-end acceptance. Abbreviated graphs are diagnostic workloads. Full verification covers decoded video and PCM, picture count, timestamps and HDR10+ metadata.

Adobe documents GPU acceleration for effects, resize and color conversion, and describes hardware decoding and encoding separately. These are comparisons to measure on the same input, output and effects. The workstation currently has no local Premiere Pro installation for an equivalent trace. [Mercury Playback Engine](https://helpx.adobe.com/premiere/desktop/get-started/technical-requirements/enable-mercury-playback-engine-gpu-accelerated-renderer.html) · [Hardware encoding and decoding](https://helpx.adobe.com/in/premiere/desktop/get-started/technical-requirements/hardware-accelerated-decoding-and-encoding.html)
