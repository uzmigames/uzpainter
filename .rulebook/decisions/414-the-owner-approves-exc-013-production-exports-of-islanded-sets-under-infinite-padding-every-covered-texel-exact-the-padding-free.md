# 414. The owner approves EXC-013: production exports of islanded sets under `infinite` padding, every covered texel exact, the padding free

**Status**: accepted
**Date**: 2026-11-09
**Related Tasks**: phase3.1_export-island-padding, phase4.1_export-island-padding-exact, phase3.1_assets3d-cutover
**Supersedes in part**: decision 259 §4 (the production refusal of `infinite` padding on UV-islanded sets) and decision 396 §2 (what `phase3.1_export-island-padding` owns)

## Context

`phase3.1_export-island-padding` (decision 396) owns the exact `infinite` padding on UV-islanded texture sets, the exact Height outside the islands that the virtual Normal's island-edge texels read, and the lift of the two production refusals: `CheckPadding` (decision 259) and `CheckIslandNormal` (decision 245). Until then production refused both on every asset, so no islanded asset had a conformant delivery; the Wand, Tunic and Sash Tier 1 evidence was written only by the diagnostic measure export (decision 286) under their own exceptions (EXC-010, EXC-011 v3, EXC-012).

Where the padding stands (task notes through cf4c215e, decisions 408 to 410):
- Every covered texel is exact on every recorded islanded golden: the padding writes uncovered texels only, and decision 408's coverage equals Painter's on every recorded coverage probe (islands 256, fold tie, Tunic 4096; 0 wrong).
- 80 of 104 listed `infinite` golden files are exact r1 and r2 (`export-padding` 28 of 28, every seam golden); the bevelled cube and the sphere are not (ring 2,132 and 824 texels).
- The kernel probes still differ on 2,415 ring texels: exact-tie sides at seam ends on Pythagorean folds (the end-overhang sweep: a tie break below 1/64 texel that no float32 model reproduces), multi-facet chains, window-side ties, poles, and the cube, sphere and kernel-probe residuals.
- The virtual Normal's covered island-edge texels still differ: Wand 42 values, Sash 880, Tunic 25,393 (decisions 245, 263; item 2.2).

**The owner's answer** (André, 2026-11-09, relayed by the coordinator session). Asked how to unblock the islanded exports, he chose, verbatim, **"Liberar com exceção"** (release under an exception). The terms relayed with that choice:
- production may export UV-islanded texture sets with `infinite` padding, where every covered texel is exact and only the padding ring and gutter texels outside the UV coverage may differ from Painter;
- the remaining exact-padding classes (exact-tie sides at seam ends on Pythagorean folds, multi-facet chains, window-side ties, poles; the cube, sphere and kernel-probe residuals) move to a later task.

**Scope limit.** He approved only texels outside the coverage. The virtual Normal's covered island-edge texels are not included: `CheckIslandNormal` stays, and a combined virtual Normal on an islanded set stays refused in production until he decides separately.

This is his own yes to the terms below (decision 259 §6).

## Decision

