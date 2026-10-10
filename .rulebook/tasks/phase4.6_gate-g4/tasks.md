## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: `phase3.8_gate-g3`, `phase4.2_coverage-hat-v8`, `phase4.1_coverage-body-v6b`, `phase4.2_remaining-nodes`, `phase4.5_uv-tiles`

## 2. Joined items
- [ ] 2.1 G3 accepted and its gate record present in `parity/reports/phase3/gate-g3.md`
- [ ] 2.2 P4-HAT8 accepted (`phase4.2_coverage-hat-v8`, with `phase4.1_hat8-sharpen-filter` and `phase4.1_hat8-specular-weight-export`)
- [ ] 2.3 P4-BODY accepted (`phase4.1_coverage-body-v6b`)
- [ ] 2.4 P4-NODES accepted (`phase4.2_remaining-nodes`, with `phase4.1_nodes-instances-anchors`, `phase4.1_nodes-mask-effects`, `phase4.1_nodes-projections`, `phase4.1_nodes-vector-font-sources`, `phase4.1_nodes-paint-layers`)
- [ ] 2.5 P4-TILES accepted (`phase4.5_uv-tiles`, with `phase4.3_tiles-workflow`, `phase4.4_tiles-per-tile-resolution`, `phase4.4_tiles-export-filters`)

## 3. Criteria evidence
- [ ] 3.1 Hat v8 Tier 1 equal: every exported map equal to the private Painter goldens; SpecularWeight consumer gap reported in the receipts
- [ ] 3.2 Body v6b Tier 1 equal on all three sets; memory admission, save/reopen and size census measured and referenced
- [ ] 3.3 UV tiles Tier 0/1 on the UDIM fixture
- [ ] 3.4 Tier 0 corpus extended to the new node, effect and source kinds and passing
- [ ] 3.5 Capability manifest lists every remaining gap explicitly: arbitrary `.sbsar`, auto-unwrap, material layering, deferred export formats and any other unproven capability
- [ ] 3.6 Settling check: no gate fixture marked `not_migratable` without an owner scope decision in the capability manifest and gate record
- [ ] 3.7 Every exception relied on is an owner-approved entry in `parity/exceptions.json` and listed in the gate record
- [ ] 3.8 Status of the optional `phase4.3_dxr-baker` recorded (qualified backends or not delivered); it neither blocks nor satisfies G4

## 4. Gate record
- [ ] 4.1 Capability manifest regenerated and its version recorded
- [ ] 4.2 Duration Hypothesis for Phase 5 revised and recorded (roadmap rule 6)
- [ ] 4.3 Gate record written to `parity/reports/phase4/gate-g4.md` (numbers and hashes only)
- [ ] 4.4 Every other mandatory Phase 4 task archived in `.rulebook` (roadmap rule 3)

## 5. Acceptance
- [ ] 5.1 DAG gate G4 met: all joined items accepted; owner signs the gate record

## 6. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 6.1 Update or create documentation covering the implementation
- [ ] 6.2 Write tests covering the new behavior
- [ ] 6.3 Run tests and confirm they pass
