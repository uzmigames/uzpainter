# Proposal: phase1.26_gate-g1

## Why
Gate G1 "Foundation green" closes Phase 1 on evidence, not on date (owner Q14). It joins the phase's terminal items and requires G0, so Phase 2 cannot start its pilots until the foundation is proven: Wand v1 equal to Painter and byte-stable, the pipeline scripts running unchanged, the project store's save/reopen/revert surviving fault injection, and the mesh certificate and reload fixtures passing (`docs/roadmap.md`, Phase 1 row and Rules 2, 3, 6; `docs/dag.md`, Gate rule). Requirements: OWN-03, ACC-01, OWN-04, OWN-07, PRJ-08, PRJ-09, PRJ-10, ARC-02 (`docs/prd.md`). Implements D14 (decision 016). A work package carrying the gate's evidence cannot close the gate by itself.

## What Changes
- Gate record `parity/reports/phase1/gate-g1.md` (numbers and hashes only; oracle blobs stay in the private store) listing, for each joined item, its accepted task, evidence paths and hashes, and the roadmap G1 clauses:
  - G0 accepted;
  - Wand v1 maps equal to the private Painter goldens (Tier 1) and byte-stable across two runs;
  - the three pipeline scripts run unchanged through the adapter;
  - project save/reopen/revert verified with fault injection, including commit-then-die retry;
  - certificate and reload fixtures pass.
- Capability manifest regenerated at the gate (roadmap Rule 3) and its hash recorded.
- `.rulebook` archive of every Phase 1 task (roadmap Rule 3).
- Revised Phase 2 duration Hypothesis (owner Q14, roadmap Rule 6).

## Dependencies
- Joined items (must be accepted): `phase0.10_gate-g0` (G0, previous gate), `phase1.25_pilot-wand` (P1-WAND), `phase1.8_project-store` (P1-STORE), `phase1.7_mesh-loader` (P1-MESH).
- Reached through the joined items (must also be accepted): `phase1.4_render-core-layer`, `phase1.3_document-model`, `phase1.14_compositor-core`, `phase1.18_export-engine`, `phase1.24_python-api-facade` and all their children.
- Successor: `phase2.11_gate-g2` (G2 requires G1).

## Acceptance
G1 Foundation green (requires G0): Wand v1 maps equal to the private Painter goldens (Tier 1) and byte-stable across two runs; the three pipeline scripts run unchanged through the adapter; project save/reopen/revert verified with fault injection including commit-then-die retry; certificate and reload fixtures pass. All joined items accepted (`docs/dag.md`: G1 inputs G0, P1-WAND, P1-STORE, P1-MESH).

## Impact
- Affected specs: `gates`
- Affected code: `parity/reports/phase1/gate-g1.md`, regenerated `capabilities.json`, `.rulebook/archive/`
- Breaking change: NO
- User benefit: Phase 2 starts from a foundation whose parity, durability and import behaviour are proven and recorded.
