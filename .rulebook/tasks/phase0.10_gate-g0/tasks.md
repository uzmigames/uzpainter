## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: phase0.1_approved-source-index, phase0.8_tier0-goldens, phase0.8_toolchain-slice, phase0.6_procedural-feasibility, phase0.9_oracle-envelope, phase0.9_normal-convention-fixture

## 2. Joined items
- [x] 2.1 phase0.1_approved-source-index accepted: approved-source index published
- [x] 2.2 phase0.8_tier0-goldens accepted: Tier 0 goldens admitted (blobs private, hashes public); first `parity/semantics/*.json` fits with residuals
- [x] 2.3 phase0.8_toolchain-slice accepted: vendored render core builds standalone; hardware `selftest` green on the owner's machine; WARP probe completed and reported; CPython boundary qualified or fallback chosen
- [x] 2.4 phase0.6_procedural-feasibility accepted: residuals published; go/no-go for Phase 3 scope
- [x] 2.5 phase0.9_oracle-envelope accepted: environment record on every admitted golden; Tier 0 stability study published; canary procedure tested (decision 034)
- [x] 2.6 phase0.9_normal-convention-fixture accepted: convention and per-fragment frame settled with evidence
- [x] 2.7 Indirect items confirmed accepted through the joined items: phase0_owner-decisions, phase0.2_parity-contract, phase0.3_painter-oracle-recorder, phase0.5_private-oracle-store, phase0.5_vendor-render-core

## 3. Gate record
- [x] 3.1 Moved out of G0 with the Iray leg (decision 033): the cross-check of phase0.8_render-reference-fits ray-query results against the phase0.7_toolchain-probes `selftest` report belongs to P0-FEAS-RENDER, the entry gate of P3-PATHTRACER
- [x] 3.2 Guard and `uzpainter parity verify` green on the gate commit: no oracle blob in the repository, every manifest hash resolves in the private store
- [x] 3.3 Write `parity/reports/phase0/gate-g0.md`: each joined item with task id, evidence paths and hashes (numbers and hashes only); statement that no capability manifest exists before phase1.3_document-model; revised Phase 1 duration Hypothesis
- [x] 3.4 Every other Phase 0 task (parents and children) archived in `.rulebook/archive/`, except the Iray leg (phase0.9_render-reference-capture and its children phase0.6_render-reference-procedure, phase0.7_render-reference-captures, phase0.8_render-reference-fits), which stays open as the entry gate of P3-PATHTRACER (decision 033), and phase0.7_tier0-semantics-ui-cases, which the owner ruled must not block G0 (answer to q1 of phase0.6_tier0-semantics-goldens, 2026-10-10); its three cases stay release gaps until it closes. Both exemptions are listed with their sources in `parity/reports/phase0/gate-g0.md` §5

## 4. Acceptance
- [x] 4.1 Acceptance gate (G0): all joined items accepted and every G0 clause of `docs/roadmap.md` evidenced in the gate record

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
- [x] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
