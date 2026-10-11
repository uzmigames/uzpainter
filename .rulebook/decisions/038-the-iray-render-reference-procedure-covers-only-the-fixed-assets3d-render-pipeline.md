# 38. The Iray render reference procedure covers only the fixed Assets3D render pipeline

**Status**: accepted
**Date**: 2026-10-11
**Related Tasks**: phase0.6_render-reference-procedure

## Context

Owner, 2026-10-11 (verbatim): "nao tem a necessidade do uzpainter ter todas as configuracoes de render do substance, nossa pipe de render e sempre fixa" (UzPainter does not need all of Painter's render settings; our render pipeline is always fixed). The fixed pipeline is the Assets3D render comparison standard, `E:\UzmiGames\Assets3D\Pipeline\render\Render-Comparison-Standard.json` (SHA-256 `2ec4281f7a1414c836eb59aec4fa895db0706c2fc9c4e19433325939a6525be5` on 2026-10-11), summarised in `docs/analysis/assets3d-pipeline/06-review-render-standard.md` §2. Task phase0.6_render-reference-procedure was written to answer every "not confirmed" Iray and display setting of `docs/architecture/07-preview-and-render-parity.md` §2.1, including open-ended sweeps (colour LUT placement, Viewer/MDL settings, Caustic Sampler and resolution-override variability).

## Decision

The render reference procedure covers only the fixed pipeline: (a) the v2 common standard (top-level block: Studio White Soft interpreted Linear, infinite sphere, no ground, shadows off, clear colour on, exposure 0, rotation 0, environment opacity 0, blur 0, Default - sRGB display transform with colour management on, no post effects, LUT, colour profile or display SSS, firefly filter and caustic sampler off, 1200x1200 with override resolution on, Iray min = max = 256 samples, max time 3600 s); (b) the `presets.ref_match` v3 preset (session-resource HDRI, shadows on, clear colour sRGB8 141,142,148, envRotation per view); (c) the `base_color` diagnostic view with the display transform on. Every other Iray or display setting is pinned to the standard's value or to Painter's default and is not a supported variable. Presentation snapshots (`Grimorio-Presentation.json`, `Studio-Presentation.json`, `Painter-Lighting-*.json`) are out of scope. Probes cover only what the fixed pipeline needs: that each standard value can be applied and verified; readiness; Save Render against the external 1:1 fallback in that configuration; seed repeatability and the denoiser state, which set the noise floor; bump or displacement for the height usage the standard prescribes. Rows of 07 §2.1 that only an open-ended sweep would answer are recorded `not required - fixed pipeline (decision 038)` with the pinned value.

## Alternatives Considered

- Answer every Painter render setting (rejected by the owner: the pipeline is fixed, and UzPainter does not need to reproduce settings the pipeline never uses)

## Consequences

The phase0.6 probe drops the LUT, post-effect, tone-mapping, MDL-parameter and persistence sweeps; each pinned value is re-applied and read back on every capture instead of relying on persistence. A change of the Assets3D standard (new version or hash) re-opens the procedure qualification. Other documents and tasks that assume full render-settings support must be re-scoped separately.
