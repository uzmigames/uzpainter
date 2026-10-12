# Proposal: phase1.14_compositor-core

## Why
The compositor turns the document into channel rasters and is the heart of output parity: Wand v1 (G1) and every later pilot are accepted on exact map equality with Painter. Requirements: LAY-01…LAY-05, LAY-09, LAY-10, LAY-13, LAY-14, MAT-05, PRJ-03, PRJ-05, EXP-09, NFR-02, NFR-03, ARC-04, CLR-01 (`docs/prd.md`). Implements D3 (decision 005: Painter-semantic document with a tile/channel evaluator and a measured quantisation profile) with owner answer Q1 (decision 017: exact equality, a divergence passes only through an owner-approved exception) in `docs/architecture/04-layer-stack-and-compositing.md`; formulas are written from public literature and fitted to Tier 0 goldens recorded through Painter's documented API (`docs/architecture/14-parity-testing.md` §2, §3; CLR-01, CLR-02; `docs/licensing-and-clean-room.md`). DAG node P1-COMPOSITOR (`docs/dag.md`), on the critical path of `docs/roadmap.md` Phase 1.

This is the parent integration and acceptance task. Per the `docs/dag.md` task decomposition rule it is split into seven children with their own artifacts, fixtures and prerequisite edges; each child names the Tier 0 tests it owns, so the Phase 1 subset is not asked to pass later-feature tests early.

## What Changes
Integration of the seven children (DAG Outputs of P1-COMPOSITOR) into the evaluator under `src/evaluator/` (kernels in `src/evaluator/kernels/`), tests in `tests/evaluator/`, fits in `parity/semantics/`:
- `phase1.5_compositor-tile-dag`: tile/channel DAG, cache, invalidation, memory admission, evaluation order, groups, stack base values, project templates, kernel generation.
- `phase1.8_compositor-sources-projection`: fills, uniform and bitmap sources, `Fill`/`UV` projections, sampling filters, colour transfer.
- `phase1.9_compositor-quantisation-profile`: the evaluator profile (quantisation points, precision, colour space of blending).
- `phase1.10_compositor-blend-kernels`: the 32 documented blend modes.
- `phase1.11_compositor-mask-effects`: masks, mask stacks, fill and levels effects, geometry masks, group masks.
- `phase1.12_compositor-height-normal`: height channel, height→normal, normal combination for the virtual normal maps.
- `phase1.13_compositor-diagnostics`: isolation, contribution, material views, region statistics.

Out of the Phase 1 subset, raising `NotYetSupported` and listed as release gaps in the capability manifest until their packages land: triplanar/planar/spherical/cylindrical projections and symmetry (P3-SMART), generator and filter effects and procedural sources (P3-PROC), compare mask, colour selection, anchors, instances, paint layers receiving bitmaps and projections, warp and UV-set-to-UV-set projections, vector and font sources (P4-NODES), the Sharpen filter (P4-HAT8), byte equality on Vulkan (P3-VULKAN).

## Dependencies
- DAG inputs: `phase1.4_render-core-layer` (P1-CORE), `phase1.3_document-model` (P1-DOCMODEL), `phase1.7_mesh-loader` (P1-MESH), `phase0.8_tier0-goldens` (P0-TIER0: private Tier 0 goldens and first fits).
- Children (all mandatory): `phase1.5_compositor-tile-dag`, `phase1.8_compositor-sources-projection`, `phase1.9_compositor-quantisation-profile`, `phase1.10_compositor-blend-kernels`, `phase1.11_compositor-mask-effects`, `phase1.12_compositor-height-normal`, `phase1.13_compositor-diagnostics`.
- Downstream: `phase1.18_export-engine` (P1-EXPORT).

## Acceptance
DAG gate of P1-COMPOSITOR: Tier 0 semantics exact for the implemented subset — every Tier 0 golden set owned by the seven children equals the private Painter goldens at the channel's storage precision in a local DX12 run on the owner's machine (decision 028; the local run report is the evidence), with no preset tolerance; a remaining difference passes only through an owner-approved entry in `parity/exceptions.json`. The parent closes only when all seven children are accepted.

## Impact
- Affected specs: `compositor`
- Affected code: `src/evaluator/`, `src/evaluator/kernels/`, `assets/templates/`, `parity/semantics/`, `tests/evaluator/`
- Breaking change: NO
- User benefit: A tile-based evaluator whose Phase 1 subset reproduces Painter's channel values exactly and records the evidence for each rule.
