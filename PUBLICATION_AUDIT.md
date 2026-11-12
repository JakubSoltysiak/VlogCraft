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

Pattern scanning and visual review establish the checks performed. They do not prove the absence of every possible secret or establish ownership of third-party material. The detailed machine-readable scan remains in the ignored local build/qa directory.
