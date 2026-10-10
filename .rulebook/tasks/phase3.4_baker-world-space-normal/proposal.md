# Proposal: phase3.4_baker-world-space-normal

## Why
OWN-05 and BAK-03 (`docs/prd.md`) require all of Painter's mesh-map bakers, and the world-space normal map is an input of the mesh-map generators (`docs/architecture/05-procedural-content.md` §3). This child of P3-BAKER (`phase3.5_embree-bakers`) implements the `WorldSpaceNormal` usage of `docs/architecture/06-baking.md` §2 (D5).

## What Changes
- `WorldSpaceNormal` baker on the shared ray-cast core with the common and detail parameters (`06-baking.md` §2): the high-poly normal at the hit in the project's object/world frame, encoded in the channel format and value mapping the Tier 2b goldens establish.
- Normal diagnostics in the comparison (angular max/mean, non-finite and unnormalised counts).
- `WorldSpaceNormal` Tier 2b manifests under `parity/manifests/`.

## Dependencies
- Prerequisites: `phase3.3_baker-evidence-publication`.
- Parent: `phase3.5_embree-bakers`.

## Acceptance
Tier 2b for `WorldSpaceNormal`: hit/coverage evidence then maps equal the Painter CPU goldens on the analytic fixtures (plane, sphere, bevelled cube with highs) and the wand and hat low/high/cage pairs, across thread counts and ISAs; any difference passes only through an owner-approved exception.

## Impact
- Affected specs: baker
- Affected code: `WorldSpaceNormal` baker kernel, WSN Tier 2b manifests
- Breaking change: NO
- User benefit: native world-space normal maps for generators and export
