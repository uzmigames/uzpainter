# Proposal: phase1.5_mesh-tangents-certificate

## Why
Normal maps only match Painter if UzPainter builds the same per-corner tangent frames (MikkTSpace) with the convention P0-NORMAL settled, and pipeline gates need a certificate that flags — never repairs — degenerate frames, coincident faces, flipped or zero-area UV triangles, UVs outside 0–1 and per-set UV quality (PRJ-04, PRJ-09, PRJ-10, QG-02). Implements D11 (decision 013) under owner answer Q8 (decision 021: zero dependency on UzEngine; UzPainter neither vendors nor calls UzEngine's cook path) in `docs/architecture/12-mesh-import.md`, with the normal convention and per-fragment frame settled by P0-NORMAL. Child of `phase1.7_mesh-loader` (P1-MESH), covering `docs/architecture/12-mesh-import.md` §3 (tangents) and §4. `docs/dag.md` gives P1-MESH no P1-CORE input, so the pixel-domain metrics of this task are computed by the mesh module without the GPU UV raster pass of `phase1.3_core-uv-raster` and run on the hosted CPU lane.

## What Changes
- `src/mesh/tangents.{h,cpp}` over Mikkelsen's reference `mikktspace.c` (vendored from upstream under its own licence): per-corner tangent + sign; `TangentSpace.PerVertex` (interpolated bitangent) and `PerFragment` (bitangent rebuilt per texel from interpolated N and T with the stored sign; default, as the pipeline); OpenGL (+Y) as the Assets3D contract, per the P0-NORMAL verdict.
- `src/mesh/certificate.{h,cpp}`: the certificate JSON of `docs/architecture/12-mesh-import.md` §4 (`corners`, `faces`, `uv` with `per_set` overlap, islands, density px/cm min/p50/max, anisotropy, gap and border px, `mesh`, `hashes`, `status` pass|warn|fail), computed at import, stored with the mesh hash, never auto-repairing; diagnostic imports proceed with `warn`.

## Dependencies
- DAG inputs of the parent: `phase1.3_document-model`, `phase0.9_normal-convention-fixture` (convention and per-fragment frame verdicts).
- Sibling prerequisite: `phase1.4_mesh-importers`.
- Parent: `phase1.7_mesh-loader`.

## Acceptance
The `docs/architecture/12-mesh-import.md` §9 fixtures owned by this child pass: mirrored UVs, hard edges, coincident opposite faces, the certificate fixtures, and the normal-convention fixture re-run with the production tangents.

## Impact
- Affected specs: `mesh`
- Affected code: `src/mesh/tangents.*`, `src/mesh/certificate.*`, `thirdparty/mikktspace/`, `tests/mesh/`
- Breaking change: NO
- User benefit: Tangent frames that match the settled convention and a certificate that tells the pipeline exactly what is wrong with a mesh.
