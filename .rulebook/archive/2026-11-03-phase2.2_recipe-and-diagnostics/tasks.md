## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: phase1.25_pilot-wand
  - Accepted and archived 2026-11-03 under EXC-010, not exactly (`9e83774d`, `.rulebook/archive/2026-11-03-phase1.25_pilot-wand/`; decisions 395, 396)
- [x] 1.2 Child accepted: phase2.1_recipe-dump-manifest-blocks (archived 2026-10-20, decision 326)
- [x] 1.3 Child accepted: phase2.1_recipe-diagnostic-views (archived 2026-10-20, decision 326)

## 2. Implementation
- [x] 2.1 Wand v1 rebuild-from-dump scenario: dump, rebuild into a new project from the dump and its resources, export both with the wand's export configuration — `tests/parity/recipe/wand_v1/runner.py` (decision 142): the adapter-built wand, `dump_recipe()`, the stored resources from `export-bundle`, `rebuild_from_recipe` into a saved project, the pinned `painter_export.py` on both; measured 2026-10-12 up to the export, which UzPainter refuses before writing on both sides (3.1)
- [x] 2.2 Report writer for `parity/reports/phase2/recipe-rebuild-wand.json` — `tools/parity/recipe_rebuild.py`, schema `parity/schema/recipe-rebuild-report.json` (digests, file hashes and sizes, outcome `pass` / `export_refused` / `fail`), guard rule `parity/reports/<phase>/recipe-rebuild-*.json`; tests `tests/parity/test_recipe_rebuild_report.py`, `tests/parity/test_guard.py`; the report itself is written by the acceptance run (4.1)

## 3. Tests
- [x] 3.1 Wand v1 rebuild: every exported file byte-identical and recipe digests equal — `test_wand_recipe.py`. Digests equal: green on 2026-10-12, with the same body and rebuild block. Byte equality is skipped on UzPainter's refusal of the wand's export (`infinite` padding on UV islands, phase1.25 item 2.7; the 8-bit sRGB `T_base` refusal was lifted by phase1.15_compositor-colour-fits item 2.2, archived 2026-10-19)
  - Green 2026-11-03 at `2ea36342` through the diagnostic measure export (decision 286), as the Wand's Tier 1 test runs since decision 395: `runner.run(..., diagnostic=True)`, each receipt marked `non_conformant` and naming only the decided refusals (decisions 245, 259). ReleaseFast build `20982dff…` (decision 223): `test_wand_recipe.py` 4 passed in 73.9 s, both 3.1 cases and both 3.2 cases. Recipe digests equal (`5a1e45fa…`); the five maps (BaseColor, Height, Metallic, Normal, Roughness) byte-identical, same names, SHA-256 and sizes. The original's comparison with Painter relies on EXC-010 version 1 (`parity/reports/phase1/tier1-wand-v1.json`); production still refuses both islanded cases (owner `phase3.1_export-island-padding`), so this shows rebuild equality, not a conformant delivery
- [x] 3.2 Diagnostics on wand v1: `isolate` on each root group restores state; `material_views` on the wand's material masks matches the exported maps — `test_wand_recipe.py`. `isolate`: green on 2026-10-12. `material_views`: green on 2026-10-19 at 3b7c70a, CPU (`test_wand_material_views_match_the_exported_maps`: 1 passed, 0 skipped, 401 s, exit 0; evidence tmp/scratch/material-views/20261019T234827Z/ run.json and junit.xml), after phase1.15 item 2.2 lifted the `T_base` refusal

## 4. Acceptance
- [x] 4.1 DAG gate met: rebuild-from-dump equality on wand; report written to `parity/reports/phase2/recipe-rebuild-wand.json`
  - Met 2026-11-03 (`f5e1f723`, refreshed at `8089e68a`): the report, written by the 3.1 run and valid against `parity/schema/recipe-rebuild-report.json`, gives `digests_equal` true, `files` identical, both exports `mode` `diagnostic_measure` and outcome `pass`. The rebuild comparison is exact. The original's own Tier 1 comparison relies on EXC-010 version 1 (decision 395); the report schema has no field for that, so this note states it

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation — `03-project-model.md` §7, `parity/CONTRACT.md` §7, `parity/GUARD.md`, decision 142
- [x] 5.2 Write tests covering the new behavior
- [x] 5.3 Run tests and confirm they pass. On 2026-10-12, after the R9 re-pin (decision 144), `tests/parity/recipe/wand_v1` ran from the repository: 2 passed (digest equality, `isolate`) and 2 skipped on their stated refusals, which stay under 3.1 and 3.2. `test_recipe_rebuild_report.py`, `test_guard.py` and `test_schemas.py` gave 136 passed, and `tier1/test_tier1_compare.py` 20 passed

## Archive (2026-11-03)

Accepted on 2026-11-03: the Wand v1 rebuild from its dump is equal (digests and every exported file byte for byte), through the diagnostic measure export; the original's comparison with Painter relies on EXC-010 (decisions 286, 395). Every item is checked. Evidence: the ReleaseFast runs of `2ea36342` and `8089e68a` and the report `parity/reports/phase2/recipe-rebuild-wand.json` (`8089e68a`). The archive rests on the affected tests (CLAUDE.md's test-time override of 2026-10-12); it is not a coordinated full-suite acceptance.
