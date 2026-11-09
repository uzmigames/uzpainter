# Proposal: phase4.1_export-island-padding-exact

## Why
Decision 414 lifts `CheckPadding`'s `infinite` refusal in production under the owner's EXC-013 (every covered texel exact, the padding outside the UV coverage free) and moves the remaining exactness work of `phase3.1_export-island-padding` here: the `infinite` padding is not yet Painter's on every texel, and the virtual Normal's covered island-edge texels still differ (Wand 42 values, Sash 880, Tunic 25,393), so a combined virtual Normal on an islanded set stayed refused in production (`CheckIslandNormal`, decision 245) until the owner decided separately: decision 417 (2026-11-09) writes it under EXC-014, its covered island-edge texels free and everything else exact, which this task narrows and withdraws as the Height outside the islands becomes exact. Under the clean-room rule the rule comes only from recorded observations of Painter.

## History (by reference)
The progress notes stay in `.rulebook/archive/2026-11-09-phase3.1_export-island-padding/tasks.md` (items 2.1 and 2.2) and, before decision 396, in `.rulebook/archive/2026-11-03-phase1.25_pilot-wand/tasks.md` item 2.7. Decisions, in order:
- Origin and moves: 090, 103, 396, 414.
- Ring, gutter and sign: 127, 176, 184, 197, 261, 264, 266.
- Exceptions: 220, 223, 259 (EXC-007 withdrawn), 395 (EXC-010), 398, 401 and 410 (EXC-011 v1 to v3), 399 (EXC-012), 414 (EXC-013).
- Island-edge Normal: 245, 263, 276, 283, 287, 289, 293, 308.
- Seam, window and far-tap rules: 339, 340, 342, 356, 358, 364, 365, 366, 368.
- Coverage and operands: 408 (float32 device coordinates, top-left rule), 409 (float32 operands before the read-out, half raw chain).
- Diagnostic reports: `parity/reports/phase1/padding-*.md`, `docs/analysis/padding-world-offset-residuals/`.

## What Changes
- The exact `infinite` padding on islanded sets, every texel, in `src/export/padding.cpp` and its CPU reference (`tests/export/padding_reference.py`), against the recorded `export-padding*` goldens and kernel probes, r1 and r2. Open classes at the move (decision 414): exact-tie sides at seam ends on Pythagorean folds (a tie break below 1/64 texel that none of 165 float32 models reproduces), multi-facet chains, window-side ties, poles; the bevelled cube and sphere goldens (ring 2,132 and 824 texels) and the kernel probes (2,415 ring texels).
- The exact Height outside the islands as Painter's island-edge Normal reads it (decision 263), so the virtual Normal is exact on every covered texel; decision 245 §2's empty-Height case with its recording.
- Lifting `CheckIslandNormal` (decision 245) for exactly what is exact, unless the owner decides the Normal's edge separately: done for a file of the combined Normal alone under `infinite` by the owner's decision 417 (EXC-014); the empty Height and the other readings of the Normal stay refused until 2.2.
- Narrowing EXC-010, EXC-011 v3, EXC-012, EXC-013 and EXC-014 by new versions as parts become exact, and withdrawing each when its golden, or production, passes with no exception (decisions 395 §6, 398 §6, 410 §4, 414).

## Dependencies
- Inputs from earlier phases: `phase3.1_export-island-padding` (archived: coverage, operands, EXC-013, the production lift); `phase1.18_export-engine`; the Wand v1, Sash v5 and Tunic v10 Tier 1 runners and goldens.
- No Phase 4 prerequisite, so level 1 (`docs/dag.md`, Task decomposition rule; decision 414 §6).
- Gate: joined by `phase4.6_gate-g4` (every Phase 4 task archived).
- Downstream: the Normal deliveries of `phase3.1_assets3d-cutover` item 3.1 on the islanded pilots, unless the owner decides the Normal's edge separately.

## Acceptance
`infinite` padding and the virtual Normal on islanded sets equal Painter on every texel of every recorded islanded golden, both recordings, on DX12; `CheckIslandNormal` lifted for that scope; the Wand v1, Sash v5 and Tunic v10 Tier 1 runs pass with no exception on the production export; EXC-010, EXC-011, EXC-012, EXC-013 and EXC-014 withdrawn.

## Impact
- Affected specs: export
- Affected code: `src/export/padding.*`, `src/export/guards.*`, `src/export/virtual_maps.*`, `tests/export/padding_reference.py`, `tests/export/`, `parity/exceptions.json`, `tests/parity/tier1/`
- Breaking change: NO
- User benefit: islanded textures, the Normal included, export as Painter writes them, with no exception
