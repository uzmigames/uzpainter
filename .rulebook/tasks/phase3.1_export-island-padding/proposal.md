# Proposal: phase3.1_export-island-padding

## Why
Decision 396 moves `phase1.25_pilot-wand` item 2.7 here, so that the Wand closes on its Tier 1 pass under EXC-010 (decision 395). Two export cases on UV-islanded texture sets are still not exact, so production refuses both before writing, on every asset:
- `infinite` padding (decision 259, `CheckPadding`);
- a virtual Normal, whose island-edge texels read Painter's padded Height outside the islands (decisions 245, 263, `CheckIslandNormal`).

The Wand's five maps are written past those refusals only by the diagnostic measure export (decision 286), which marks its receipt `non_conformant`. No asset with UV islands has a conformant delivery until this task is done. Under the clean-room rule the rule comes only from recorded observations of Painter.

## History (by reference)
The item's progress notes stay in the Wand task, `.rulebook/archive/2026-11-03-phase1.25_pilot-wand/tasks.md` item 2.7. The decisions, in order:
- Origin: decisions 090 (R-090 partial fit) and 103 (split from `phase1.18_export-engine` item 6.1).
- Ring, gutter and sign: decisions 127, 176, 184, 197, 261, 264, 266.
- Exceptions: 220 (±1 code does not hold), 223 (EXC-007), 259 (EXC-007 withdrawn, refusal restored), 395 (EXC-010, Wand v1 only).
- Island-edge Normal: decisions 245, 263, 283, 287, 289, 293, 308.
- Diagnostic measure export: decision 286.
- Seam, window and far-tap rules: decisions 339, 340, 342, 356, 358, 364, 365, 366, 368 (fronts of decision 367).
- Diagnostic reports: `parity/reports/phase1/padding-*.md`, `docs/analysis/padding-world-offset-residuals/`.

## What Changes
- The exact `infinite` padding rule on islanded sets, every texel (ring, seams, corners, poles, gutter), in `src/export/padding.cpp` and its CPU reference, against the recorded `export-padding*` goldens and kernel probes, on both recordings.
- The exact Height outside the islands as Painter's island-edge Normal reads it (decision 263), so the virtual Normal is exact on every covered texel; decision 245 §2's empty-Height case with it.
- Lifting `CheckPadding` (decision 259) and `CheckIslandNormal` (decision 245) for exactly what is exact; the rest stays refused.
- The refusals' owner string (`kIslandsOwner` in `src/export/guards.h`, and the messages that name `phase1.25_pilot-wand item 2.7`) renamed to this task.
- EXC-010 narrowed by a new version as each part becomes exact (decision 395 §6: the padding first, then the Normal's edge), and withdrawn when the Wand v1 Tier 1 run passes with no exception.

## Dependencies
- Inputs from earlier phases: `phase1.18_export-engine` (archived: `CheckPadding`, `CheckIslandNormal`, the padding passes); the Wand v1 Tier 1 runner and goldens of `phase1.25_pilot-wand`.
- No same-phase prerequisite, so level 1 (`docs/dag.md`, Task decomposition rule).
- Gate: joined by `phase3.8_gate-g3` item 4.4 (every Phase 3 task archived).
- Downstream, by item: `phase3.1_assets3d-cutover` 3.1 (a conformant Wand, Belt and Tunic delivery writes manifest blocks; a `non_conformant` export gets none, decision 286 §5), and the Belt and Tunic pilots' exports (`phase2.9_pilot-belt`, `phase2.10_pilot-tunic-recovery`), unless each relies on an owner-approved exception of its own.

## Acceptance
`infinite` padding and the virtual Normal on islanded sets equal Painter on every texel of every recorded islanded golden, both recordings, on DX12; both refusals lifted for that scope; the Wand v1 Tier 1 run passes with no exception and EXC-010 is withdrawn.

## Impact
- Affected specs: export
- Affected code: `src/export/padding.*`, `src/export/guards.*`, `src/export/virtual_maps.h`, `tests/export/padding_reference.py`, `tests/export/`, `parity/exceptions.json`, `tests/parity/tier1/wand_v1/`
- Breaking change: NO
- User benefit: textures with UV islands export as Painter writes them, with no exception and through the production path
