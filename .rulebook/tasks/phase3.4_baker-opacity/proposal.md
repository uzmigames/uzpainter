# Proposal: phase3.4_baker-opacity

## Why
OWN-05 and BAK-03 (`docs/prd.md`) require all of Painter's mesh-map bakers. This child of P3-BAKER (`phase3.5_embree-bakers`) implements the `Opacity` usage of `docs/architecture/06-baking.md` §2 (D5).

## What Changes
- `Opacity` baker on the shared ray-cast core with the common and detail parameters: the high-poly coverage/opacity value at the hit, encoded in the channel format the Tier 2b goldens establish.
- Opacity diagnostics in the comparison: exact alpha equality and edge coverage (`docs/architecture/14-parity-testing.md` §4).
- `Opacity` Tier 2b manifests under `parity/manifests/`.

## Dependencies
- Prerequisites: `phase3.3_baker-evidence-publication`.
- Parent: `phase3.5_embree-bakers`.

## Acceptance
Tier 2b for `Opacity`: hit/coverage evidence then maps equal the Painter CPU goldens on the analytic fixtures (plane, sphere, bevelled cube with highs) and the wand and hat low/high/cage pairs, across thread counts and ISAs; any difference passes only through an owner-approved exception.

## Impact
- Affected specs: baker
- Affected code: `Opacity` baker kernel, opacity Tier 2b manifests, comparison-tool alpha diagnostics
- Breaking change: NO
- User benefit: Painter-equal opacity maps baked natively
