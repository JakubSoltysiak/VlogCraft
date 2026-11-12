# Windows verification

## 3.1 baseline, 12 November 2026

The 3.1 x64 MSI installed on Windows 11 Pro build 26300 with an AMD Ryzen AI 9 HX 370 and Radeon 890M. The Start menu and optional desktop shortcut targeted the installed executable. An earlier private build was uninstalled and its executable and shortcut disappeared. The final 3.1 MSI SHA-256 was C195327F9344DFF74A2AE7324B13BE8003D5C7430887C2B702678686DE00F880.

The 11-test offline regression suite passed in 26.044 seconds. It covered NTFS sparse ranges and chunk offsets, HTTP ingestion, multitrack audio/video/title export, HEVC MOV, monochrome grading, silence on a muted track, approval/undo, missing media and relinking, crash-style recovery, injected disk-full failure, optical-flow tracking, decoded stabilization and 104 tracks with 1,500 clips.

The installed desktop test supplied a native WebView2 drop payload for a fully allocated 4,977,125,566-byte synthetic MOV. It linked the original without copying it, sought to 4.6 seconds in a proxy, split the timeline, exercised undo/redo and exported from packet offset 4,578,951,204. The H.264 export contained 24 frames at 3840×2160, 60/1, and 0.400 seconds of AAC. The first decoded frame differed from the corresponding source frame by a mean 0.891 RGB levels at 96×54. The installed app also applied/undid motion and a multitrack approval, reloaded the project and closed normally.

A single installed run measured 1.047 s from drop to clip insertion, 4.344 s through proxy readiness, 0.781 s for a seek check including automation polling and 1.719 s for the 24-frame export. The process tree's peak summed working set was 2,075.5 MiB, sampled CPU time 21.48 s and process I/O 5,045.9 MiB read / 12.2 MiB written. These are whole-workflow measurements on a short synthetic source. GPU utilization, physical disk I/O and sustained real-time playback were unmeasured. Three control-image comparisons matched the reference, with the inspector visible at two viewport widths.

The encoder smoke matrix exported and decoded H.264, HEVC and AV1 on both CPU and AMD AMF at 640×360/60. NVENC and Quick Sync could not be qualified on this hardware. No paid endpoint was invoked and no camera footage was supplied.
