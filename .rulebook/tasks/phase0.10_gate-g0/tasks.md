## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase0.1_approved-source-index, phase0.8_tier0-goldens, phase0.8_toolchain-slice, phase0.6_procedural-feasibility, phase0.9_render-reference-capture, phase0.9_normal-convention-fixture

## 2. Joined items
- [ ] 2.1 phase0.1_approved-source-index accepted: approved-source index published
- [ ] 2.2 phase0.8_tier0-goldens accepted: Tier 0 goldens admitted (blobs private, hashes public); first `parity/semantics/*.json` fits with residuals
- [ ] 2.3 phase0.8_toolchain-slice accepted: vendored render core builds standalone; hardware `selftest` green on the owner's machine; WARP probe completed and reported; CPython boundary qualified or fallback chosen
- [ ] 2.4 phase0.6_procedural-feasibility accepted: residuals published; go/no-go for Phase 3 scope
- [ ] 2.5 phase0.9_render-reference-capture accepted: Iray capture procedure qualified; references admitted with their noise floor; fixture values proposed to the owner
- [ ] 2.6 phase0.9_normal-convention-fixture accepted: convention and per-fragment frame settled with evidence
- [ ] 2.7 Indirect items confirmed accepted through the joined items: phase0_owner-decisions, phase0.2_parity-contract, phase0.3_painter-oracle-recorder, phase0.5_private-oracle-store, phase0.5_vendor-render-core

## 3. Gate record
- [ ] 3.1 Cross-check: ray-query results of phase0.8_render-reference-fits agree with the `selftest` probe report of phase0.7_toolchain-probes on the owner's GPU, or the difference is explained in the record
- [ ] 3.2 Guard and `uzpainter parity verify` green on the gate commit: no oracle blob in the repository, every manifest hash resolves in the private store
- [ ] 3.3 Write `parity/reports/phase0/gate-g0.md`: each joined item with task id, evidence paths and hashes (numbers and hashes only); statement that no capability manifest exists before phase1.3_document-model; revised Phase 1 duration Hypothesis
- [ ] 3.4 Every other Phase 0 task (parents and children) archived in `.rulebook/archive/`

## 4. Acceptance
- [ ] 4.1 Acceptance gate (G0): all joined items accepted and every G0 clause of `docs/roadmap.md` evidenced in the gate record

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
