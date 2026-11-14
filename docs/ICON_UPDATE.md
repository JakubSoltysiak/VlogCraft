# Approved VlogCraft icon update
This visual asset checkpoint is separate from 3.4.8 performance work. No playback, export, timing, project or AI behavior changed.

The owner's approved 1536×1024 RGBA PNG is preserved byte-for-byte at assets/branding/vlogcraft-original.png for future color adjustment. Its source SHA-256 is 82c1661509be32262ec9356ac6801f761e0bb96bb74d7c1beea6f5aecccb2552. The image already contains transparency. No redraw, crop, recolor, sharpening or generated replacement was used.

tools/build_branding.py centers the entire original on a transparent square and performs premultiplied-alpha Lanczos scaling independently for 16,24,32,48,64,128,256 pixels. Every PNG is embedded unchanged as a corresponding ICO frame. The V and colored arcs remain distinguishable on light/dark backgrounds; the fine film-strip details naturally become tiny at 16 px.

The EXE, MSI Icon table, installed web icon, favicon, header/footer, desktop and Start menu shortcuts all use the same approved asset. WinForms explicitly loads it and shares VlogCraft.Studio AppUserModelID with the shortcuts. The installer uses a new icon resource name to avoid the old cached resource.

## Actual verification
- All seven ICO frames matched the PNG pixels exactly; original source hash matched.
- Built and installed EXE contained one icon group and exactly seven approved resource payloads; no old payload.
- MSI Icon table contained only the exact approved ICO.
- Both installed shortcut icon bytes matched; AppUserModelID and executable targets matched.
- Shell large/small icons and live taskbar/window icons matched the approved frames with **zero raster difference** at their actual sizes. Windows selected 48/24 px for the live handles on this desktop.
- Installed header/footer images loaded, favicon resolved, browser errors zero. Original-resolution art is kept in the source repository; only compact derived icons are installed.
- Installed tree contained exactly one ICO: vlogcraft-approved.ico; zero old icon files.
- Upgrade, uninstall and reinstall returned 0; project/settings byte inventory remained unchanged; complete frozen bundle/source checks passed.
- 61 Python regressions passed before the final static-route correction; installed checks then verified that correction. Full milestone regression and exact-head CI follow with the performance milestone.
- Icon-only MSI SHA-256: c971c764de8e67f64a8e47dc189eb49389ea6d6f124181b708899e4988fcccc0. The installed native binary remains the verified 3.4.7 engine, fe2f6ee15ca5f9e2460445072381cc834cd887d934ac14485fc00060346b818f.

The initial packaged browser check correctly caught missing static asset routes; the allowlist was fixed and the installer rebuilt/requalified. Early harness failures assumed one extraction result for two returned handles, used an incomplete 64-bit GDI declaration, and compared DPI-selected handles at arbitrary sizes. Those checks were corrected without changing artwork or relaxing pixel equality. [Microsoft's extraction API](https://learn.microsoft.com/en-us/windows/win32/api/shellapi/nf-shellapi-extracticonexw) defines the returned icon count.

No VlogCraft taskbar pin existed to migrate. The running taskbar icon handle is verified; arbitrary pre-existing pins on other Windows installations are not qualified. Historical installers remain in ignored local release storage. No private footage or media metadata is part of this asset checkpoint.
