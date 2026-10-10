# Proposal: phase3.4_baker-thickness

## Why
OWN-05 and BAK-03 (`docs/prd.md`) require all of Painter's mesh-map bakers; the thickness map is an input of the mesh-map generators (`docs/architecture/05-procedural-content.md` §3). This child of P3-BAKER (`phase3.5_embree-bakers`) implements the `Thickness` usage of `docs/architecture/06-baking.md` §2 (D5).

## What Changes
- `Thickness` baker on the shared ray-cast core: secondary rays cast inward with `NbSecondary`, the distance parameters, `Spread`, `Distribution` and `MaximizeRange`, sampled from the deterministic Hammersley sequence.
- Effective range applied by `MaximizeRange` recorded in `baked.effective_normalization` and the receipt.
- `Thickness` Tier 2b manifests under `parity/manifests/`.

## Dependencies
- Prerequisites: `phase3.3_baker-evidence-publication`.
- Parent: `phase3.5_embree-bakers`.

## Acceptance
Tier 2b for `Thickness`: hit/coverage evidence then maps equal the Painter CPU goldens on the analytic fixtures (plane, sphere, bevelled cube with highs) and the wand and hat low/high/cage pairs, across thread counts and ISAs; any difference passes only through an owner-approved exception.

## Impact
- Affected specs: baker
- Affected code: `Thickness` baker kernel, thickness Tier 2b manifests
- Breaking change: NO
- User benefit: Painter-equal thickness maps for generators
