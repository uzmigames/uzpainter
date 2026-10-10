# Proposal: phase1.18_export-engine

## Why
Every parity verdict and every Assets3D delivery goes through export: maps must be byte-deterministic, equal to Painter's Tier 0 export goldens, and published atomically so a consumer never reads a half-written delivery. Requirements: EXP-01…EXP-06, EXP-09, EXP-10, INT-13, INT-21, QG-03, NFR-02, ARC-11 (`docs/prd.md`). Implements D7 (decision 009: Painter-compatible JSON compiled into a validated plan) with owner answer Q10 (decision 023) in `docs/architecture/08-export.md` §1–§6; Phase 1 covers the plan compiler, padding/resize/dither, PNG8/16, EXR, the PBR, Blender and inline presets, generation-directory publication and receipts, while the Unreal, glTF and UzEngine presets and the TGA/BMP/JPEG/DDS writers follow in P3-UNREAL and P3-UZE. DAG node P1-EXPORT (`docs/dag.md`), on the critical path of `docs/roadmap.md` Phase 1.

This is the parent integration and acceptance task, split per the `docs/dag.md` task decomposition rule into four independently reviewable children.

## What Changes
Integration of the four children (DAG Outputs of P1-EXPORT) under `src/export/`, presets in `assets/export-presets/`, tests in `tests/export/`:
- `phase1.15_export-plan-compiler`: Painter export configuration → typed plan, dry run, virtual maps, explicit refusal of unsupported identifiers and formats.
- `phase1.16_export-processing-encoders`: padding, resize, dithering, bit depth and colour encoding, PNG8/16 and EXR writers.
- `phase1.17_export-presets`: `PBR Metallic Roughness`, `Blender (Principled BSDF)` and the Assets3D inline five-map preset, each with a provenance record.
- `phase1.17_export-publication-receipts`: generation-directory publication with an atomic `current.json` pointer, fixed-name copy journal and delivery adapter, receipts with the `exportacao` block.

## Dependencies
- DAG input: `phase1.14_compositor-core` (P1-COMPOSITOR: evaluated channels, virtual normal sources, diagnostics).
- Children (all mandatory): `phase1.15_export-plan-compiler`, `phase1.16_export-processing-encoders`, `phase1.17_export-presets`, `phase1.17_export-publication-receipts`.
- Downstream: `phase1.24_python-api-facade` (P1-PYAPI) and, in Phase 3, `phase3.3_unreal-gltf-presets` and `phase3.4_uzengine-preset`.

## Acceptance
DAG gate of P1-EXPORT: Tier 0 export goldens exact; byte determinism (same build + same project + same config ⇒ identical bytes); publication interruption tests pass (a consumer sees the old or the new complete generation at every interruption point). The parent closes only when all four children are accepted.

## Impact
- Affected specs: `export`
- Affected code: `src/export/`, `assets/export-presets/`, `parity/semantics/`, `tests/export/`, vendored `thirdparty/libpng/`, `thirdparty/zlib/`, `thirdparty/tinyexr/`
- Breaking change: NO
- User benefit: Deterministic, Painter-equal exports that consumers can never catch half-written.
