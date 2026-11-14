# Sanitized 3.4.8 qualification evidence

These records contain selected numeric results and generated-source measurements. Private originals, identifiers, hashes, paths, metadata, images and raw logs stay local. See [the report](../../PERFORMANCE_CONSISTENCY_3_4_8.md) for conditions and limits.

baseline.json contains ten completed unchanged-engine runs plus the retained failed attempt. candidate.json contains all ten packaged trials. They share a condition/observer contract; comparison.json applies the permanent median/worst investigation gate. Candidate interval quantiles exclude initial paused preparation; unchanged baseline p99 is unavailable. Raw terminal-hold counter windows remain alongside active-window results. Across-run mean-interval variance is not per-frame variance.

full-endurance.json is the failed first attempt; endurance-retry.json is the completed replacement. qualification-steps.json preserves the original FULL failure and subsequent individual checks. camera-export.json follows a corrected full-range-format harness assertion; the existing output was reverified, not re-encoded. memory-controls.json contains two diagnostic arms with forced GC only after stopping, not qualification FPS.

Installer lifecycle and final bundle checks apply to the locally installed development MSI. Hosted Actions independently compiles/packages the exact pushed commit; GPU execution, physical synchronization, calibrated HDR and clean-machine readiness remain separate gates. No public binary release is created.
