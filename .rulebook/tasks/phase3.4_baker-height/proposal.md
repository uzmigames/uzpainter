# Proposal: phase3.4_baker-height

## Why
OWN-05 and BAK-03 (`docs/prd.md`) require all of Painter's mesh-map bakers, and BAK-02 requires recorded effective normalisation for generator inputs. This child of P3-BAKER (`phase3.5_embree-bakers`) implements the `Height` usage of `docs/architecture/06-baking.md` §2 (D5).

## What Changes
- `Height` baker on the shared ray-cast core: signed low-to-high distance along the cast ray with `NbSecondary`, the distance parameters, `Spread`, `Distribution`, `MaximizeRange` and `Divisor`, sampled from the deterministic Hammersley sequence; distances in the project unit rule (`docs/architecture/12-mesh-import.md` §3).
- Effective range and divisor recorded in `baked.effective_normalization` and the receipt.
- `Height` Tier 2b manifests under `parity/manifests/`.

## Dependencies
- Prerequisites: `phase3.3_baker-evidence-publication`.
- Parent: `phase3.5_embree-bakers`.

## Acceptance
Tier 2b for `Height`: hit/coverage evidence then maps equal the Painter CPU goldens on the analytic fixtures (plane, sphere, bevelled cube with highs) and the wand and hat low/high/cage pairs, across thread counts and ISAs; any difference passes only through an owner-approved exception.

## Impact
- Affected specs: baker
- Affected code: `Height` baker kernel, height Tier 2b manifests
- Breaking change: NO
- User benefit: Painter-equal baked height with recorded units and range
