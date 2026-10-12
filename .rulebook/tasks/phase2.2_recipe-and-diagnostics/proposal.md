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

## Child results
- `phase2.1_recipe-diagnostic-views` (decision 136): `uzpainter.diagnostics` (`isolate`, `contribution`, `material_views`, `region_stats`, `snapshot_layer_tree`, `diff_snapshots`) and the worker's five MCP Diagnostics tools. Its §3 tests are green on CPU: `tests/python/test_pyapi_diagnostics.py` (4 cases) and `tests/supervisor/test_worker_diagnostics.py` (1 case). Each view equals the OpenEXR 32f export of its `diagnosticMap` source. Its prerequisite item 1.1 (`phase1.25_pilot-wand` accepted) is still open. Item 3.2 here runs the same calls on the wand.

## Parent harness (decision 142)
- Scenario `tests/parity/recipe/wand_v1/runner.py`, tests `test_wand_recipe.py`. Report `tools/parity/recipe_rebuild.py` with schema `parity/schema/recipe-rebuild-report.json` and its guard rule.
- The gate compares UzPainter with itself, so it reads no Painter golden. It skips a comparison only on UzPainter's explicit refusal, and the skip names that refusal.
- Measured on 2026-10-12 with the R9-pinned scripts:
  - the rebuilt wand has the original's digest;
  - `isolate` restores state;
  - the wand's export is refused on both sides (phase1.25 item 2.7);
  - `material_views` is refused (8-bit sRGB `T_base`, phase1.15_compositor-colour-fits item 2.2).
- Every wand test waits on the R9 re-pin of the drifted Assets3D `painter_layer_stack.py` (decision 144).

## Impact
- Affected specs: `recipe`
- Affected code: recipe dump, rebuild, diagnostics, export receipts
- Breaking change: NO
- User benefit: reproducible recipes and paint-gate diagnostics for every delivery
