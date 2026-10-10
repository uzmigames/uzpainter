## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase1.3_document-model, phase0.9_normal-convention-fixture, phase1.4_mesh-importers

## 2. Implementation
- [ ] 2.1 Vendor `mikktspace.c` from upstream with its licence; compute per-corner tangents and signs
- [ ] 2.2 Implement the `PerVertex` and `PerFragment` frame rules, defaulting to `PerFragment`, with the OpenGL (+Y) convention from the P0-NORMAL verdict
- [ ] 2.3 Implement the certificate corner and face counters (non-finite/zero normals, zero tangents/bitangents, degenerate TBN, flipped handedness, coincident opposite faces, zero-area and flipped UV triangles, n-gons triangulated)
- [ ] 2.4 Implement the per-set UV metrics (outside 0–1, overlap px, islands, density px/cm, anisotropy, gap and border px) in the mesh module without the GPU
- [ ] 2.5 Compute `status` pass|warn|fail, store the certificate with the mesh hash, and never modify the mesh

## 3. Tests
- [ ] 3.1 Mirrored-UV fixture: flipped handedness counted and the frame sign correct per corner
- [ ] 3.2 Hard-edge fixture: split corner normals preserved and tangents computed per corner
- [ ] 3.3 Coincident-opposite-faces fixture (the hat lesson): counted under `faces.coincident_opposite`
- [ ] 3.4 Zero-area and flipped UV triangles, degenerate TBN and UVs outside 0–1 each counted on dedicated fixtures; the mesh is unchanged after certification
- [ ] 3.5 Per-set UV metrics on a synthetic two-island set equal their analytic values
- [ ] 3.6 Normal-convention fixture re-run: the production tangent frames reproduce the P0-NORMAL verdict on the hemisphere fixture

## 4. Acceptance
- [ ] 4.1 All tests of this child green (hosted CPU lane; the normal-convention comparison in a local run on the owner's machine, decision 028, whose report is the evidence)

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
