# 142. The wand rebuild gate compares UzPainter with itself, takes its resources from export-bundle, and skips only on an explicit refusal

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase2.2_recipe-and-diagnostics, phase2.1_recipe-dump-manifest-blocks, phase2.1_recipe-diagnostic-views, phase1.25_pilot-wand, phase1.15_compositor-colour-fits

## Context

`phase2.2_recipe-and-diagnostics` is the P2-RECIPE parent. Its children are merged; each stays open only on the prerequisite `phase1.25_pilot-wand` (P1-WAND). The parent's own items are:

- the Wand v1 rebuild-from-dump scenario (2.1) and its report (2.2);
- the gate tests on the wand: rebuild equality (3.1) and the diagnostics (3.2);
- the gate record (4.1).

The parent's launch brief asked for the wand items to skip until the Wand Tier 1 golden (R9) exists. A run on 2026-10-12, with the R9-pinned scripts, measured these facts:

- **Rebuild.** The wand builds through the Assets3D adapter (create, sync). `dump_recipe()` dumps it. `UzPainter.exe export-bundle` gives every stored resource: 17 files (the OBJ, two mesh maps, fourteen images). `rebuild_from_recipe` rebuilds a new project from the dump and those files alone. The rebuilt project dumps the same body, the same rebuild block and the same digest.
- **Export.** The wand's pinned `painter_export.py` is refused before writing, identically on both sides. The refusal is `NotYetSupported`: `infinite` padding on UV islands (R-090, phase1.25_pilot-wand item 2.7).
- **Diagnostics.** `isolate` on the wand's root group leaves the revision, every visibility flag and the layer tree unchanged. `material_views` on each of the four material groups is refused: the wand's `T_base` is an 8-bit sRGB colour bitmap, and only the 16-bit one is recorded (`evaluator:unsupported_source`, phase1.15_compositor-colour-fits item 2.2). This gap also stands behind the wand's five-map export once padding is fitted.
- **Script drift.** Assets3D commit 9a718b9 changed the pinned `Pipeline/painting/painter_layer_stack.py`. As a result every wand test fails at the recorder's hash check until R9 is re-pinned. That work belongs to `wand-repin` (decision 144); the run above used the pinned bytes from Assets3D f49fe67, staged outside the repository.

No model panel was consulted: these are test-design choices with no scope consequence (speed rule 3).

## Decision

1. **The gate compares UzPainter with itself.** Rebuild equality reads no Painter golden. The wand tests therefore do not skip on a missing R9 golden; they run wherever the asset repository and `zig` are present. The admitted golden's manifest replaces the request once it exists (`job_manifest()`). The items stay unchecked while the prerequisite P1-WAND is open.
2. **Resources come from the project itself.** The rebuild reads the files that `export-bundle` writes for the original project, renamed `<sha256><ext>`. Bundle `res/` plus `meshmaps/` is the layout `rebuild_from_recipe` reads (decision 122). This proves that the dump and the project's stored resources are enough.
3. **Both projects are exported by the pinned export script.** The rebuilt project is saved in the work directory and carried as the adapter session. The pinned export script runs on it unchanged, with only its `out` repointed to a second folder.
4. **Report.** `parity/schema/recipe-rebuild-report.json` (`uzpainter/parity/recipe-rebuild-report/1`) holds:
   - the job's id and manifest hash, the build hash, the compatibility profile and the application version;
   - the stored resources' hashes;
   - per side, the digest, the revision and either the exported files (name, SHA-256, size) or the refusal class;
   - the equality: `pass`, `export_refused` or `fail`.

   `tools/parity/recipe_rebuild.py` builds and validates it. The repository guard admits it only at `parity/reports/<phase>/recipe-rebuild-*.json`, and only when it validates. `export_refused` never satisfies the gate. The report is written only by the acceptance run (`UZP_RECIPE_REBUILD_REPORT`).
5. **Skips name the real refusal.** A comparison skips only when UzPainter refuses the evaluation with `NotYetSupported` before writing, and the skip reason is the refusal's own message. The export refusal must be the same on both sides, or the digest test fails. `material_views` refusals are caught per material group, and the test skips naming each one.
6. **What stays open.**
   - 1.1 to 1.3 stay open: P1-WAND, and the children, which are open on it.
   - 3.1's byte equality waits for phase1.25 item 2.7, then phase1.15_compositor-colour-fits item 2.2.
   - 3.2's material views wait for phase1.15_compositor-colour-fits item 2.2.
   - 4.1 waits on all of the above.

**Addendum (2026-10-12).** After the re-pin (decision 144) was merged, `tests/parity/recipe/wand_v1` ran from the repository, with no staged bytes. 2 passed (digest equality, `isolate`) and 2 skipped, with the refusals above as reasons.
