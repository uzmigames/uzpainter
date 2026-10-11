# 50. The render fits run a CPU feasibility prototype on the fixed-pipeline references; term (c) is the prototype's

**Status**: accepted
**Date**: 2026-10-11
**Related Tasks**: phase0.8_render-reference-fits, phase0.7_render-reference-captures, phase3.6_path-tracer-tier3-report

## Context

Task phase0.8_render-reference-fits was written before decision 038. It asked for a feasibility prototype path tracer, a layered BSDF, the camera, environment and display transform "of the analytic profile (Legacy `Linear` tone mapping)", black-box lobe fits in `parity/semantics/iray.json`, transport evidence (spectral vs RGB, caustics, path depth), UzPainter's error at S (term c), a noise-floor report, and DXR / Vulkan ray-query probes. Its input, phase0.7_render-reference-captures (decision 046), admitted 22 fixture goldens plus the qualification sphere under the fixed pipeline: OCIO Default - sRGB, Save Render 16-bit PNG at 1200x1200, 256 samples, two separate-session S renders and one k*S render (k = 4) each, all single convex meshes under an infinite environment with no ground. The shipped GPU path tracer is Phase 3 (P3-PATHTRACER); phase3.6 item 2.3 already owns the noise measurement on it.

Measured for this decision on the admitted renders (private store, numbers only):
1. Display encoding. 95.65% of the interior RGB samples of the 66 fixture renders equal round(65535 encode(h)) for a binary16 value h, encode the IEC 61966-2-1 encoding; every other sample is within one 16-bit code of that lattice (the clear-colour background lies on it too).
2. Run-to-run (a), 19 goldens: about 90% of the differing samples differ by exactly one binary16 step, spatially white, zero-mean; a same-session repeat of phase0.6 showed the same count.
3. Run-to-run (a), three goldens: the difference is confined to whole up-facing flat faces (the tilted plane; the top face of the bevelled cube in `cube-mid-grey` and `cube-saturated--ref-match-000`, not in `cube-saturated--ref-match-180`), broad (up to 36 binary16 steps), zero-mean, white; its variance is about 11% of 2 sigma_S^2.
4. Nested sequence: on the grey diffuse sphere a high-pass estimate gives sigma_S = 157.7 and sigma_K = 59.1 codes; rms(S - K) = 143.3 matches the nested prediction 146.2, not the independent 168.4; sigma_K^2 / sigma_S^2 = 0.14 instead of 1/k = 0.25.
5. Bias: Jensen's inequality on the concave encoding predicts -0.068e-4 of full scale for S - K on the grey diffuse sphere; observed -0.07 +- 0.05e-4.

The model panel was consulted under the owner's delegation on 2026-10-11 (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5). Finding 1 was put to it as 99.29% on the lattice, a figure that counted the background; the interior figure is 95.65%. Verdicts per claim:

| Claim | Verdicts |
|---|---|
| C1 Reword every item to the fixed pipeline; 2.3 becomes the fitted display encoding, Legacy `Linear` dropped | AGREE x2, PARTLY x1: the float16 stage is a fitted model of the codes, not proof of Iray's internals |
| C2 The prototype is a CPU numpy program, not shipped, implementing the whole 07 §3.2 design; one vertex suffices on the fixtures | AGREE x2, PARTLY x1: test the loop (multiple bounces, MIS, roulette, sampler) beyond the fixtures; document below-facet handling |
| C3 Fit on the k*S references, interior only, residuals against K and both S, status `calibrated` or `gap`, public sources per entry | AGREE x1, PARTLY x2: choosing on the same pixels grades itself; use a hold-out and state the multiplicity |
| C4 Term (c) measured on the prototype and labelled so; a generic tool lets phase3.6 rerun it | AGREE x3 |
| C5 Finding 2 explained, finding 3 open with a capture request, (a) does not change the floor | AGREE x1, PARTLY x1, DISAGREE x1: finding 2 shows rounding-level non-repeatability, not its mechanism; report (a) per face and keep it in view for defect tests on those faces |
| C6 The negative S - K bias is the encoding's Jensen bias; compare at equal S or correct | AGREE x1, PARTLY x2: one fixture is one data point; keep it a hypothesis until per-fixture predictions match |
| C7 Spectral via the prototype; caustics and depth not identifiable, gap listed | AGREE x1, PARTLY x2: the spectral comparison bounds the prototype's sensitivity only, it says nothing about Iray |
| C8 FLIP 1.7 pinned by wheel hash, diagnostic only | AGREE x3 |
| C9 A fresh `selftest` run records the probes, cross-checked against 2026-10-10 | AGREE x2, PARTLY x1: record the feature bits and the raw results, not only extension names |
| C10 4.1 can close with the open items listed with owners | PARTLY x3: make the bar explicit and write the per-face caveat into the acceptance text |

