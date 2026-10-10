# Proposal: phase3.4_baker-bent-normals

## Why
OWN-05 and BAK-03 (`docs/prd.md`) require all of Painter's mesh-map bakers. This child of P3-BAKER (`phase3.5_embree-bakers`) implements the `BentNormals` usage of `docs/architecture/06-baking.md` §2 (D5), which shares the AO/BentNormals parameter group.

## What Changes
- `BentNormals` baker on the shared ray-cast core: the mean unoccluded direction over secondary rays with `NbSecondary`, `MinDistance`, `MaxDistance`, `MaxDistanceRelativeScale`, `Spread`, `Distribution`, `IgnoreBackfaceSecondary` and `FilterMethodSecondary`, sampled from the deterministic Hammersley sequence; output frame and encoding as the Tier 2b goldens establish.
- Normal diagnostics in the comparison (angular max/mean, non-finite and unnormalised counts).
- `BentNormals` Tier 2b manifests under `parity/manifests/`.

## Dependencies
- Prerequisites: `phase3.3_baker-evidence-publication`.
- Parent: `phase3.5_embree-bakers`.

## Acceptance
Tier 2b for `BentNormals`: hit/coverage evidence then maps equal the Painter CPU goldens on the analytic fixtures (plane, sphere, bevelled cube with highs) and the wand and hat low/high/cage pairs, across thread counts and ISAs; any difference passes only through an owner-approved exception.

## Impact
- Affected specs: baker
- Affected code: `BentNormals` baker kernel, bent-normal Tier 2b manifests
- Breaking change: NO
- User benefit: Painter-equal bent normals baked natively
