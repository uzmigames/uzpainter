## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase1.3_document-model, phase1.4_mesh-importers, phase1.5_mesh-tangents-certificate

## 2. Implementation
- [ ] 2.1 Implement `reload_mesh` as one transaction: parse, certify, match sets by material identity, keep stacks and resources
- [ ] 2.2 Reject renamed, split or merged materials with an explicit error carrying a mapping proposal
- [ ] 2.3 Classify texels per set as unchanged, moved, new or replaced from the corner hashes, without the GPU
- [ ] 2.4 Mark mesh-map bindings, geometry masks, procedural caches and downstream receipts `invalid`, keeping them
- [ ] 2.5 Return `{sets: added, removed, renamed}` and the per-set region classes; leave the old mesh on any failure

## 3. Tests
- [ ] 3.1 Reload of an identical mesh: no set changes, all texels unchanged, nothing invalidated
- [ ] 3.2 Reload with moved vertices: affected texels classified `moved`, dependent mesh maps marked `invalid` and kept
- [ ] 3.3 Rename fixture: explicit error with a mapping proposal; project unchanged
- [ ] 3.4 Split fixture: explicit error with a mapping proposal; project unchanged
- [ ] 3.5 Failure injected mid-reload: the old mesh and all bindings are intact

## 4. Acceptance
- [ ] 4.1 All tests of this child green on the hosted CPU lane

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
