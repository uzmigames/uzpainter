## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: phase1.3_document-model, phase1.4_mesh-importers, phase1.5_mesh-tangents-certificate (1.3 and 1.4 archived; 1.5 complete locally in commit 3cecbfa with all local checks green, waiting only for its hosted CI run after the owner's next push: its code is treated as accepted)

## 2. Implementation
- [x] 2.1 Implement `reload_mesh` as one transaction: parse, certify, match sets by material identity, keep stacks and resources
- [x] 2.2 Reject renamed, split or merged materials with an explicit error carrying a mapping proposal
- [x] 2.3 Classify texels per set as unchanged, moved, new or replaced from the corner hashes, without the GPU
- [x] 2.4 Mark mesh-map bindings, geometry masks, procedural caches and downstream receipts `invalid`, keeping them
- [x] 2.5 Return `{sets: added, removed, renamed}` and the per-set region classes; leave the old mesh on any failure

## 3. Tests
- [x] 3.1 Reload of an identical mesh: no pixel or derivation change (no set changes, all texels unchanged, nothing invalidated); from the same path a `no_op`, from another path a metadata-only revision recording the new `mesh.source` (amended by decision 123)
- [x] 3.2 Reload with moved vertices: affected texels classified `moved`, dependent mesh maps marked `invalid` and kept
- [x] 3.3 Rename fixture: explicit error with a mapping proposal; project unchanged
- [x] 3.4 Split fixture: explicit error with a mapping proposal; project unchanged
- [x] 3.5 Failure injected mid-reload: the old mesh and all bindings are intact

## 4. Acceptance
- [x] 4.1 All tests of this child green on the hosted CPU lane

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
- [x] 5.2 Write tests covering the new behavior
- [x] 5.3 Run tests and confirm they pass

## Hosted CPU lane evidence

- Run 38100063195 on commit 8e5f3bc (2026-10-11): `tests/mesh/test_mesh_certificate.py`, `test_mesh_import.py` and `test_mesh_reload.py` all passed on the hosted CPU lane (the Painter comparison skips there with oracle_unavailable; its evidence is the local run). The run's two `tests/store` failures come from a partial commit of the store task and are fixed in 4c75222.
