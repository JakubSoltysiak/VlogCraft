# Build, test and contribute

Use Python 3.11 x64 and Node 22 or newer. Install packaging/requirements.txt in a local virtual environment and put FFmpeg/FFprobe on PATH. The Windows host uses WebView2. FFmpeg builds with the required codecs, drawtext, zscale, tonemap and LUT filters are needed for the complete suite.

Run these commands from the repository root.

~~~powershell
python -m pip install -r packaging/requirements.txt
python -m pip check
python tools/audit_repository.py
python -m unittest discover -s tests -p "test_*.py" -v
node --test tests/timeline_commands.test.js
~~~

Start the Windows application with python desktop.py --project <absolute-project-path>. The tests generate their media in temporary directories. Large-media and interactive performance tests are separate scripts in tests. Review VERIFICATION.md for measured acceptance scope.

For MSI packaging, install WiX 3.14.1 and run python packaging/build_windows.py --wix <directory-containing-candle-and-light>. The build expects FFmpeg's LICENSE in the parent of its bin directory. Generated build, dist, release, projects and media are ignored.

Create feature branches and pull requests for substantial work. Keep studio-3.3-verified intact. Preserve project compatibility, original media, linked editing, undo/recovery and explicit AI approval. Run regression after engine changes and record measured results. Include remaining gaps in FEATURES.md.

Windows Actions runs history checks, dependency compatibility, syntax checks, regression, application packaging and MSI lifecycle validation. It uses generated short media. Hosted CI does not qualify physical desktop dragging, real GPU drivers, high-DPI behavior or sustained native playback.

The source repository has no newly granted project redistribution license. Follow THIRD_PARTY.md and review exact bundled components before distributing installers. CI does not automatically publish stable releases.
