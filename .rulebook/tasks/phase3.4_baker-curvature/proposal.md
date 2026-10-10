# Proposal: phase3.4_baker-curvature

## Why
OWN-05 and BAK-03 (`docs/prd.md`) require Painter's curvature bake, and BAK-02 requires generator mesh maps with recorded algorithm, source role and effective normalisation, never silently auto-rescaled. Curvature feeds the edge-wear and cavity generators (`docs/architecture/05-procedural-content.md` §3). This child of P3-BAKER (`phase3.5_embree-bakers`) implements the `Curvature` usage of `docs/architecture/06-baking.md` §2–§3 (D5).

## What Changes
- `Curvature` baker with `CurvatureMethod` `FromMesh` (geometry sampled with `NbSecondary`, `SamplingRadius`, `MaxDistanceRelativeScale`) and `FromNormalMap` (from the baked `Normal` map).
- Normalisation: `AutoMinMax` computes bounds over the set, otherwise `TonemappingBounds`; the **effective** bounds are recorded in the binding (`baked.effective_normalization`) and in the receipt so a re-bake or a linked set can reuse them (`06-baking.md` §3).
- `Curvature` Tier 2b manifests under `parity/manifests/`.

## Dependencies
- Prerequisites: `phase3.3_baker-evidence-publication`, `phase3.2_baker-normal` (input of `FromNormalMap`).
- Parent: `phase3.5_embree-bakers`.

## Acceptance
Tier 2b for `Curvature`: hit/coverage evidence then maps equal the Painter CPU goldens on the analytic fixtures (plane, sphere, bevelled cube with highs) and the wand and hat low/high/cage pairs, for both methods, across thread counts and ISAs; the effective bounds are recorded and reused; any difference passes only through an owner-approved exception.

## Impact
- Affected specs: baker
- Affected code: `Curvature` baker kernels, binding `effective_normalization`, curvature Tier 2b manifests
- Breaking change: NO
- User benefit: Painter-equal curvature with traceable normalisation for re-bakes and linked sets
