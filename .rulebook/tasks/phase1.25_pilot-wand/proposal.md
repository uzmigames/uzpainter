# Proposal: phase1.25_pilot-wand

## Why
Wand v1 is the Phase 1 smoke fixture of the pilot order Wand v1 → Belt v5 → Tunic v10 (owner Q7; `docs/roadmap.md`, "Pilot order"). It is the first end-to-end proof that a real Assets3D stack, rebuilt from the same stack JSON, resources and external mesh maps through the unchanged pipeline scripts, yields maps equal to Painter's and stable byte for byte. Requirements: OWN-03, ACC-01, G-03, G-04, BAK-01 (Wand v1 Tier 1 is its acceptance criterion), INT-10, EXP-05, NFR-02 (`docs/prd.md`). Implements D14 (decision 016) with owner answers Q1 (decision 017: exact equality, exceptions only through the register), Q6 (decision 020: migration rebuilt through Painter's documented API, no `.spp` reader) and Q7, using Tier 1 of `docs/architecture/14-parity-testing.md` §1–§4. DAG node P1-WAND (`docs/dag.md`), joined directly by gate G1.

## What Changes
- `parity/manifests/phase1/wand-v1.json`: independently authored inputs (stack JSON, resource hashes, external mesh-map hashes, instruction sequence `painter_create` → `sync` → `painter_export`, project settings), software identities (Painter 12.1.0 build id, UzPainter build hash) and the SHA-256 of every private oracle record.
- Wand v1 Tier 1 goldens recorded on the owner's machine with the oracle recorder (`tools/parity/recorder/`) by rebuilding Wand v1 in Painter through its documented API from the same inputs (G-03; no `.spp` reader), each recorded twice (same session; after save/reopen) and stability-classified; blobs only in `UZP_PARITY_STORE`.
- The UzPainter rebuild of Wand v1 through the UzmiGames pipeline adapter (`UzPainter.exe run` with `painter_create.py`, `painter_layer_stack.py sync`, `painter_export.py`, scripts pinned by SHA-256) on DX12 with identical external mesh maps (BAK-01), run twice.
- `parity/reports/phase1/tier1-wand-v1.json`: per exported map and set, oracle stability, UzPainter repeatability and equality to Painter reported separately, with max |Δ|, mean |Δ|, p99 |Δ|, differing-texel count and percentage, and per-region breakdown by the asset's material masks (numbers and hashes only; difference maps stay private).

## Dependencies
- DAG input: `phase1.24_python-api-facade` (P1-PYAPI: `uzpainter` module, facade, `run`, pipeline adapter). Through it: `phase1.18_export-engine`, `phase1.14_compositor-core`, `phase1.8_project-store`, `phase1.7_mesh-loader`, `phase1.3_document-model`, `phase1.4_render-core-layer`.
- Phase 0 evidence used: `phase0.3_painter-oracle-recorder` (recorder and capture procedure), `phase0.5_private-oracle-store` (store, `uzpainter parity fetch/verify/record`, guard), `phase0.2_parity-contract` (golden schemas, exception register).
- Downstream: gate `phase1.26_gate-g1`; Phase 2 nodes `phase2.4_supervisor-worker`, `phase2.3_realtime-preview`, `phase2.2_recipe-and-diagnostics`, `phase2.9_pilot-belt`.

## Acceptance
DAG gate of P1-WAND: maps equal (every exported Wand v1 map equals the private Painter golden at native decoded values, Tier 1, with no preset tolerance; a difference passes only through an owner-approved entry of `parity/exceptions.json`); byte-stable across two runs (the two UzPainter runs produce byte-identical files). If any Wand v1 content cannot be migrated through Painter's documented API it is recorded `not_migratable` with the reason and G1 stays blocked unless an explicit owner scope decision covers it (`docs/dag.md`, corpus migration assumption).

## Impact
- Affected specs: `parity`
- Affected code: `parity/manifests/phase1/wand-v1.json`, `parity/reports/phase1/tier1-wand-v1.json`, `tests/parity/tier1/wand_v1` (runner executed locally on the owner's machine, decision 028; hosted CI skips it with an explicit reason)
- Breaking change: NO
- User benefit: The first real asset proves the whole Phase 1 chain — mesh, stack, compositor, export, scripts — against Painter, with numbers the owner can check.
