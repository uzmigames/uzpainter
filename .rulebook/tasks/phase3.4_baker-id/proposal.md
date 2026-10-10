# Proposal: phase3.4_baker-id

## Why
OWN-05 and BAK-03 (`docs/prd.md`) require all of Painter's mesh-map bakers; ID maps drive colour-selection masks and the material/ID leak checks of the paint gates. This child of P3-BAKER (`phase3.5_embree-bakers`) implements the `ID` usage of `docs/architecture/06-baking.md` §2 (D5).

## What Changes
- `ID` baker on the shared ray-cast core with `ColorSource` (Vertex Color, Material Color, File ID, Mesh ID/Polygroup) and `ColorGenerator` (Random, Hue shift, Grayscale); enum integers from Painter's `enum_values()` labels.
- Colour generation that reproduces Painter's assignment for each generator, established black-box against the Tier 2b goldens, with the effective palette recorded in the receipt.
- ID diagnostics in the comparison: exact label equality and edge coverage (`docs/architecture/14-parity-testing.md` §4).
- `ID` Tier 2b manifests under `parity/manifests/`.

## Dependencies
- Prerequisites: `phase3.3_baker-evidence-publication`.
- Parent: `phase3.5_embree-bakers`.

## Acceptance
Tier 2b for `ID`: hit/coverage evidence then maps equal the Painter CPU goldens on the analytic fixtures (plane, sphere, bevelled cube with highs) and the wand and hat low/high/cage pairs, for each `ColorSource` and `ColorGenerator` the fixtures exercise, across thread counts and ISAs; any difference passes only through an owner-approved exception.

## Impact
- Affected specs: baker
- Affected code: `ID` baker kernel, ID Tier 2b manifests, comparison-tool label diagnostics
- Breaking change: NO
- User benefit: Painter-equal ID maps for colour-selection masks
