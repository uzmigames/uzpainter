# Proposal: phase1.11_compositor-mask-effects

## Why
The approved paint standard relies on layer masks (background, bitmap fill effect, levels, subtraction), mask opacity and blend, ordered typed effects, group masks and a defined base under complementary masks (LAY-03, LAY-04, LAY-10, G-02). Implements D3 (decision 005: Painter-semantic document with a tile/channel evaluator and a measured quantisation profile) with owner answer Q1 (decision 017: exact equality, a divergence passes only through an owner-approved exception) in `docs/architecture/04-layer-stack-and-compositing.md`; formulas are written from public literature and fitted to Tier 0 goldens recorded through Painter's documented API (`docs/architecture/14-parity-testing.md` §2, §3; CLR-01, CLR-02; `docs/licensing-and-clean-room.md`). Child of `phase1.14_compositor-core` (P1-COMPOSITOR), covering `docs/architecture/04-layer-stack-and-compositing.md` §1 (mask and effect model) and §2 (steps 2, 4, 5); named in the `docs/dag.md` decomposition rule.

## What Changes
- `src/evaluator/mask.{h,cpp}`: mask stacks, mono-channel: `m := background (Black 0 | White 1)`; effects in order, each with its own mode and opacity; disabled mask counts as 1; mask opacity and blend; mask precision (8 vs 16 bit) as settled by Tier 0.
- `src/evaluator/effects.{h,cpp}`: content effects in list order on the layer's own content: fill effect (source blended with its own per-channel mode/opacity) and levels (`LevelsParams`, clamp behaviour from Tier 0); in mask stacks: bitmap fill effect, levels, subtraction through the blend modes.
- Geometry mask of type `Mesh` (inclusion list by object/material) multiplying the mask; `UVTile` geometry masks are a release gap.
- Group masks: groups with an optional mask; per-group Height blend override and the effective Height blend readable (LAY-03).
- Fit: `parity/semantics/masks-levels.json`.
- Excluded (release gaps until their packages): compare mask, colour selection, anchors (P4-NODES), generator and filter effects (P3-PROC), Sharpen (P4-HAT8).

## Dependencies
- DAG inputs of the parent: `phase0.8_tier0-goldens` (mask goldens), `phase1.3_document-model`.
- Sibling prerequisites: `phase1.10_compositor-blend-kernels`, `phase1.8_compositor-sources-projection`.
- Parent: `phase1.14_compositor-core`.

## Acceptance
Tier 0 goldens owned by this child are exact: mask goldens (background, fill effect, levels, subtract), levels clamp behaviour, content-effect order, group `Normal`/`PassThrough` semantics with masks, mask precision, base value under complementary masks (LAY-10). Only the fitted formula, its public source and its residual are published under `parity/semantics/`; the goldens stay in the private oracle store and are compared locally on the owner's machine (decision 028; `docs/architecture/14-parity-testing.md` §6); the local run report is the evidence and hosted CI skips these tests with an explicit reason.

## Impact
- Affected specs: `compositor`
- Affected code: `src/evaluator/mask.*`, `src/evaluator/effects.*`, `src/evaluator/kernels/`, `parity/semantics/masks-levels.json`, `tests/evaluator/`
- Breaking change: NO
- User benefit: Masked fills and grouped materials — the structure of every pilot stack — evaluate exactly, with no unintended default bleed.
