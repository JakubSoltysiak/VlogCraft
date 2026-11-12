# Third-party components and source provenance

The original VlogCraft 3.0 code and demonstration screenshots came from the user-supplied VlogCraft Studio archive. Subsequent commits preserve that history. No new redistribution license is granted by this document. A repository-level open-source license has not been selected. Publishing source does not relicense dependencies or third-party assets.

## Source repository

The tracked repository contains application source, build scripts, documentation and small demonstration/control screenshots. The archived screenshots show a mock timeline and application controls. It contains no camera footage, music recording, project document, virtual environment, FFmpeg executable or Windows installer. System font names in the stylesheet refer to fonts installed on the user's machine. Font binaries are not supplied in this repository. The build icon is drawn by the packaging script.

## Runtime and build components

| Component | Role | Upstream license information |
|---|---|---|
| Python | Desktop runtime | Python Software Foundation license and accompanying notices |
| FFmpeg / FFprobe | External media processes | Build-dependent LGPL/GPL terms. The local build enables GPL components including x264/x265. See the exact build configuration and its LICENSE before distribution. |
| pywebview | Desktop host | BSD-3-Clause |
| pythonnet | Windows .NET bridge | MIT |
| clr-loader | .NET loader | MIT |
| Pillow | Image operations | MIT-CMU |
| OpenCV Python headless | Motion analysis | Apache-2.0 for current OpenCV, plus package/bundled third-party notices |
| NumPy | Color/audio array operations | BSD-3-Clause and bundled notices |
| PyInstaller | Application packaging | GPL-2.0-or-later with the PyInstaller bootloader exception |
| WiX Toolset 3 | MSI build tool | Microsoft Reciprocal License |
| Microsoft Edge WebView2 | Installed Windows runtime | Microsoft's runtime terms |

The build script collects installed Python-package notices and the exact FFmpeg LICENSE into the application directory. It uses an externally installed WebView2 runtime.

Before distributing a bundled installer, review the exact dependency builds and provide all applicable notices, corresponding-source material and source offers required by those builds. A license file alone does not establish binary-redistribution compliance. GitHub source publication excludes generated installers and dependencies. Automated build verification does not constitute legal clearance to distribute its output.

Upstream sources are [Python licensing](https://docs.python.org/3/license.html), [FFmpeg legal information](https://ffmpeg.org/legal.html), [pywebview](https://github.com/r0x0r/pywebview), [pythonnet](https://github.com/pythonnet/pythonnet), [Pillow](https://github.com/python-pillow/Pillow), [OpenCV Python packaging](https://github.com/opencv/opencv-python), [NumPy](https://github.com/numpy/numpy), [PyInstaller licensing](https://pyinstaller.org/en/stable/license.html) and [WiX 3](https://github.com/wixtoolset/wix3).
