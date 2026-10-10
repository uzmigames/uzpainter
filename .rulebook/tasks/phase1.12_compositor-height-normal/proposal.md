# Proposal: phase1.12_compositor-height-normal

## Why
Height is authored in declared units and converted to a normal; the exported normals must combine the mesh normal map, the channel normal and the height-derived normal exactly as Painter does, and relief must be applied exactly once with every normal tagged `geometry_only` or `combined` (MAT-05, EXP-09, PRJ-04). Implements D3 (decision 005: Painter-semantic document with a tile/channel evaluator and a measured quantisation profile) with owner answer Q1 (decision 017: exact equality, a divergence passes only through an owner-approved exception) in `docs/architecture/04-layer-stack-and-compositing.md`; formulas are written from public literature and fitted to Tier 0 goldens recorded through Painter's documented API (`docs/architecture/14-parity-testing.md` §2, §3; CLR-01, CLR-02; `docs/licensing-and-clean-room.md`). Child of `phase1.14_compositor-core` (P1-COMPOSITOR), covering `docs/architecture/04-layer-stack-and-compositing.md` §6 (height, normal, virtual normal maps); named in the `docs/dag.md` decomposition rule.

## What Changes
- `src/evaluator/height.{h,cpp}`: Height as a signed channel in its template storage format; `SignedAddition` and `LinearDodge` semantics from the blend kernels.
- `src/evaluator/height_to_normal.{h,cpp}` + kernel: finite-difference gradient of the height channel scaled by a strength parameter, for both methods Painter offers in its project settings; footprint, scaling and edge handling fitted from Tier 0 height ramps into `parity/semantics/height-to-normal.json`.
- `src/evaluator/normal_combine.{h,cpp}`: the fitted normal-blend operator combining mesh normal map, channel normal and height-derived normal, converted to OpenGL or DirectX; provides the sources of the virtual maps `Normal_OpenGL`/`Normal_DirectX` (tag `combined` with the relief round) and the geometry-only pass-through (tag `geometry_only`) consumed by the export plan.

## Dependencies
- DAG inputs of the parent: `phase0.8_tier0-goldens` (height ramps, normal blends), `phase1.7_mesh-loader` (tangent frames for the mesh normal map).
- Sibling prerequisites: `phase1.10_compositor-blend-kernels`, `phase1.11_compositor-mask-effects`.
- Parent: `phase1.14_compositor-core`. Consumer: `phase1.15_export-plan-compiler` (virtual normal maps).

## Acceptance
Tier 0 goldens owned by this child are exact: height→normal methods and strength scaling, normal blends, height goldens (MAT-05). Only the fitted formula, its public source and its residual are published under `parity/semantics/`; the goldens stay in the private oracle store and are compared on the self-hosted GPU runner (`docs/architecture/14-parity-testing.md` §6).

## Impact
- Affected specs: `compositor`
- Affected code: `src/evaluator/height.*`, `src/evaluator/height_to_normal.*`, `src/evaluator/normal_combine.*`, `src/evaluator/kernels/`, `parity/semantics/height-to-normal.json`, `tests/evaluator/`
- Breaking change: NO
- User benefit: Relief and normal maps match Painter and are never applied twice by downstream tools.
