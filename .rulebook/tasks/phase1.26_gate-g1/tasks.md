## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase0.10_gate-g0, phase1.25_pilot-wand, phase1.8_project-store, phase1.7_mesh-loader

## 2. Joined items
- [ ] 2.1 phase0.10_gate-g0 accepted: G0 Contract frozen
- [ ] 2.2 phase1.25_pilot-wand accepted: Wand v1 maps equal to the private Painter goldens (Tier 1) and byte-stable across two runs
- [ ] 2.3 phase1.8_project-store accepted: `09-…` §7 tests pass, including save/reopen/revert with fault injection and commit-then-die retry
- [ ] 2.4 phase1.7_mesh-loader accepted: `12-…` §9 fixtures pass, including the certificate and reload fixtures
- [ ] 2.5 Indirect items confirmed accepted through the joined items: phase1.4_render-core-layer, phase1.3_document-model, phase1.14_compositor-core, phase1.18_export-engine, phase1.24_python-api-facade (with the three pipeline scripts running unchanged through the adapter as its acceptance)

## 3. Gate record
- [ ] 3.1 Guard and `uzpainter parity verify` green on the gate commit: no oracle blob in the repository, every manifest hash resolves in the private store
- [ ] 3.2 Regenerate the capability manifest from the Phase 1 build and record its hash; every Phase 1 capability claimed `supported` carries Tier 0 evidence
- [ ] 3.3 Write `parity/reports/phase1/gate-g1.md`: each G1 clause with its task id, evidence paths and hashes (numbers and hashes only), the exceptions relied on, and the revised Phase 2 duration Hypothesis
- [ ] 3.4 Every other Phase 1 task (parents and children) archived in `.rulebook/archive/`

## 4. Acceptance
- [ ] 4.1 Acceptance gate (G1): all joined items accepted and every G1 clause of `docs/roadmap.md` evidenced in the gate record

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
