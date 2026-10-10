# Proposal: phase3.4_baker-position

## Why
OWN-05 and BAK-03 (`docs/prd.md`) require all of Painter's mesh-map bakers; the position map feeds the Position and Dirt generators (`docs/architecture/05-procedural-content.md` §3) and BAK-02 requires its normalisation to be recorded, never silently rescaled. This child of P3-BAKER (`phase3.5_embree-bakers`) implements the `Position` usage of `docs/architecture/06-baking.md` §2 (D5).

## What Changes
- `Position` baker on the shared ray-cast core with `Mode`, `Axis`, `Normalization` and `NormalizationScale`; enum integers from Painter's `enum_values()` labels.
- Effective normalisation (bounds and scale actually applied) recorded in `baked.effective_normalization` and the receipt; distances in the project unit rule (`docs/architecture/12-mesh-import.md` §3).
- `Position` Tier 2b manifests under `parity/manifests/`.

## Dependencies
- Prerequisites: `phase3.3_baker-evidence-publication`.
- Parent: `phase3.5_embree-bakers`.

## Acceptance
Tier 2b for `Position`: hit/coverage evidence then maps equal the Painter CPU goldens on the analytic fixtures (plane, sphere, bevelled cube with highs) and the wand and hat low/high/cage pairs, for each `Mode`/`Axis`/`Normalization` the fixtures exercise, across thread counts and ISAs; any difference passes only through an owner-approved exception.

## Impact
- Affected specs: baker
- Affected code: `Position` baker kernel, position Tier 2b manifests
- Breaking change: NO
- User benefit: Painter-equal position maps with recorded normalisation
