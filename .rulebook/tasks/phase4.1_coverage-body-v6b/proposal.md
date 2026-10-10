# Proposal: phase4.1_coverage-body-v6b

## Why
OWN-03 (`docs/prd.md`) requires body v6b to be reproduced with equal maps; PRJ-02 (several texture sets per project) is accepted by body v6b's three sets; PRJ-03 (per-set 4096) by the VRAM admission test; NFR-03 requires three 4096² sets in one project, measured separately; OWN-07, SAV-01 and NFR-04 require a self-contained, portable project far more compact than `.spp` (baseline 879 MB–1.19 GB for the body), measured by a size census against the 10 % candidate budget, with retention of the current and previous checkpoints plus the last 50 mutation revisions (owner decision 024, Q11). Stroke-painted content follows the corpus migration assumption (decisions 019 and 020). This is DAG node P4-BODY (`docs/dag.md`), implementing D14 and D8: `docs/roadmap.md` Phase 4 row; `docs/architecture/09-project-file-format.md` §2–§4 and §7 (census, retention, save semantics); `docs/architecture/04-layer-stack-and-compositing.md` §7 and `docs/architecture/13-engine-integration.md` §6 (memory admission; the body's three 4K sets fit in sequence); `docs/architecture/14-parity-testing.md` §2–§3 (Tier 1 rules, `not_migratable`).

## What Changes
- **Body v6b rebuilt**: recorded in Painter through the documented API (twice) and rebuilt in UzPainter from the same stack JSON and resources with identical external mesh maps — three 4096² texture sets in one project; manifest `parity/manifests/tier1/body-v6b.json`; Tier 1 report in `parity/reports/phase4/`.
- **Memory admission**: the three sets evaluated under the VRAM tile budget derived at startup (tiles in dependency order, LRU eviction); a texture-set creation above the budget fails explicitly; peak RAM and VRAM recorded per set and for the whole project.
- **Save/reopen**: save, close, reopen, re-export and compact cycles with equal maps after each; retention per Q11 verified on the body content; portable file with no `-wal`/`-shm` companion at rest.
- **Size census**: body v6b project bytes plus external dependency bytes, with the history retained under Q11, measured against the matched `.spp` after Painter's documented compact-save, linked bytes counted on both sides; ratio reported against the 10 % candidate budget for the owner's ratification.
- **Budgets measured**: evaluation, export, save, reopen and compaction times and peak memory on the body corpus, recorded for P5-PERF.
- Stroke-painted content imported as bitmaps when the documented export route preserves the output, otherwise `not_migratable` with the reason.

## Dependencies
- DAG input: `phase3.7_fixtures-bracers-hat5` (P3-BRACERS).
- Upstream used here: `phase1.8_project-store` (census instrumentation, retention, fault injection), `phase1.14_compositor-core` (tile admission).
- Downstream: `phase4.6_gate-g4` (G4); budgets feed `phase5.1_performance-budgets` (P5-PERF).

## Acceptance
DAG gate of P4-BODY: equal maps; budgets measured. In substance: every map of the three body v6b sets equals the private Painter goldens at native depth (or an owner-approved exception covers a difference) after rebuild and after save/reopen; memory admission holds the three 4K sets with peak memory recorded; the size census ratio against the matched `.spp` and the timing/memory budgets are published; a fixture marked `not_migratable` without an owner scope decision blocks acceptance.

## Impact
- Affected specs: `parity` (body v6b fixture)
- Affected code: `parity/manifests/tier1/body-v6b.json`, `parity/reports/phase4/` (Tier 1, census, budgets); product code only for defects the fixture exposes
- Breaking change: NO
- User benefit: the largest multi-set asset runs in UzPainter with equal maps, bounded memory and a measured compact project file
