# Initial public-source audit

12 November 2026, before the first push to JakubSoltysiak/VlogCraft.

- Both the GitHub connector and Git Credential Manager authentication resolved to JakubSoltysiak. The remote repository was public and empty, with main as its configured primary branch.
- The initial history contained 11 commits and 154 distinct file-content blobs across all branches and tags. Every reachable blob was inspected for common provider credentials, private keys, credential-bearing URLs, secret assignments and absolute personal paths.
- No credential-pattern or personal-path matches were found. One email-pattern match was a NumPy matrix expression. Commit author metadata uses the requested project email or the earlier local-only identity.
- The largest historical blob was a 238,144-byte demonstration PNG. All eight binary versions were demonstration screenshots or tiny control-image references. Those images were visually reviewed. No private footage, audio recording, editing project, installer, tool archive or virtual environment was tracked.
- The three archived application screenshots show mock/demo interface content. Source archive provenance is retained. Third-party code and assets have not been relicensed.
- The ignore file now excludes environments, credentials, editing projects and backups, project data directories, media, caches, generated builds, installers and tool archives.
- THIRD_PARTY.md records dependency roles and license provenance. Source publication excludes bundled dependencies and generated installers. Binary release redistribution requires a separate review of the exact builds and corresponding-source obligations.
- Existing commits and tags, including ddb8b55 and studio-3.3-verified, are preserved without rewriting. Future commits use JakubSoltysiak and 255693@edu.p.lodz.pl.

## 3.4.5 architecture investigation follow-up — 13 November 2026

The account was reverified as JakubSoltysiak. A dedicated branch and stacked draft PR #2 preserve PR #1, main and historical tags. The owner's newer canonical main/TODO changes were merged into the working branch without replacing them.

New published material consists of source experiments/measurement scripts, generated-fixture numeric JSON and reports. Curated records exclude personal paths/process IDs, footage, frames, projects, SDKs and tool/installer binaries. Existing control references were regenerated from the preserved 3.4.4 baseline using explicit DPR1/sRGB capture, visually inspected and compared with 3.4.5. No camera folder was supplied and no private media was uploaded.

The reachable-history audit is repeated after the final commit before push. Full logs remain locally under build/qa; final remote refs and a fresh mirror are verified separately. Source publication grants no new project license and no approval for bundled binary redistribution.

Pattern scanning and visual review establish the checks performed. They do not prove the absence of every possible secret or establish ownership of third-party material. The detailed machine-readable scan remains in the ignored local build/qa directory.