Overall: GPT "approve the re-scope, reject acceptance as justified then"; Kimi "approve with conditions"; Grok "partly accept".

## Decision

1. **Re-scope.** Every item of phase0.8 is reworded to the fixed pipeline (decisions 038, 042, 046); none is deleted. Legacy `Linear` is dropped from item 2.3.
2. **Prototype.** `tools/parity/render_fits/` is a CPU feasibility prototype written from the 07 §3.1 sources (Kajiya 1986, Veach 1997, PBRT 4th ed., Burley 2020, Walter 2007, Heitz 2014/2018, Schlick 1994, Burley 2012, OpenPBR, the MDL specification; Kulla and Conty 2017, Turquin 2019, Wyman et al. 2013 and Jakob and Hanika 2019 added to the approved-source index for variants and the spectral check). It is never shipped and never Tier 3 evidence. The path loop with NEE, MIS and Russian roulette is tested on a concave bowl, where one vertex loses energy and the loop restores the furnace. A direction below the facet is absorbed; a facet's empty side (no mesh vertex beyond its plane) lets rays escape exactly.
3. **Display encoding.** The fixed pipeline's encoding is fitted as code = round(65535 encode(binary16(L))), an empirical model of the observed codes, `calibrated` with its lattice statistics.
4. **Fits.** Variants are chosen on one chessboard half of 16 x 16 pixel blocks, by the RMS of 64 x 64 block means against the k*S render; residuals are reported on the other half and on held-out goldens (the perturbations, the negative controls, the plane, the cube and all `ref_match` goldens). The candidate count is reported with the ranking. One global environment scale is fitted. Every entry of `parity/semantics/iray.json` is `calibrated` with residuals against k*S and both S renders.
5. **Term (c).** It is measured on the prototype (seeds 1 and 2 at 256 samples against its own 1024-sample render that nests seed 1) on a 256 x 256 crop per golden holding interior, edge and background, with the statistics of (a) and (b). The report says it is the prototype's. Phase3.6 item 2.3 measures `painter_iray`'s (c) with the same statistics; no blocker moves to a lower task.
6. **Run-to-run.** Finding 2 is reported as non-repeatability at the binary16 rounding level (mechanism not identified). Finding 3 is reported per face, stays open, and goes to the coordinator as a capture request. The defect tests on those goldens state the per-face (a).
7. **Bias.** The Jensen prediction is reported per golden and region beside the observed S - K, as a hypothesis graded by that comparison.
8. **Transport evidence.** The spectral comparison is the prototype's sensitivity, not evidence about Iray. Caustics and the maximum path depth are reported as not identifiable on these fixtures, with the measured below-facet and depth differences; P3 must not infer them from Phase 0.
9. **FLIP** `flip-evaluator` 1.7, wheel SHA-256 `2081f715ea8190a5f58bc578b0cccd36a9a3f3cf78ad13fe6f86e5a75615bda7`, owner's machine only, diagnostic.
10. **Probes.** A fresh `UzPainter.exe selftest` on the owner's machine records the DXR tier, the shader model, inline ray-query support, the three Vulkan extensions and the `accelerationStructure` and `rayQuery` features with adapter and driver.
11. **Acceptance.** Item 4.1 is checked when (a), (b) and the prototype's (c) are in the report, the fits are published with held-out residuals, the probes are recorded, and the open items are named with their owners (the coordinator's captures for finding 3; phase3.6 for the shipped tracer's (c)).

## Alternatives Considered

- Wait for P3-PATHTRACER to measure (c) and fit lobes. Rejected: the task's own text asks for a feasibility prototype, and Phase 3 should start from fitted, sourced lobes.
- Select variants on all pixels. Rejected (panel): the selection would grade itself.
- Treat (a) of the three face-confined goldens as part of the floor. Not adopted: (b) holds each S render's own noise; (a) is reported per face instead, and its cause is captured first.

## Consequences

Phase0.8 items 2.1-2.8, 3.1-3.3 and 4.1 are reworded. The approved-source index gains P-KULLA, P-TURQUIN, P-WYMAN and P-JAKOB, and the dependency inventory pins `flip-evaluator`. A change of the Assets3D standard, of an environment hash or of Painter's default shader re-opens the fits.
