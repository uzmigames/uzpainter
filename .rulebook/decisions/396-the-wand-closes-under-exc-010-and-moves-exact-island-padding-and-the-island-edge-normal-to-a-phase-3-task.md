# 396. The Wand closes under EXC-010 and moves exact island padding and the island-edge Normal to a Phase 3 task

**Status**: accepted
**Date**: 2026-11-03
**Related Tasks**: phase1.25_pilot-wand, phase3.1_export-island-padding, phase1.26_gate-g1

## Context

The owner approved EXC-010 for the Wand v1 (decision 395). The Wand's Tier 1 run passes under it through the diagnostic measure export (decision 286), and items 3.1 to 3.3 are checked. Item 2.7 stays open: the exact `infinite` padding on UV-islanded sets. With it, the exact Height outside the islands, which the Normal's island-edge texels read (decisions 245, 263). Production still refuses both on every asset (decisions 245, 259).

Item 2.7's own text says the Wand item is done only when that padding is exact on every texel (decision 259). That no longer matches the Wand's acceptance, which EXC-010 now covers. Left in the Wand, it holds the pilot and gate G1 on work that EXC-010 already excepts. That work has no end date: decisions 127 to 368 narrowed the residuals but have not closed them.

Earlier splits set the pattern: decisions 130 (`phase1.15_compositor-colour-fits`) and 393 (`phase3.2_source-substance-presets-inputs`). The moved item gets a new owner task, the source item names it, and nothing claims the moved work is done.

## Decision

1. **Item 2.7 moves to `phase3.1_export-island-padding`.** In the Wand task it is checked as moved, with a note naming the new task and this decision. Its progress notes stay there as history. The new task's proposal lists the decisions by number and copies no page.
2. **The new task owns:**
   - the exact rule on every texel;
   - the exact Height outside the islands for the island-edge Normal, decision 245 §2's empty-Height case included;
   - lifting `CheckPadding` (decision 259) and `CheckIslandNormal` (decision 245) for exactly what is exact;
   - renaming the refusals' owner (`kIslandsOwner`, `src/export/guards.h`), which still names `phase1.25_pilot-wand item 2.7`. That is a native edit, so it is not part of this split;
   - narrowing EXC-010 by versions, and withdrawing it once the Wand passes with no exception (decision 395 §6).
3. **Why Phase 3, level 1.**
   - **Not Phase 1.** G1 item 3.4 requires every other Phase 1 task archived. A Phase 1 follow-up such as decision 130's would hold G1 again, which is what this split removes.
   - **Not Phase 2.** G2 item 3.5 requires every Phase 2 task archived. That would make G2 wait on exactness. G2's criteria only ask for Tier 1 parity "under the exception policy".
   - **Phase 3 is the first phase whose acceptance needs a conformant production export of islanded sets.** `phase3.1_assets3d-cutover` item 3.1 writes the Assets3D manifest blocks for the Wand, Belt and Tunic rounds. A `non_conformant` export gets no manifest (decision 286 §5).
   - **Level 1**, because it has no same-phase prerequisite. Its inputs are `phase1.18_export-engine` (archived) and the Wand's runner and goldens (`docs/dag.md`, Task decomposition rule). G3 joins it through its item 4.4.
4. **Belt and Tunic.** Their exports are islanded too, and stay refused in production. EXC-010 covers neither. Each pilot either relies on an owner-approved exception of its own, through the measure export as the Wand did, or waits on this task. This decision does not choose for them. Their notes now name the new task instead of the Wand item.
5. **Unchanged:** the production refusals, EXC-010's terms, decisions 245, 259 and 286, and the Wand's "pass under EXC-010, never exact" reporting (decision 395 §6).

## Alternatives Considered

- **Keep 2.7 in the Wand.** Rejected: the Wand could not close although its acceptance is met under the owner's exception.
- **A Phase 1 follow-up**, like decisions 130 and 103. Rejected: G1 item 3.4 would wait on it.
- **A Phase 2 task.** Rejected: G2 would wait on exactness that its criteria do not require.

## Consequences

- `phase1.25_pilot-wand` can close on its Tier 1 pass under EXC-010.
- `docs/task-index.md` gains the Phase 3 row.
- The Belt and Tunic tasks name `phase3.1_export-island-padding` as the owner of the refusal that stops their exports.
