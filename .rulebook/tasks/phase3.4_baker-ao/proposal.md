# Proposal: phase3.4_baker-ao

## Why
OWN-05 names AO as a required high-poly bake, BAK-03 requires Painter's settings, BAK-04 requires AO miss evidence from ray hits (a second wider pass SHOULD be offered) and BAK-08 requires one corrected AO per set to feed generators, delivery and albedo layers (`docs/prd.md`). This child of P3-BAKER (`phase3.5_embree-bakers`) implements the `AO` usage of `docs/architecture/06-baking.md` §2–§4 (D5).

## What Changes
- `AO` baker on the shared ray-cast core with the AO parameter group: `NbSecondary`, `MinDistance`, `MaxDistance`, `MaxDistanceRelativeScale`, `Spread`, `Distribution`, `IgnoreBackfaceSecondary`, `FilterMethodSecondary`, `Attenuation`, `GroundPlane`, `GroundOffset`, secondary rays drawn from the deterministic Hammersley sequence.
- AO miss reporting from hit evidence, distinct from real holes, hidden surfaces and low AO (BAK-04), written into the receipt's per-usage evidence.
- Optional documented second pass with wider distances applied only to missed texels (BAK-04 SHOULD), off by default, recorded in the receipt when used.
- `AO` Tier 2b manifests under `parity/manifests/`; the reference is Painter's CPU AO baker (Adobe records CPU/GPU AO differences), with the backend recorded in every golden.

## Dependencies
- Prerequisites: `phase3.3_baker-evidence-publication` (and through it `phase3.1_baker-request-model`).
- Parent: `phase3.5_embree-bakers`.

## Acceptance
Tier 2b for `AO`: hit/coverage evidence then maps equal the Painter CPU goldens on the analytic fixtures (plane, sphere, bevelled cube with highs) and the wand and hat low/high/cage pairs, across thread counts and ISAs; any difference passes only through an owner-approved exception.

## Impact
- Affected specs: baker
- Affected code: `AO` baker kernel, AO receipt evidence, AO Tier 2b manifests
- Breaking change: NO
- User benefit: Painter-equal AO with misses separated from genuine occlusion
