# Proposal: phase4.6_gate-g4

## Why
Gate G4 "Coverage" closes Phase 4 (`docs/roadmap.md`, `docs/dag.md` gate rule): it joins every mandatory acceptance item of the phase, requires G3, and cannot be closed by any single work package carrying its evidence. Its criteria prove the PRD requirements Phase 4 delivers: the remaining certified corpus reproduced with equal maps (OWN-03; hat v8 for PRJ-06, BAK-08 and NFR-03 maps and layers; body v6b for PRJ-02 sets, NFR-03 and the OWN-07/NFR-04 census), the UV-tile workflow (OWN-01, PRJ-02), the remaining node, effect and source kinds with paint layers receiving bitmaps and projections (LAY-04, LAY-12; owner decision 019, Q5), and a capability manifest that keeps every remaining gap explicit (OWN-01, ARC-03). Implements D14 (`docs/roadmap.md`, `docs/dag.md`) with the tier, exception and migration rules of `docs/architecture/14-parity-testing.md` §2, §3, §5 and §8. The optional GPU baker P4-DXR is not a predecessor of any gate (`docs/dag.md` gate rule).

## What Changes
- Gate record `parity/reports/phase4/gate-g4.md` (numbers and hashes only): each joined item with its acceptance evidence, each G4 criterion with the report that proves it, the exceptions relied on, the `not_migratable` settling check, the regenerated capability manifest version with its gap list, the status of the optional P4-DXR, and the owner's signature.
- Regenerated capability manifest at the gate (roadmap rule 3).
- Revised duration Hypothesis for Phase 5, recorded in the gate record (roadmap rule 6, owner Q14).

## Dependencies
- DAG inputs (joined items): `phase3.8_gate-g3` (G3), `phase4.2_coverage-hat-v8` (P4-HAT8), `phase4.1_coverage-body-v6b` (P4-BODY), `phase4.2_remaining-nodes` (P4-NODES), `phase4.5_uv-tiles` (P4-TILES).
- Mandatory children reaching the gate through those inputs: `phase4.1_hat8-sharpen-filter`, `phase4.1_hat8-specular-weight-export`; `phase4.1_nodes-instances-anchors`, `phase4.1_nodes-mask-effects`, `phase4.1_nodes-projections`, `phase4.1_nodes-vector-font-sources`, `phase4.1_nodes-paint-layers`; `phase4.3_tiles-workflow`, `phase4.4_tiles-per-tile-resolution`, `phase4.4_tiles-export-filters`.
- Not joined (optional): `phase4.3_dxr-baker` (P4-DXR).
- Downstream: `phase5.1_performance-budgets` (P5-PERF), `phase5.2_packaging` (P5-PACKAGE), `phase5.4_parity-report` (P5-REPORT).

## Acceptance
DAG gate G4: all joined items accepted. Roadmap G4 criteria, each evidenced in the gate record: hat v8 and body v6b Tier 1 equal; UV tiles Tier 0/1 on a UDIM fixture; the capability manifest shows every remaining gap explicitly (arbitrary `.sbsar`, auto-unwrap, material layering, deferred export formats); Tier 0 extended to the new node kinds. A gate fixture marked `not_migratable` without an explicit owner scope decision fails G4 even if every other fixture passes (`docs/dag.md`, corpus migration assumption).

## Impact
- Affected specs: `gates` (G4)
- Affected code: none; `parity/reports/phase4/gate-g4.md`, capability manifest regeneration, `.rulebook/` archive of the Phase 4 tasks
- Breaking change: NO
- User benefit: an evidence-backed decision that the certified corpus and the documented layer model are covered, with every remaining gap visible, before stress and release work starts