1. **EXC-013 version 1** (`parity/exceptions.json`). EXC-007 stays withdrawn; EXC-008 to EXC-012 are taken.
   - **Tier and domain.** Tier 1, a new domain kind `production_export`, selector `export/islanded-infinite-padding`: the files a production export pads `infinite` over incomplete UV coverage. It lists no goldens. A comparison is in the domain only when the candidate's export receipt names EXC-013 in `exceptions_relied_on` (`Comparison.candidate_exceptions`); a receipt that does not name it is outside it.
   - **Bound.** `max_abs_diff` 0 over `covered`, with no excepted output: every covered texel of every map is exactly equal. The uncovered (padding) texels may differ, with no numeric bound (decision 223 §3).
   - **Fail-closed.** A comparison without a coverage mask, with a mask of another size or with no covered texel is not covered; a shape mismatch is structural and fails in every tier.
   - **Basis** `owner_scope_split`, `approved_by: owner`, `approved_on: 2026-11-09`. Defect test: `tests/parity/test_verdict.py::test_exc013_catches_injected_defects` (one covered interior value, one covered island-edge value on any map, the Normal's output included, a wrong covered region, a uniform offset, a structural difference, a missing or mis-sized mask, a receipt that does not name the entry: each fails).
2. **`CheckPadding`'s `infinite` refusal is lifted in production** (`src/export/guards.cpp` `PaddingRefusal`).
   - An `infinite` file on a texture set whose UV islands do not cover the tile is written: its covered texels are the evaluation's, its uncovered ones the measured padding (`padding.h`, decisions 223 to 409) over the set's triangles, which the export now reads from the texturing mesh (`SourceInputs::mesh`). Without that mesh the export fails before writing.
   - The other padding refusals on islanded sets stay: another algorithm, `passthrough` with an alpha layout or of a mesh or virtual map, and the resize of an islanded set (decision 349). The owner approved `infinite` only.
   - The diagnostic measure export (decision 286) no longer records a decision 259 bypass: nothing is refused there to bypass.
3. **`CheckIslandNormal` (decision 245) is unchanged.** A file that reads a combined virtual Normal over incomplete coverage is refused before writing under every padding, in production and in the preflight, as before; its message names `phase4.1_export-island-padding-exact` as owner (`kIslandsOwner`).
4. **Reporting: conformant under an exception, never exact.**
   - Each file padded under it lists EXC-013 (`EncodedFile::exceptions`). The export receipt gains `exceptions_relied_on`: [{exception_id `EXC-013`, version 1, decision `414`, paths}], and its manifest export block names it in `open_items`. A receipt without padded islanded files has no `exceptions_relied_on`.
   - Such a generation is conformant (no `non_conformant`): Assets3D manifest blocks are written for it (decision 286 §5 refuses only `non_conformant`), with the exception named.
   - Its parity verdict against a golden is "pass under EXC-013", never exact.
5. **Scope split** (the pattern of decisions 130, 393 and 396). `phase3.1_export-island-padding` closes on the delivered scope: the coverage rule (decision 408), the float32 and half padding operands (decision 409), EXC-011 v3 (decision 410), this lift and EXC-013. Moved to `phase4.1_export-island-padding-exact`, which owns them from now on:
   - item 2.1, the exact `infinite` padding on every texel (the classes above), with the separating recordings the notes name (an oblique-seam end-overhang sweep; candidate float32 tangent-frame models);
   - item 2.2, the exact Height outside the islands for the virtual Normal, decision 245 §2's empty-Height case included;
   - the lift of `CheckIslandNormal` for exactly what is exact, unless the owner decides the Normal's edge separately;
   - narrowing and withdrawing EXC-010, EXC-011 v3, EXC-012 and EXC-013 as parts become exact (decisions 395 §6, 398 §6, 410 §4).
6. **Why Phase 4, level 1.** Decision 396 put the work in Phase 3 because Phase 3 was the first phase whose acceptance needs a conformant production export of islanded sets. Under EXC-013 that export exists for every map but a combined virtual Normal, so exactness no longer gates Phase 3's padding needs; a Phase 3 task would make G3 (item 4.4: every Phase 3 task archived) wait on residual-bound work with no estimate, as decision 396 §3 refused for G1 and G2. It has no Phase 4 prerequisite, so level 1 (`docs/dag.md`, Task decomposition rule).

## Alternatives Considered

- **Except the Normal's island edge too.** Rejected: the owner approved texels outside the coverage only; the Normal waits on his separate decision.
- **Scope EXC-013 to the three pilots' goldens.** Rejected: the owner's terms are production exports, and the export cannot tell an asset's golden (decision 395 §4). The bound (every covered texel exact) is what makes an unscoped domain safe.
- **Keep the work in Phase 3** (a level 2 task). Rejected (§6).

## Consequences

- Production exports islanded sets under `infinite` for every map but a combined virtual Normal, marked as relying on EXC-013. A five-map pilot export that includes the Normal is still refused as a whole (the export is all or nothing, decision 091).
- `phase3.1_assets3d-cutover` item 3.1 has conformant non-Normal pilot exports to validate; its Normal deliveries still wait on the owner's decision on the Normal's edge or on `phase4.1_export-island-padding-exact`.
- EXC-010, EXC-011 v3 and EXC-012 are unchanged: their Tier 1 evidence still comes from the diagnostic measure export, which now bypasses decision 245's refusal only.
