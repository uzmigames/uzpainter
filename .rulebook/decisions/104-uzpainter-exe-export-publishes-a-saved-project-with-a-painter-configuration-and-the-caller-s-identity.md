# 104. `UzPainter.exe export` publishes a saved project with a Painter configuration and the caller's identity

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase1.18_export-engine, phase1.17_export-publication-receipts, phase1.23_pyapi-pipeline-adapter

## Context

P1-EXPORT's parent task integrates the plan compiler, the encoders, the presets and the publication. Before it, there was no way to export a saved project end to end. `PublishExport` needed a `core::Project` built by a test driver. The only export verb of `UzPainter.exe` was `export --recover`. Item 3.2 (the determinism lane) asks to export the same project with the same configuration in two processes.

Facts:

- `ProjectStore::Open` gives the current revision of a `.uzp` file, with an integrity report.
- `ReadResource` gives verified resource bytes, and `mesh::RederiveMesh` rebuilds the texturing mesh from them.
- The receipt's ARC-11 `app_version` and `build` come from the caller (decision 097).
- No build of UzPainter carries a version string yet. Phase1.20 defines `application.version()` later.

## Decision

1. `UzPainter.exe export <file.uzp> --config <config.json> --app-version <version> --build <id>` exports the current revision (`src/export/project_export.h`, `ExportProject`). The steps:
   - it opens the file through the project store, taking its lock, and refuses a file whose integrity report is not clean (`ValueError`);
   - it compiles the configuration with the file's path as `$project` and runs `CheckExportable`;
   - it evaluates on the CPU store, bounded by the machine's physical memory, reading resources from the file and the mesh re-derived from its stored bytes;
   - it publishes through `PublishExport`.
2. The version and the build are required arguments, never invented defaults. The pipeline adapter (phase1.23) and the facade (phase1.20) pass their own identities.
3. The output and exit codes:
   - success prints `{generation, receipt, receipt_sha256, files}` as canonical JSON and exits 0;
   - a refusal prints `ValueError: ...` or `NotYetSupported: ...`, writes nothing and exits 1;
   - a failure prints its reason, leaves the previous generation selected and exits 1;
   - a usage error exits 2.
4. The export module links the project store in `uzp-export-tests.exe` too, so `tests/export/test_export_engine.py` drives the same code (`project`, `cli` verbs). Determinism means: two processes exporting into one exportPath publish byte-identical files and plans, and receipts that differ only in `generation` and `moment`.

## Consequences

- Item 3.2 is a test on every lane. The interruption suite of phase1.17 covers item 3.3 unchanged, because the command publishes through the same `PublishExport`.
- Exporting a project another worker holds open fails with the store's `locked` error. A read-only open is not needed in Phase 1.
- A refusal in the command cannot leave partial output: every check runs before `PublishExport` creates a generation.
