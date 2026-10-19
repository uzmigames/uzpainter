## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase0.10_gate-g0, phase1.25_pilot-wand, phase1.8_project-store, phase1.7_mesh-loader

## 2. Joined items
- [x] 2.1 phase0.10_gate-g0 accepted: G0 Contract frozen
  - Archived `.rulebook/archive/2026-10-13-phase0.10_gate-g0/` (`0fffb00`, on the owner's order), every item checked; `parity/reports/phase0/gate-g0.md` (draft record `parity/reports/phase1/gate-g1.md` §3.1)
- [ ] 2.2 phase1.25_pilot-wand accepted: Wand v1 maps equal to the private Painter goldens (Tier 1) and byte-stable across two runs
- [x] 2.3 phase1.8_project-store accepted: `09-…` §7 tests pass, including save/reopen/revert with fault injection and commit-then-die retry
  - Archived `.rulebook/archive/2026-10-13-phase1.8_project-store/`. Re-run 2026-10-19 on `main` `39d8d7b`: `python -m pytest tests/store/test_store_settle.py` exit 0, 7 passed (`interruptions`, `two_layers`, `commit_then_die`, `pruned_key_replay`, `revert_edit_reopen_compact` and the two list/refusal cases), draft record §3.2
- [x] 2.4 phase1.7_mesh-loader accepted: `12-…` §9 fixtures pass, including the certificate and reload fixtures
  - Archived `.rulebook/archive/2026-10-11-phase1.7_mesh-loader/`. Re-run 2026-10-19 on `main` `39d8d7b`: `python -m pytest tests/mesh` exit 0, 30 passed, 0 skipped (certificate over OBJ/glTF/FBX, nine reload cases, normal-convention re-run against the store), draft record §3.3
- [ ] 2.5 Indirect items confirmed accepted through the joined items: phase1.4_render-core-layer, phase1.3_document-model, phase1.14_compositor-core, phase1.18_export-engine, phase1.24_python-api-facade (with the three pipeline scripts running unchanged through the adapter as its acceptance)
  - Pre-verified 2026-10-19: phase1.4, phase1.3, phase1.14 and phase1.18 archived. Open: phase1.24 items 1.1 (stale text; its three prerequisites are now archived), 3.1 (owner question q1), 3.4 (P22-B, decision 189) and 4.1 (draft record §3.6)

## 3. Gate record
- [ ] 3.1 Guard and `uzpainter parity verify` green on the gate commit: no oracle blob in the repository, every manifest hash resolves in the private store
  - Pre-verified 2026-10-19 on `39d8d7b` (not the gate commit): guard exit 0, 3775 files checked, 0 blocked; `store verify` exit 0 on both manifest roots (300 manifests and 21856 blobs; 82 and 2686) and on the whole store (draft record §1, §4)
- [ ] 3.2 Regenerate the capability manifest from the Phase 1 build and record its hash; every Phase 1 capability claimed `supported` carries Tier 0 evidence
  - Pre-verified 2026-10-19 on `39d8d7b`: `zig build painter -j4` gives `capabilities.json` SHA-256 `4a52afe9…a557a`. All 546 `supported` entries carry Tier 0 evidence that resolves to current-envelope manifests (draft record §6). Re-run on the gate commit
- [ ] 3.3 Write `parity/reports/phase1/gate-g1.md`: each G1 clause with its task id, evidence paths and hashes (numbers and hashes only), the exceptions relied on, and the revised Phase 2 duration Hypothesis
  - Drafted 2026-10-19 (`parity/reports/phase1/gate-g1.md`); the Wand clauses, phase1.24 and §7 are pending
- [ ] 3.4 Every other Phase 1 task (parents and children) archived in `.rulebook/archive/`
  - Open 2026-10-19: phase1.15_compositor-colour-fits, phase1.24_python-api-facade and phase1.25_pilot-wand (draft record §5)

## 4. Acceptance
- [ ] 4.1 Acceptance gate (G1): all joined items accepted and every G1 clause of `docs/roadmap.md` evidenced in the gate record

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
