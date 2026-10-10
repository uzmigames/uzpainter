# Proposal: phase0.4_vendor-check

## Why
After the copy, UzPainter's vendored render core evolves independently of UzEngine (decision 021, owner Q8). That independence is only safe if every change to the copy stays visible: Apache-2.0 §4(b) requires a prominent notice in each modified file, ARC-07 requires local modifications to be marked and logged, OWN-02 forbids any engine path in the build, and the glTF 32/48-byte stride defect is avoided only as long as its files never enter the folder (`docs/architecture/13-engine-integration.md` §2.4, §3.3). A manual review would miss silent edits, so `13-…` §3.3 specifies a vendoring check that runs in CI on every commit. Release criterion 2 of `docs/licensing-and-clean-room.md` §5 also requires the vendoring check to pass. Child of `phase0.5_vendor-render-core` (implements D12; PRD LIC-02, ARC-07, OWN-02).

## What Changes
- A vendoring check under `tools/vendoring/` (the location is this task's choice; `13-…` fixes the rules, not the path) that reads `thirdparty/uzengine-render-core/MANIFEST.json` and `MODIFICATIONS.md` and fails on each rule of `13-…` §3.3:
  - hash drift: a recomputed SHA-256 that differs from `vendored_sha256`, a `verbatim` entry whose `vendored_sha256` differs from `upstream_sha256`, or a `modified` entry whose modification ids are missing from `MODIFICATIONS.md`;
  - a `modified` file without the §4(b) notice naming its id, original path and commit;
  - a file under the folder that has no manifest entry (the metadata files `LICENSE`, `ORIGIN.md`, `MANIFEST.json` and `MODIFICATIONS.md` excepted), or a manifest entry whose file is missing;
  - a path on the denylist: `asset/importers/**`, `asset/formats/uzmesh_format.*`, `asset/formats/uztexture_format.cpp`, `renderer/**`, `engine/config/**`;
  - conflict markers in any vendored file;
  - an include or library path of the build (read from the build's verbose compiler and linker invocations) that points outside the UzPainter repository, other than the pinned Zig toolchain's own directories and the Windows SDK; any path into a UzEngine checkout fails by name.
- Wiring into the hosted CPU lane of CI on every commit (`14-parity-testing.md` §7), with a non-zero exit and a per-rule message on failure.
- Negative fixtures: one deliberately broken copy of the folder per rule, used by the check's own tests.

## Dependencies
- Prerequisites: `phase0_owner-decisions` (P0-OWNER, archived), `phase0.1_vendor-core-copy` (manifest and copy), `phase0.3_vendor-modifications` (modification log, notices, `build.zig`).
- Parent: `phase0.5_vendor-render-core` (P0-VENDOR) closes only when this child passes.
- Successors: every later commit touching `thirdparty/uzengine-render-core/`; `phase5.2_packaging` and `phase5.5_clean-history` rely on the check passing on the released tree.

## Acceptance
The vendoring check passes on the vendored folder as imported and modified, fails with the right rule on each negative fixture, and runs in CI on every commit. Contributes to the P0-VENDOR gate "no `runtime.lib`, no submodule, no engine path, no pin or patch queue" (`docs/dag.md`) and to G0 "vendored render core builds standalone" (`docs/roadmap.md`).

## Impact
- Affected specs: render-core
- Affected code: `tools/vendoring/` (new), CI workflow of the hosted CPU lane
- Breaking change: NO
- User benefit: any unlogged edit, missing licence notice, defective mesh-cook file or engine path is caught on the commit that introduces it
