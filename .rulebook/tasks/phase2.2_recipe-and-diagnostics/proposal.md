# Proposal: phase2.2_recipe-and-diagnostics

## Why
P2-RECIPE in `docs/dag.md`, implementing D3 (`docs/architecture/03-project-model.md` §7, `docs/architecture/04-layer-stack-and-compositing.md` §8) and D7 (`docs/architecture/08-export.md` §5, §6). The pipeline needs a recipe dump with a deterministic digest that rebuilds identical exports, manifest blocks for every delivery, and faithful diagnostics for the paint gates; Tunic v10 recovery depends on dump-and-rebuild. Requirements: SAV-03, SAV-04, INT-20, INT-21, LAY-09, LAY-14, EXP-04, DIA-01, QG-01 (`docs/prd.md`). This parent is the integration and acceptance task; the work is split into two children.

## What Changes
- `dump_recipe`, `inspect`, rebuild path and manifest `exportacao` blocks: child `phase2.1_recipe-dump-manifest-blocks`.
- Isolation, contribution and material views, region statistics, snapshot and diff: child `phase2.1_recipe-diagnostic-views`.
- Wand v1 rebuild-from-dump evidence in `parity/reports/phase2/recipe-rebuild-wand.json` (digests, file hashes, pass/fail; no oracle data).

## Dependencies
- DAG input: `phase1.25_pilot-wand` (P1-WAND).
- Children (all mandatory): `phase2.1_recipe-dump-manifest-blocks`, `phase2.1_recipe-diagnostic-views`.
- Consumer: `phase2.10_pilot-tunic-recovery` (P2-TUNIC).

## Acceptance
DAG gate: rebuild-from-dump equality on wand — the wand v1 project dumped, rebuilt from the dump plus its referenced resources into a new project, and exported with the same configuration gives byte-identical files and the same recipe digest. The parent closes only when both children pass.

## Impact
- Affected specs: `recipe`
- Affected code: recipe dump, rebuild, diagnostics, export receipts
- Breaking change: NO
- User benefit: reproducible recipes and paint-gate diagnostics for every delivery
