# 51. The first Iray lobe fits are published `calibrated` with no lobe reproduced; depth, caustics and spectral transport stay unidentified

**Status**: accepted
**Date**: 2026-10-11
**Related Tasks**: phase0.8_render-reference-fits, phase3.4_path-tracer-transport, phase3.5_path-tracer-materials

## Context

Task phase0.8_render-reference-fits fitted the feasibility prototype (decision 050) black-box against the 22 admitted fixture goldens of decision 046: 800 metal x dielectric combinations, chosen on one chessboard half of 16 x 16 pixel blocks by the RMS of 64 x 64 block means against the k*S render, residuals reported on the other half and on held-out goldens (`parity/reports/phase0/iray-noise-floor.md` §4-§6). Measured:

- Metal: GGX, alpha = roughness^2, height-correlated Smith, Schlick F0 = base colour. Single scattering leaves the roughness-0.9 metal 1.8x too dark (linear), Kulla-Conty or Turquin compensation 1.25x; an albedo-based multiple-scattering lobe tinted by F0 (MDL `multiscatter_tint`) brings every roughness within about 0.3%. Held-out residuals +4 to +37 codes (+190 on the mirror sphere).
- Dielectric: Schlick F0 0.04 (IOR 1.5), Lambert, layering (1 - E_s(mu_o))(1 - E_s(mu_i)) without renormalisation, multiple-scattering lobe tinted by 0.04. Held-out residuals -510 to +573 codes; the saturated sphere's specular-dominated channels too bright; the ref_match grey sphere -346 at 0 degrees, +220 at 180.
- Environment orientation fitted on the mirror sphere; one global intensity scale 1.0192 (exposure 0). Box pixel filter; bump strength 0.5.
- Iray's block standard errors of S - K are 0.2 to 1 code in interiors: every fit lies far outside the floor.
- Spectral sensitivity of the prototype (Jakob-Hanika upsampling, Wyman colour-matching fit): -1 / -113 / -29 codes on the saturated sphere under Studio White Soft (+580 -> +532); the ref_match HDRI is achromatic.
- With below-facet directions absorbed, depth 1 and depth 8 are bit-identical on every golden tested; letting them pass through the surface moves normal ridges by +7.5 codes mean. No caustic path exists on one convex object without ground.
- Defects (256 x 256 crops, 256 samples): environment +90 degrees, missing normal map, roughness +0.2 and Burley without layering each shift the interior mean signed delta by 109 to 1793 codes against combined standard errors of 0.7 to 1.5; the missing normal map is inside in the edge band.

The model panel was consulted under the owner's delegation on 2026-10-11 (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5):

| Claim | Verdicts |
|---|---|
| D1 Publish all ten entries `calibrated` with held-out residuals; dielectric and view-dependent residuals go to phase3.5 | AGREE x1, PARTLY x2: put "no lobe reproduced" in the file's header, keep the residuals inline, say the support is unequal and that environment or geometry errors are alternatives to lobe errors |
| D2 The environment scale 1.0192 is a nuisance constant, not Painter's intensity; P3 re-fits | AGREE x3 |
| D3 No evidence for spectral transport; RGB stays; reported as the prototype's sensitivity | AGREE x2, PARTLY x1: it does not prove every spectral model renders the same |
| D4 Depth and caustics not identifiable; authored depth and a documented below-facet rule for P3 | AGREE x3 |
| D5 Item 3.2 satisfied | PARTLY x3: the detector grades shifts against a misfit baseline; say so, and re-derive thresholds once the lobes close |
| D9 Acceptance 4.1 can be checked | PARTLY x3: as a deliverable checklist with explicit non-reproduction and the open items kept |

Overall: GPT "conditional Phase-0 closure, not a validated Iray match"; Kimi "accept with conditions"; Grok "partly accept; publish calibrated with the non-reproduction note".

## Decision

1. `parity/semantics/iray.json` holds ten `calibrated` entries (display encoding, environment mapping, camera and pixel filter, channel quantisation, metal lobe, dielectric lobe, normal and bump, ignored channels, held-out geometry and ref_match, transport), each with approved public sources, its constants and its residuals inline against k*S and both S renders. Its description states that no lobe is reproduced, that a residual may come from the lobes, the environment handling or the geometry, and that the support is unequal (display encoding and environment orientation tight, metal close, dielectric, bump and filter first guesses).
2. The environment scale 1.0192 is recorded as a fitted nuisance constant. Phase 3 does not adopt it; it re-fits after any change of material, environment or encoding.
3. Transport stays RGB. The spectral comparison is reported as the prototype's sensitivity under one upsampling, not evidence about Iray.
4. The maximum path depth and caustic paths are not identifiable on the fixed pipeline's fixtures. Phase 3 (phase3.4) keeps the maximum depth an authored constant and the below-facet rule (absorb) a documented choice, to be tested on references with concavity, interreflection or caustics.
5. Defect detection (item 3.2) is reported as satisfied for these four defects with the caveat that the baseline is the misfit model; it shows sensitivity, not false-positive rates, and its thresholds are re-derived when the lobe residuals close.
6. The dielectric lobe structure and the view-dependent diffuse residual are open questions owned by phase3.5; they do not block this Phase-0 task, whose acceptance is the deliverable checklist of decision 050 with the non-reproduction stated.

## Alternatives Considered

- Mark the metal entry `exact` or the fits `gap`. Rejected: no residual is zero, and a gap would hide a usable first model.
- Hold the task open until the dielectric is reproduced. Rejected: lobe calibration of the shipped tracer is phase3.5's scope, and Phase 0 owes first fits with residuals.
- Adopt spectral transport for safety. Rejected: no evidence asks for it, and it costs every pixel.

## Consequences

Phase3.5 starts from the published entries and their residuals; phase3.4 from an authored maximum depth and the absorb rule. A change of the Assets3D standard, of an environment hash or of Painter's default shader re-opens the fits.
