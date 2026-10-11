# Proposal: phase1.9_compositor-quantisation-profile

## Why
Exact equality depends on quantising at the same points as Painter and blending sRGB8 channels in the same space; the result is the evaluator profile, stored in every project and golden and versioned so old projects re-evaluate with the evaluator they were authored with (ARC-04, PRJ-05, NFR-02, NFR-08). Implements D3 (decision 005: Painter-semantic document with a tile/channel evaluator and a measured quantisation profile) with owner answer Q1 (decision 017: exact equality, a divergence passes only through an owner-approved exception) in `docs/architecture/04-layer-stack-and-compositing.md`; formulas are written from public literature and fitted to Tier 0 goldens recorded through Painter's documented API (`docs/architecture/14-parity-testing.md` §2, §3; CLR-01, CLR-02; `docs/licensing-and-clean-room.md`). Child of `phase1.14_compositor-core` (P1-COMPOSITOR), covering `docs/architecture/04-layer-stack-and-compositing.md` §4.

## What Changes
- `src/evaluator/profile.{h,cpp}`: evaluator profile `painter-12.1-<profile-id>`: fp32 intermediates (integer only where the storage format is integer and the operation exactly representable; FP16 never a substitute for `L16`/`RGB16`), accumulator quantisation to the `ChannelFormat` at the points Painter quantises, encoded-vs-linear blending for sRGB8, no fast-math.
- The Tier 0 experiment (a stack of three 1/3-opacity fills; exact vs per-layer-quantised models; encoded vs linear sRGB8) decides the profile; its fit and residual go to `parity/semantics/quantisation-profile.json`.
- Profile registry: the profile id is written into every project (`versions.evaluator_profile`) and golden; a later profile needs a new id and a migration that keeps the old evaluator available.

## Dependencies
- DAG inputs of the parent: `phase0.8_tier0-goldens` (quantisation goldens), `phase1.3_document-model` (`evaluator_profile` field).
- Sibling prerequisites: `phase1.5_compositor-tile-dag`, `phase1.8_compositor-sources-projection` (uniform fills used by the experiment).
- Parent: `phase1.14_compositor-core`. Consumers: every kernel child.

## Acceptance
Tier 0 quantisation goldens exact for every channel format the templates use, with the chosen profile recorded; a project stamped with a profile re-evaluates with that profile.

## Impact
- Affected specs: `compositor`
- Affected code: `src/evaluator/profile.*`, `parity/semantics/quantisation-profile.json`, `tests/evaluator/`
- Breaking change: NO
- User benefit: Stacked opacities and sRGB blends round exactly as in Painter, and old projects never change output when the evaluator evolves.
