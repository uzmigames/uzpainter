## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase1.25_pilot-wand
- [x] 1.2 Child accepted: phase2.1_recipe-dump-manifest-blocks (archived 2026-10-20, decision 326)
- [x] 1.3 Child accepted: phase2.1_recipe-diagnostic-views (archived 2026-10-20, decision 326)

## 2. Implementation
- [x] 2.1 Wand v1 rebuild-from-dump scenario: dump, rebuild into a new project from the dump and its resources, export both with the wand's export configuration — `tests/parity/recipe/wand_v1/runner.py` (decision 142): the adapter-built wand, `dump_recipe()`, the stored resources from `export-bundle`, `rebuild_from_recipe` into a saved project, the pinned `painter_export.py` on both; measured 2026-10-12 up to the export, which UzPainter refuses before writing on both sides (3.1)
- [x] 2.2 Report writer for `parity/reports/phase2/recipe-rebuild-wand.json` — `tools/parity/recipe_rebuild.py`, schema `parity/schema/recipe-rebuild-report.json` (digests, file hashes and sizes, outcome `pass` / `export_refused` / `fail`), guard rule `parity/reports/<phase>/recipe-rebuild-*.json`; tests `tests/parity/test_recipe_rebuild_report.py`, `tests/parity/test_guard.py`; the report itself is written by the acceptance run (4.1)

## 3. Tests
- [ ] 3.1 Wand v1 rebuild: every exported file byte-identical and recipe digests equal — `test_wand_recipe.py`. Digests equal: green on 2026-10-12, with the same body and rebuild block. Byte equality is skipped on UzPainter's refusal of the wand's export (`infinite` padding on UV islands, phase1.25 item 2.7; the 8-bit sRGB `T_base` refusal was lifted by phase1.15_compositor-colour-fits item 2.2, archived 2026-10-19)
- [x] 3.2 Diagnostics on wand v1: `isolate` on each root group restores state; `material_views` on the wand's material masks matches the exported maps — `test_wand_recipe.py`. `isolate`: green on 2026-10-12. `material_views`: green on 2026-10-19 at 3b7c70a, CPU (`test_wand_material_views_match_the_exported_maps`: 1 passed, 0 skipped, 401 s, exit 0; evidence tmp/scratch/material-views/20261019T234827Z/ run.json and junit.xml), after phase1.15 item 2.2 lifted the `T_base` refusal

## 4. Acceptance
- [ ] 4.1 DAG gate met: rebuild-from-dump equality on wand; report written to `parity/reports/phase2/recipe-rebuild-wand.json`

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation — `03-project-model.md` §7, `parity/CONTRACT.md` §7, `parity/GUARD.md`, decision 142
- [x] 5.2 Write tests covering the new behavior
- [x] 5.3 Run tests and confirm they pass. On 2026-10-12, after the R9 re-pin (decision 144), `tests/parity/recipe/wand_v1` ran from the repository: 2 passed (digest equality, `isolate`) and 2 skipped on their stated refusals, which stay under 3.1 and 3.2. `test_recipe_rebuild_report.py`, `test_guard.py` and `test_schemas.py` gave 136 passed, and `tier1/test_tier1_compare.py` 20 passed
