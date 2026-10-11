## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: phase1.3_document-model, phase0.9_normal-convention-fixture, phase1.4_mesh-importers

## 2. Implementation
- [x] 2.1 Vendor `mikktspace.c` from upstream with its licence; compute per-corner tangents and signs
- [x] 2.2 Implement the `PerVertex` and `PerFragment` frame rules (unset = PerVertex (Painter default, decision 031); PerFragment on request), with the OpenGL (+Y) convention from the P0-NORMAL verdict
- [x] 2.3 Implement the certificate corner and face counters (non-finite/zero normals, zero tangents/bitangents, degenerate TBN, flipped handedness, coincident opposite faces, zero-area and flipped UV triangles, n-gons triangulated)
- [x] 2.4 Implement the per-set UV metrics (outside 0–1, overlap px, islands, density px/cm, anisotropy, gap and border px) in the mesh module without the GPU
- [x] 2.5 Compute `status` pass|warn|fail, store the certificate with the mesh hash, and never modify the mesh

## 3. Tests
- [x] 3.1 Mirrored-UV fixture: flipped handedness counted and the frame sign correct per corner
- [x] 3.2 Hard-edge fixture: split corner normals preserved and tangents computed per corner
- [x] 3.3 Coincident-opposite-faces fixture (the hat lesson): counted under `faces.coincident_opposite`
- [x] 3.4 Zero-area and flipped UV triangles, degenerate TBN and UVs outside 0–1 each counted on dedicated fixtures; the mesh is unchanged after certification
- [x] 3.5 Per-set UV metrics on a synthetic two-island set equal their analytic values
- [x] 3.6 Normal-convention fixture re-run: the production tangent frames reproduce the P0-NORMAL verdict on the hemisphere fixture

## 4. Acceptance
- [x] 4.1 All tests of this child green (hosted CPU lane; the normal-convention comparison in a local run on the owner's machine, decision 028, whose report is the evidence)

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
- [x] 5.2 Write tests covering the new behavior
- [x] 5.3 Run tests and confirm they pass

## Hosted CPU lane evidence

- Run 38100063195 on commit 8e5f3bc (2026-10-11): `tests/mesh/test_mesh_certificate.py`, `test_mesh_import.py` and `test_mesh_reload.py` all passed on the hosted CPU lane (the Painter comparison skips there with oracle_unavailable; its evidence is the local run). The run's two `tests/store` failures come from a partial commit of the store task and are fixed in 4c75222.
