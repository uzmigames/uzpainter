# 326. A complete task whose only open item is its prerequisite phase1.25_pilot-wand closes on a recorded scope split, because phase1.25 is blocked only by Painter recordings

Date: 2026-10-20. Status: accepted (owner request: "atualiza e arquive as tasks finalizadas e foque em terminar as tasks q ja tao mais avancadas").
Related: phase1.25_pilot-wand, phase1.26_gate-g1, decisions 069, 130 and 131 (scope-split precedent), the agent brief's speed rule 4 (2026-10-12).

## Context

Eight Phase 2 tasks have every item checked except item 1.1, "Prerequisites accepted: phase1.25_pilot-wand" (the five phase2.1 tasks, phase2.2_preview-capture, phase2.2_supervisor-admission-ledger and phase2.3_supervisor-jobs). Their deliverables are on main, and their own tests passed in the last green full gate (86c2b91c, 3273 passed).

phase1.25 is open only on work that is blocked by Painter recordings:
- item 2.7, `infinite` padding: its residuals need decisions 289/293/298 and 283's recordings, packaged in operation-v2 and waiting for the owner's runtime authorization;
- items 3.1 to 4.1, which follow from 2.7.

None of the eight deliverables reads the Wand's exported maps or their parity. They cover the preview, display presets, diagnostic views, recipe dump blocks, supervisor IPC, the admission ledger and supervisor jobs.

Speed rule 4, applied in decisions 069, 130 and 131, checks an item that is blocked only by a recording or by a later phase as a recorded scope split with an owner, as long as nothing claimed is untrue.

## Decision

1. **Item 1.1 of each of the eight tasks is checked as a recorded scope split.** The note names phase1.25 as not accepted, its open items, and this decision. Nothing claims phase1.25 is accepted.
2. **The Wand's parity stays owned by phase1.25 and the G1 gate.** phase1.26 items 2.2 and 4.1 still require phase1.25 accepted. Any rebuild-from-the-Wand item stays open in its own task, for example phase2.2_recipe-and-diagnostics 3.1.
3. **Text superseded:** the 1.1 note of phase2.1_recipe-dump-manifest-blocks, which kept that task open until phase1.25 and G1 were accepted.
4. **Each task is archived under `.rulebook/archive/2026-10-20-<id>/`.** The order is children before parents: phase2.1, then phase2.2, then phase2.3.

## Consequences

- Eight tasks leave the open list. Their dependants can close the same way once their own items are evidenced: phase2.4_supervisor-worker 4.1, then phase2.5 to 2.8.
- If a later Wand recording changes a shared component, the fix lands under phase1.25 or a new task, not by reopening these.
