# Proposal: phase1.7_mesh-loader

## Why
UzPainter has to import today's Assets3D meshes exactly as authored — corners, winding, materials and UVs untouched — certify them without repairing anything, generate tangent frames that match the settled convention, and reload a changed mesh without losing the layer stack. Requirements: PRJ-01, PRJ-02, PRJ-04, PRJ-07, PRJ-08, PRJ-09, PRJ-10, INT-10, INT-12, INT-14, BAK-06, QG-02 (`docs/prd.md`). Implements D11 (decision 013) under owner answer Q8 (decision 021: zero dependency on UzEngine; UzPainter neither vendors nor calls UzEngine's cook path) in `docs/architecture/12-mesh-import.md`, with the normal convention and per-fragment frame settled by P0-NORMAL. DAG node P1-MESH (`docs/dag.md`), joined directly by gate G1 ("certificate and reload fixtures pass", `docs/roadmap.md`).

This is the parent integration and acceptance task, split per the `docs/dag.md` task decomposition rule into three independently reviewable children.

## What Changes
Integration of the three children (DAG Outputs of P1-MESH: OBJ/FBX/glTF raw loader, texturing mesh, MikkTSpace frames, certificate, reload) under `src/mesh/`, tests and fixtures in `tests/mesh/` and `tests/mesh/fixtures/`:
- `phase1.4_mesh-importers`: `TexturingMesh`, own OBJ parser, FBX (ufbx) and glTF/GLB (fastgltf) importers, import contracts (triangulation, units, identity, orientation), texture sets per material.
- `phase1.5_mesh-tangents-certificate`: MikkTSpace frames (PerVertex/PerFragment) and the import certificate.
- `phase1.6_mesh-reload`: `reload_mesh` with binding preservation, changed-region report and invalidation.
High-poly streaming into Embree or GPU acceleration structures (`docs/architecture/12-mesh-import.md` §2, last row) is baker input and is delivered with P3-BAKER, not here.

## Dependencies
- DAG inputs: `phase1.3_document-model` (P1-DOCMODEL: project, texture-set and mesh-map binding types, transactions) and `phase0.9_normal-convention-fixture` (P0-NORMAL: convention and per-fragment frame verdicts).
- Children (all mandatory): `phase1.4_mesh-importers`, `phase1.5_mesh-tangents-certificate`, `phase1.6_mesh-reload`.
- Downstream: `phase1.14_compositor-core` (texturing mesh feeds the UV raster) and gate `phase1.26_gate-g1` (G1 joins P1-MESH directly).

## Acceptance
DAG gate of P1-MESH: the fixtures of `docs/architecture/12-mesh-import.md` §9 pass — mirrored UVs, hard edges, negative OBJ indices, n-gons, duplicate material names, instances/transforms, units, multi-set body, coincident opposite faces; reload/rename/split fixtures that preserve or deliberately reject bindings; the normal-convention fixture across Painter, UzPainter and UzEngine (UzEngine only as an external consumer running its own executable). The parent closes only when all three children are accepted.

## Impact
- Affected specs: `mesh`
- Affected code: `src/mesh/`, `tests/mesh/`, `tests/mesh/fixtures/`, vendored `thirdparty/ufbx/`, `thirdparty/fastgltf/`, `thirdparty/mikktspace/`
- Breaking change: NO
- User benefit: Today's meshes enter UzPainter bit-faithfully with a certificate that flags every defect and a reload that keeps the work.
