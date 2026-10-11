# 68. The qualification sphere's template-default material is read back under OCIO and its term (c) is measured; item 3.2 closes

**Status**: accepted
**Date**: 2026-10-11
**Related Tasks**: phase0.9_render-reference-capture, phase3.5_path-tracer-materials, phase3.6_path-tracer-tier3-report

## Context

Decision 063 held item 3.2 of `phase0.9_render-reference-capture` ("the noise-floor report covers every analytic fixture with an admitted reference") open until the template-default material of an OCIO project was read back as a hashed private record in one Painter session and the feasibility prototype's term (c) was measured on the qualification sphere as `iray-noise-floor.md` §3 does for the other 22 fixtures. Item 4.1 (the gate) also waits for the owner's signature of `parity/reports/phase0/gate-p3-pathtracer-entry.md`.

Measured on 2026-10-11 (Painter `12.1.5+js-api.1.1.20`, one session started with `OCIO` naming Painter's `resources/ocio/substance/config.ocio`, documented API only, under the Assets3D Painter lock):

- Golden `phase0/template-default-material/ocio-sphere`: the authored sphere created as the qualification job creates it (`project.create` with the mesh only), no layer, the template's five channels exported (PNG 16 for the 8-bit channels, OpenEXR 32f for the 16-bit float ones), r1 and r2 (after save and reopen) byte-identical on all five maps; private record `f6ac6f70c43d0df1d0051ad16e7a6805ce4f98b1143852c7b113b9d3f4faa2bb`, 12 private records (the record, five maps per recording with identical blobs, the environment record), `store verify` ok. The recorder refuses a manifest that names `OCIO` unless the session's colour management is that configuration.
- Template capture: BaseColor sRGB8, BaseMetalness L8, SpecularRoughness L8, Normal RGB16F, Height L16F; texture set 1024 px.
- Uniform values: BaseColor 59396/65535 on every channel (sRGB-encoded) = the encoding of linear 0.799986, the sRGB of 0.8, not on the sRGB8 lattice (code 231 exports 59367); the Legacy recording `tier0/semantics/base-values-default` reads 59397. BaseMetalness 0. SpecularRoughness 19532 = L8 code 76. Normal (127/255, 127/255, 1). Height 0. The shader instance was read back under OCIO the same day (`iray-references.md` §5).
- Term (c) on the sphere (`python -m tools.parity.render_fits qualification`, the fits' chosen lobes, environment scale 1.0192 and bump strength unchanged; crop origin (599, 599)): interior mean |delta| 402.1 codes (p99 1 532, mean signed -15.36 +- 2.93) at seed 1 and 511.2 at seed 2, against Iray's (b) of 139.9; edge 196.5 against 170.1; background 0.

Model panel under the owner's delegation (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5, 2026-10-11):

| Claim | Verdicts |
|---|---|
| Q1 The read-back meets decision 063's first condition | AGREE x3 |
| Q2 Scene: BaseColor the export's linear value, metalness 0, roughness 76/255, interpolated normal, no bump | PARTLY x3: state the empty-Normal convention explicitly (127/255 decodes to a 0.32-degree tilt); record that Iray's input (0.8 or code 231) is not observed; one rule for stored values |
| Q3 Item 3.2 is met | AGREE x3 (coverage of the floor, not material fidelity) |
| Q4 Report (c)/(b) = 2.9 and an 8-fold sample need | PARTLY x3: report the ratio descriptively with both seeds; no sample-cost projection (heavy tails, seed spread, a ~5-sigma S-K bias) |
| Q5 4.1 stays open; the record reads "ready for signature" | AGREE x2, PARTLY x1: "evidence complete; owner signature pending", after a clause-by-clause check |

## Decision

1. **Read-back.** The template-default material of an OCIO project is the record above; it is the material of `tier3/render-procedure/qualification-sphere`. Its numbers are public, its exports private.
2. **Prototype scene** (`render_fits.fixtures.QUALIFICATION`). Each channel takes the value the export shows, at the precision Painter stores it: BaseColor the export's linear 0.799986 (the empty stack is not on the sRGB8 lattice), metalness L8 code 0, roughness L8 code 76 (76/255). The empty Normal channel (127/255, 127/255, 1), which every fixture shares, is read as flat: the prototype keeps the interpolated normal, the convention of phase0.8's fits for all 22 fixtures. Height 0 adds no bump. Not observable from Phase 0 and handed to phase3.5: whether Iray shades with 0.8 or with the sRGB8 code 231 (about 0.1% linear), and whether it tilts the normal by the decoded 127/255. Neither enters (c), which compares the prototype with itself.
3. **Item 3.2 is met.** The noise-floor table of `iray-noise-floor.md` §3 holds (a), (b) and (c) for all 23 admitted analytic fixtures. The sphere's (c)/(b) of 2.9 (seed 1; 3.7 at seed 2) is reported as measured, above the 1.3-2 of the other dielectrics; no sample-cost projection is drawn from it. The prototype is never Tier 3 evidence; phase3.6 measures the shipped tracer's (c).
4. **Item 4.1 stays open.** The gate record is rewritten clause by clause to "evidence complete; owner signature pending". The task is not archived until the owner signs (decision 063, point 3).

## Alternatives Considered

- Quantise the read-back BaseColor to sRGB8 code 231 like the authored fixtures (rejected: the export shows the empty stack off the lattice).
- Measure (c) at three to five seeds before closing (not adopted: the claim made is coverage with the same statistics as the other fixtures, which use seed 1; the second seed is reported).

## Consequences

`tools/parity/render_fits` gains the `qualification` command and the qualification fixture; `tools/parity/render_procedure/references.py` generates the read-back manifest; the texture recorder checks the `OCIO` a manifest names. The owner's remaining action on P0-FEAS-RENDER is the signature.
