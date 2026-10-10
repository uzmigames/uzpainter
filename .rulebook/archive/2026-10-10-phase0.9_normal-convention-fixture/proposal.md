# Proposal: phase0.9_normal-convention-fixture

## Why
The Assets3D contract uses the OpenGL (+Y) normal convention and a MikkTSpace per-fragment frame, and both must be validated by a Phase 0 fixture before the mesh loader freezes its tangent code (PRD PRJ-04; `docs/architecture/12-mesh-import.md` §3). UzPainter computes tangents with Mikkelsen's reference `mikktspace.c` per corner; whether `PerFragment` (bitangent rebuilt per texel from interpolated N and T with the stored sign) or `PerVertex` equals Painter's frame is unknown, and the green-channel convention of the UzEngine consumer is unconfirmed. The render side relies on the same frame for normal mapping (`07-preview-and-render-parity.md` §3.3). Exact equality applies (Q1, decision 017); Painter outputs stay private (decision 022). `docs/dag.md` P0-NORMAL, implements D11 and D6.

## What Changes
- UzmiGames-authored hemisphere fixture: a low/high pair whose baked tangent-space normal field is analytically known; public manifest `parity/manifests/phase0/normal-convention.json`.
- Painter oracle: the hemisphere normal baked in Painter 12.1.0 through the documented baking API (Normal baker, OpenGL convention), recorded twice and admitted to the private store.
- UzPainter prototype in the P0-TOOLCHAIN build: MikkTSpace frames per corner (vendored `mikktspace.c` under its own licence), the same normal field expressed in the `PerVertex` and `PerFragment` frames.
- Comparison in tangent space at native depth, and the same map shaded in UzEngine's own executable as an external consumer fixture to fix its green-channel convention (12 §3).
- Tangent-frame verdicts: `parity/semantics/tangent-frame.json` (convention, frame mode, residuals, public source MikkTSpace) and `parity/reports/phase0/normal-convention.md` (numbers only).

## Dependencies
- Prerequisites: `phase0.3_painter-oracle-recorder` (P0-RECORDER), `phase0.5_private-oracle-store` (P0-STORE), `phase0.8_toolchain-slice` (P0-TOOLCHAIN).
- Successors: `phase1.7_mesh-loader` (P1-MESH) and gate `phase0.10_gate-g0` (G0).

## Acceptance
Convention and per-fragment frame settled with evidence (`docs/dag.md`, P0-NORMAL).

## Impact
- Affected specs: mesh
- Affected code: tangent-frame prototype in the UzPainter build, `thirdparty/mikktspace/`, `parity/manifests/`, `parity/semantics/`, `parity/reports/phase0/`
- Breaking change: NO
- User benefit: imported normals, baked normals and rendered normals agree with Painter and with the engine consumers
