# 169. Every shipped template base is observed and exported exactly; the PNG of an L8 material channel is refused

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase1.25_pilot-wand

## Context

Decision 168 made five shipped template bases `observed`. It left 21 `inferred` and refused, and requested one `export-template-base-<template>` golden for each. Decision 172 admitted all 21 under the envelope `painter-12.1.5_js-api.1.1.20`. Every one is stable (`r1 = r2`, every same-session repeat identical). In each OpenEXR 32f file every texel holds the candidate for that template's code class, bit for bit:

- `float32(127/255)` on 16 BaseColor templates;
- `float32(0.8)` on OpenPBR - Fuzz and OpenPBR - Subsurface Scattering;
- `float32(10/255)` on the Specular of Maxwell, Non-PBR and VrayMtl Specular Glossiness.

Before each entry was changed, its template value was checked against the decoded file.

Dota 2 also exports Specular, which its template stores as L8. Its OpenEXR 32f file holds `float32(10/255)` in R, G and B. Its PNG 16 holds `(14330, 2570, 14330)` on every texel. Our template entry held `(0.2186618, 10/255, 0.2186618)`, the float32 values whose UNORM writes are those codes.

The export reads an L8 channel through its first component. Measured against the new golden before this change, it wrote:

- OpenEXR 32f: `0.2186618` in every component, where Painter writes `10/255`;
- PNG 16: `14330` in every component, where Painter writes `(14330, 2570, 14330)`.

0 of 8 comparisons were identical (steps 2-5, r1 and r2). The export was wrong in both formats, and nothing refused it.

Painter's PNG puts the sRGB encode of `10/255` (14330) in R and B, and its linear write (2570) in G. One empty channel does not explain that rule. Fitting it would need recordings of a non-empty L8 Specular, and of L8 BaseColor or Emissive. The coordinator's brief settled what to do: refuse what is not exact and record the measured state. The model panel was not consulted.

## Decision

1. **The 21 bases are `observed`** (`assets/templates/*.json`). Each `base_provenance` names its `export-template-base-<template>` golden, its golden-record hash and its map. It keeps `export16`, the base-values code that the sRGB export encode of the value writes. No value changed. No shipped entry is `inferred` now.
2. **Dota 2's L8 Specular base is `float32(10/255)` in all three components** and `observed`, from `export-template-base-dota-2`. Its OpenEXR export is exact.
3. **The PNG of an L8 BaseColor, Specular or Emissive is refused before writing** (`CheckProcessing` in `src/export/encode.cpp`). It raises `NotYetSupported`, naming this decision and the golden. The only shipped case is Dota 2's Specular. The refusal applies at PNG 8 too, which no recording shows.
4. **The `inferred` guard stays** (`RequireIdentifiedBase`, decision 126). It now protects any future entry authored from a PNG code alone. Its tests use a copy of the templates in which Blender's BaseColor is marked `inferred`.
5. **Capabilities.** The context `srgb8-inferred-template-base` is replaced by `l8-material-channel-png` in both packages. Its conformance case exports Dota 2's Specular at PNG 16, and the refusal must name decision 169.
6. **Tests.**
   - `test_observed_template_bases_equal_painter_files` covers all 24 `export-template-base-*` goldens (25 maps) at OpenEXR 32f and PNG 16, plus the three float virtual-map twins (decision 168).
     - 104 files written: 25 x 4 - 2 + 6.
     - 208 of 208 comparisons byte-identical with r1 and r2.
     - Dota 2's two Specular PNG 16 files are refused.
   - The Dota 2 diagnostics test now expects every BaseColor view.
   - `test_base_values_equal_the_empty_project_exports` no longer compares the PNG of an L8 material channel.

## Consequences

- `phase1.25_pilot-wand` item 2.6 is exact end to end. The PNG 16 encode and the linear read-out of every template constant match Painter's files, so the item is checked.
- Dota 2's Specular PNG export is a release gap. Its owner is the export encoder owner. Settling it needs a recording of a non-empty L8 Specular (and BaseColor or Emissive set to L8) at PNG 8 and PNG 16.
