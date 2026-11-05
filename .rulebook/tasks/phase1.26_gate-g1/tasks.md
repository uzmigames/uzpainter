## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: phase0.10_gate-g0, phase1.25_pilot-wand, phase1.8_project-store, phase1.7_mesh-loader
  - Met 2026-11-05: all four archived (`2026-10-13-phase0.10_gate-g0`, `2026-11-03-phase1.25_pilot-wand` under EXC-010 (decision 395), `2026-10-13-phase1.8_project-store`, `2026-10-11-phase1.7_mesh-loader`); gate record §3
  - Runs last (decision 397, owner 2026-11-03): this gate's runs start only after every feature task of Phase 1 has passed its own tests

## 2. Joined items
- [x] 2.1 phase0.10_gate-g0 accepted: G0 Contract frozen
  - Archived `.rulebook/archive/2026-10-13-phase0.10_gate-g0/` (`0fffb00`, on the owner's order), every item checked; `parity/reports/phase0/gate-g0.md` (draft record `parity/reports/phase1/gate-g1.md` §3.1)
- [x] 2.2 phase1.25_pilot-wand accepted: Wand v1 maps equal to the private Painter goldens (Tier 1) and byte-stable across two runs
  - Met **under EXC-010, not exact** (decisions 395, 396): archived `.rulebook/archive/2026-11-03-phase1.25_pilot-wand/` (`9e83774d`). `parity/reports/phase1/tier1-wand-v1.json` (SHA-256 `5711b4a6…a942` at `b0265f97`) is `pass` relying on EXC-010 version 1: covered interior texels equal on all five maps, 42 Normal island-edge values and the padding excepted; oracle `stable`, rebuilds `repeatable`, save/reopen export byte-identical. The maps are the diagnostic measure export's; production still refuses the islanded export (`phase3.1_export-island-padding`). Gate record §3.5
- [x] 2.3 phase1.8_project-store accepted: `09-…` §7 tests pass, including save/reopen/revert with fault injection and commit-then-die retry
  - Archived `.rulebook/archive/2026-10-13-phase1.8_project-store/`. Re-run 2026-10-19 on `main` `39d8d7b`: `python -m pytest tests/store/test_store_settle.py` exit 0, 7 passed (`interruptions`, `two_layers`, `commit_then_die`, `pruned_key_replay`, `revert_edit_reopen_compact` and the two list/refusal cases), draft record §3.2
- [x] 2.4 phase1.7_mesh-loader accepted: `12-…` §9 fixtures pass, including the certificate and reload fixtures
  - Archived `.rulebook/archive/2026-10-11-phase1.7_mesh-loader/`. Re-run 2026-10-19 on `main` `39d8d7b`: `python -m pytest tests/mesh` exit 0, 30 passed, 0 skipped (certificate over OBJ/glTF/FBX, nine reload cases, normal-convention re-run against the store), draft record §3.3
- [x] 2.5 Indirect items confirmed accepted through the joined items: phase1.4_render-core-layer, phase1.3_document-model, phase1.14_compositor-core, phase1.18_export-engine, phase1.24_python-api-facade (with the three pipeline scripts running unchanged through the adapter as its acceptance)
  - Checked 2026-10-21 on `main` `8709033a`: all five archived with no unchecked item, at `.rulebook/archive/2026-10-10-phase1.4_render-core-layer/`, `2026-10-10-phase1.3_document-model/`, `2026-10-12-phase1.14_compositor-core/`, `2026-10-12-phase1.18_export-engine/` and `2026-10-21-phase1.24_python-api-facade/`. The pipeline scripts are phase1.24 items 3.2 and 4.1; in the coordinated full suite at `1103f00c` that accepted phase1.24, all 55 `tests/adapters` cases passed, none skipped (draft record §3.4, §3.6)

## 3. Gate record
- [ ] 3.1 Guard and `uzpainter parity verify` green on the gate commit: no oracle blob in the repository, every manifest hash resolves in the private store
  - Pre-verified 2026-10-19 on `39d8d7b` (not the gate commit): guard exit 0, 3775 files checked, 0 blocked; `store verify` exit 0 on both manifest roots (300 manifests and 21856 blobs; 82 and 2686) and on the whole store (draft record §1, §4)
  - Pre-gate re-run 2026-10-21 on `8709033a` (not the gate commit): guard exit 0, 4186 files checked, 0 blocked; `store verify` exit 0 on the current-envelope root (333 manifests, 22578 blobs) and on the whole store. `store verify parity/manifests` exit 1: refused on `parity/manifests/consumers/gltf/wand-v1.json`, a non-golden consumer fixture (`a34143c8`); its golden subdirectories verify exit 0 (82 manifests, 2686 blobs). Open for the gate commit (draft record §4.1) The directory-wide refusal is fixed: `store verify` leaves out the glTF consumer fixture, and `verify parity/manifests` exits 0.
  - Gate run 2026-11-05 (not yet the gate commit; G1 stays open on the full gate, item 3.3): the guard first blocked `parity/fixtures/meshes/plane.obj` on `store-hash`. It is an authored fixture (`6a2f26cc`, 2026-10-10) that the store had kept as an authored input on 2026-10-26 (decision 144); a false positive, fixed in `072756c0` (the rule leaves out blobs kept only as authored inputs; one a corpus record names stays blocked). On `072756c0` and `b0265f97`: guard exit 0, 5321 and 5329 files checked, 0 blocked; `store verify` exit 0 on the current envelope (426 manifests, 24144 blobs), on 12.1.5 (333, 22578), on `parity/manifests` (82, 2686) and on the whole store (gate record §4.2)
- [ ] 3.2 Regenerate the capability manifest from the Phase 1 build and record its hash; every Phase 1 capability claimed `supported` carries Tier 0 evidence
  - Pre-verified 2026-10-19 on `39d8d7b`: `zig build painter -j4` gives `capabilities.json` SHA-256 `4a52afe9…a557a`. All 546 `supported` entries carry Tier 0 evidence that resolves to current-envelope manifests (draft record §6). Re-run on the gate commit
  - Pre-gate re-run 2026-10-21 on `8709033a` (not the gate commit): `zig build painter -j2` exit 0, `capabilities.json` SHA-256 `4b0a7c47…f8a40a` (1 441 105 bytes). All 926 `supported` entries carry Tier 0 evidence: 99 current-envelope Tier 0 goldens, every blob `available`, 0 problems; the conformance and capabilities selection 8 passed (draft record §6.1) The directory-wide refusal is fixed: `store verify` leaves out the glTF consumer fixture, and `verify parity/manifests` exits 0.
  - Gate run 2026-11-05 on `072756c0` (not the gate commit): `zig build painter -j4` exit 0, `zig-out/bin/capabilities.json` SHA-256 `005c9168…5b8b` (1 558 752 bytes): 974 `supported`, 328 `pending-evidence`, 338 `release-gap`, 15 `desktop-only-omitted`. Every `supported` entry carries Tier 0 evidence: 111 current-envelope goldens, all 8660 of their blobs `available`, 0 problems. `b0265f97` changes the inventory, so the hash is re-recorded from the gate commit's build (gate record §6.2)
- [ ] 3.3 Write `parity/reports/phase1/gate-g1.md`: each G1 clause with its task id, evidence paths and hashes (numbers and hashes only), the exceptions relied on, and the revised Phase 2 duration Hypothesis
  - Drafted 2026-10-19 (`parity/reports/phase1/gate-g1.md`); the Wand clauses, phase1.24 and §7 are pending
  - Rewritten 2026-11-05: every clause evidenced (the Wand's under EXC-010), the exceptions relied on (§3.7), the revised Phase 2 Hypothesis (§7) and the full local gate (§8): red at `072756c0`, 96 failed and 3 errors of 7461; two root causes fixed (`1f830aca`, `b0265f97`, 21 node ids pass on re-run), 75 failed and 3 errors remain with causes and owners in §8.3. Final at closure, after a green full gate on the gate commit
- [x] 3.4 Every other Phase 1 task (parents and children) archived in `.rulebook/archive/`
  - Open 2026-10-19: phase1.15_compositor-colour-fits, phase1.24_python-api-facade and phase1.25_pilot-wand (draft record §5)
  - Open 2026-10-21 on `8709033a`: 41 of the 43 indexed Phase 1 tasks archived; open are only phase1.25_pilot-wand and this gate, which waits on it (draft record §5)
  - Met 2026-11-05 on `072756c0`: 42 of the 43 Phase 1 tasks of `docs/task-index.md` are archived; the only `phase1.*` task left under `.rulebook/tasks/` is this gate (gate record §5)

## 4. Acceptance
- [ ] 4.1 Acceptance gate (G1): all joined items accepted and every G1 clause of `docs/roadmap.md` evidenced in the gate record

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
