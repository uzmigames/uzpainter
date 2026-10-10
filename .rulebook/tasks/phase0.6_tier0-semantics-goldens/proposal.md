# Proposal: phase0.6_tier0-semantics-goldens

## Why
The compositor reproduces Painter's layer-stack semantics, but most of what decides its outputs is undocumented: blend formulas and the space they operate in, where values are quantised, stack base values, mask precision, group semantics with masks, content-effect order, levels clamping, the `BilinearHQ` kernel, the height→normal methods and the `AO_Mixed` operator. `docs/architecture/04-layer-stack-and-compositing.md` §9 lists these as what Tier 0 must settle before the kernels are frozen, and under the clean-room policy the only permitted way to learn them is black-box observation of Painter's outputs through its documented API (`docs/licensing-and-clean-room.md` §1.2; decision 002). Exact equality (Q1, decision 017) needs every golden recorded at least twice so oracle stability can be measured (`14-parity-testing.md` §2). PRD G-04, LAY-01, LAY-04, LAY-05, LAY-10, ARC-04, CLR-01, CLR-05. Child of `phase0.8_tier0-goldens` (implements D3, D13).

## What Changes
- UzmiGames-authored synthetic meshes (plane, sphere, bevelled cube) with UVs and provenance, and independently authored bitmap inputs (16-bit gradients, height ramps, an AO mesh-map bitmap), described in the public manifest `parity/manifests/phase0/tier0-semantics.json`.
- UzmiGames-written instruction sequences (documented API only, run by the recorder of `phase0.3_painter-oracle-recorder`) and private goldens for the `04-…` §9 list:
  - blend modes: two uniform fills per documented `BlendingMode` member over value and opacity sweeps, on each channel storage format in use; asymmetric stacks confirming the bottom-up evaluation order (`04-…` §2);
  - quantisation points: the stack of three 1/3-opacity fills per channel format (`04-…` §4), plus uniform-colour ramps in each documented colour space for the sRGB transfer fit;
  - stack base values per template (empty-project export);
  - mask precision (8 vs 16 bit) with an authored 16-bit gradient mask;
  - group `Normal` and `PassThrough` with masks on the group and on children;
  - content-effect order (fill effect, levels and filter permutations);
  - levels clamp behaviour at and beyond the range ends;
  - `BilinearHQ` resampling of an authored bitmap source at non-1:1 scales;
  - height→normal: both project-setting methods over height ramps and a strength sweep;
  - `AO_Mixed`: the authored AO mesh map combined with an AO-channel sweep.
- Outputs exported through the documented `export_project_textures` at 16 bit (float where the channel is float), each golden recorded at least twice (same session; after save/reopen), records shaped by `parity/schema/golden-private.json`, admitted into the private store by `uzpainter parity record`; only hashes, inputs, instruction sequences, settings and software identities enter the public manifest.
- Excluded here and owned by the packages that name them: export padding/dithering/resize, quad triangulation, triplanar/planar/spherical/cylindrical projections, compare mask and colour selection (`14-…` §3 Tier 0 rows; `docs/dag.md` task decomposition rule).

## Dependencies
- Prerequisites: `phase0.3_painter-oracle-recorder` (P0-RECORDER), `phase0.5_private-oracle-store` (P0-STORE).
- Parent: `phase0.8_tier0-goldens` (P0-TIER0) closes only when this child passes.
- Successors: `phase0.7_tier0-stability-fits` (stability and fits computed from these goldens), `phase1.14_compositor-core` children (kernels tested against them).

## Acceptance
Every `04-…` §9 item has a golden set on the synthetic meshes, recorded at least twice through the documented API and exported at native 16-bit or float depth; blobs are in the private store and the public manifest holds only authored inputs, instruction sequences, settings, software identities and hashes; `uzpainter parity verify` passes. Contributes to the P0-TIER0 gate "each golden recorded ≥ 2×" (`docs/dag.md`) and G0 "Tier 0 goldens admitted (blobs private, hashes public)" (`docs/roadmap.md`).

## Impact
- Affected specs: tier0
- Affected code: `parity/manifests/phase0/tier0-semantics.json`, authored fixture meshes and bitmaps, recorder instruction sequences; private store contents
- Breaking change: NO
- User benefit: every undocumented compositing rule is observed on Painter's own outputs before a kernel depends on it
