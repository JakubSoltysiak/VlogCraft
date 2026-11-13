# Optional architecture lab

These programs are opt-in local measurements. In 3.4.6 a separate native player is optionally integrated into the editor; benchmark programs and MLT remain isolated. They operate on generated fixtures by default. Do not point them at private camera media for publication or upload their output blindly. Raw local logs may contain paths; public records are curated under docs/benchmarks.

For 3.4.6, run benchmarks/native_precision.py RESULTS, tests/native_windows.py EXECUTABLE GENERATED_MEDIA RESULTS, and benchmarks/native_playback.py EXECUTABLE GENERATED_MEDIA RESULTS --seconds 125 after building the runtime. These use generated media. benchmarks/camera_native.py PRIVATE_MANIFEST PRIVATE_RESULTS is strictly local; its raw plans, captures and logs must remain ignored. tools/audit_private_media.py PRIVATE_MANIFEST --verify-hashes checks integrity without disclosing names/hashes. See [current scope](../docs/NATIVE_PLAYBACK_3_4_6.md).

Use the build virtualenv's Python 3.11 and FFmpeg/FFprobe 9.0.2 on PATH. Native/MLT tests require Windows x64; GPU runs need a supported local adapter. Install packaging/requirements.txt first. Run from the repository root:

~~~powershell
python benchmarks/generate_media.py build/qa/architecture/media
python tools/setup_architecture_lab.py --build-native
python benchmarks/compare_engines.py build/qa/architecture/media build/qa/architecture/comparison-current
python benchmarks/filter_profile.py build/qa/architecture/media/h264-4k60-0.mp4 build/qa/architecture/filters
python benchmarks/engine_profile.py build/qa/architecture/export build/qa/architecture/media/h264-4k60-0.mp4 --seconds 3 --width 3840 --repeat 3 --gpu
python benchmarks/opaque_ab.py build/qa/benchmark-media/4k60.mp4 build/qa/architecture/opaque-ab
python benchmarks/drain_stress.py --repeat 100
python benchmarks/cache_profile.py --help
python benchmarks/service_profile.py build/qa/architecture/media/hevc10-4k5994.mp4 build/qa/field-test.mov build/qa/architecture/services
python benchmarks/ui_profile.py .venv/Scripts/python.exe build/qa/architecture/distinct-media build/qa/architecture/ui
python benchmarks/distinct_playback.py .venv/Scripts/python.exe build/qa/architecture/distinct-media build/qa/architecture/playback --seconds 660 --until-end
python benchmarks/long_render.py build/qa/architecture/distinct-media build/qa/architecture/long-render
python benchmarks/program_seek.py .venv/Scripts/python.exe build/qa/architecture/media build/qa/architecture/program-seek
python benchmarks/precision_audio.py build/qa/architecture/precision-audio
python experiments/ffmpeg_raw.py build/qa/architecture/raw build/qa/architecture/media/h264-4k60-0.mp4 build/qa/architecture/media/h264-4k60-1.mp4 build/qa/architecture/media/h264-4k60-2.mp4 --capture
python experiments/mlt/direct.py build/tools/architecture/shotcut/Shotcut build/qa/architecture/mlt build/qa/architecture/media/h264-4k60-0.mp4 --capture
python experiments/native_d3d11/host.py build/qa/architecture/host build/qa/architecture/media/h264-4k60-0.mp4
~~~

The generator refuses to overwrite existing files. It specifies distinct hue/audio content, 4K60 H.264 GOP60/B3 and 4K59.94 HEVC10. Different FFmpeg/builds can produce different bytes; consult input SHA/metadata in saved profiles. corpus.py creates 32 independently allocated 720p60 two-second files for the 1,500-clip UI/transport tests. Those clips are not 1,500 independent recordings.

Optional large fixtures:

~~~powershell
python benchmarks/generate_media.py build/qa/architecture/large-media --large-pairs
~~~

This allocates approximately 12 GB of six-second raw moving video with different content/audio, two independent files over 5 GiB. The driver/workflow report is distinct from physical Explorer gesture qualification. Use an empty output directory and sufficient free space. Originals and existing fixtures are never overwritten.

Tool setup verifies pinned downloaded archive SHA-256 and writes only ignored build/tools/architecture. It fetches portable FFmpeg SDK, Zig and Shotcut; production packaging does not depend on them. The SDK's DLL directory is inserted only in native child environments. No new engine binaries are added to Git or uploaded by CI.

Scripts ending in _profile measure separate workloads and cannot be combined as additive costs. Do not run concurrent benchmarks/builds when comparing throughput. Windows sessions create their own project and close only their owned process family. First-frame, CPU submission, completed compositor, browser callback, DXGI presentation and physical scanout are different metrics.

Read docs/ENGINE_BENCHMARKS.md for the exact observed workload, variation, failed pilots and unqualified scenarios. Native C++ is a video-only SDR prototype; it rejects unsupported HDR color tags and lacks VFR/sequence/audio/effect parity. MLT 7.41 CPU and high-precision/channel tests do not qualify its newer GPU module.
