# Proposal: phase3.2_baker-normal

## Why
OWN-05 and BAK-03 (`docs/prd.md`) require a detailed tangent-space normal bake from the high-poly mesh like Painter's, and PRJ-04 fixes the OpenGL (+Y) convention with a MikkTSpace per-fragment frame validated by the Phase 0 fixture. This child of P3-BAKER (`phase3.5_embree-bakers`) implements the `Normal` usage of `docs/architecture/06-baking.md` §2–§3 (D5).

## What Changes
- `Normal` baker on the shared ray-cast core: tangent space from the texturing mesh's MikkTSpace frame with the project's `TangentSpace` mode; output convention per `NormalMapFormat` (`06-baking.md` §3), using the convention settled by the normal-convention fixture (`14-parity-testing.md` §2).
- Normal-specific diagnostics in the Tier 2b comparison (`14-parity-testing.md` §4): angular max/mean, non-finite and unnormalised counts; a low normal Z is reported as an inspection signal and never used to replace values (BAK-07).
- Tier 2b manifests for the `Normal` usage under `parity/manifests/` (fixture descriptions and hashes of the private Painter CPU goldens).

## Dependencies
- Prerequisites: `phase3.1_baker-request-model`; `phase0.9_normal-convention-fixture` (already accepted upstream of `phase2.10_pilot-tunic-recovery`, re-used here).
- Parent: `phase3.5_embree-bakers`. Unblocks `phase3.3_baker-evidence-publication` (first usage published with receipts) and `phase3.4_baker-curvature` (`FromNormalMap`).

## Acceptance
Tier 2b for `Normal`: hit/coverage evidence then maps equal the Painter CPU goldens on the analytic fixtures (plane, sphere, bevelled cube with highs) and the wand and hat low/high/cage pairs, across thread counts and ISAs; any difference passes only through an owner-approved exception (`06-baking.md` §7).

## Impact
- Affected specs: baker
- Affected code: `Normal` baker kernel on the ray-cast core, normal Tier 2b manifests
- Breaking change: NO
- User benefit: Painter-equal detailed normal maps baked natively
