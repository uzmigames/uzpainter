# 52. Iray's run-to-run difference is rounding-level except on facets with a zero normal component; the k*S render nests the S render

**Status**: accepted
**Date**: 2026-10-11
**Related Tasks**: phase0.8_render-reference-fits, phase0.7_render-reference-captures, phase3.6_path-tracer-tier3-report

## Context

Decision 046 left three points open: large run-to-run differences on `plane-mid-grey` and two cube goldens, Iray's sample sequence repeating across sessions, and a negative mean of S - K. Task phase0.8 measured on the admitted renders (`parity/reports/phase0/iray-noise-floor.md` §2):

- 19 goldens: 79-100% of the differing samples of (a) differ by exactly one binary16 step of the linear value, spatially white and zero-mean; a same-session repeat shows the same level.
- Face-confined: the decorrelated pixels are exactly the facets whose normal has an x component of exactly zero, the plane n = (0, 0.77, 0.64) (96.5% differ; rms(a)^2 / 2 rms(b)^2 = 0.126) and the cube's top face n = (0, 0.91, 0.42) in `cube-mid-grey` (86%) and `cube-saturated--ref-match-000` (90%). The five other visible cube faces stay at the rounding level, and so does the top face in `cube-saturated--ref-match-180` (0.1%).
- Nested: on all 13 noise-dominated goldens rms(S - K) matches sqrt(sigma_S^2 - sigma_K^2) from the high-pass noise, not sqrt(sigma_S^2 + sigma_K^2); sigma_K^2 / sigma_S^2 = 0.13 to 0.19.
- Jensen: the bias the concave encoding predicts for S - K has the observed sign on 13 of 13 goldens; observed / predicted 0.3 to 2.0, median about 1.3.

The model panel was consulted under the owner's delegation on 2026-10-11 (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5):

| Claim | Verdicts |
|---|---|
| D6 The face-confined difference is attributed, as a hypothesis, to a sampling frame that depends on the sign of an exactly-zero normal component; a capture request tests it | AGREE x2 (one "as a hypothesis"), PARTLY x1: alternatives remain; add a negative yaw and a symmetric versus asymmetric environment to test the mechanism, not only the trigger |
| D7 The S-render noise of decision 046 is the nested reading; bounds from (b) are not rescaled by 1/k | AGREE x1, PARTLY x2: record the ratio for this sample-count pair only, not as a convergence law |
| D8 The negative S - K is mainly Jensen's inequality; compare at equal S or subtract the prediction | PARTLY x3: "mainly" is not shown (ratio 0.3 lies outside a factor of two); report raw and adjusted with the prediction's uncertainty; equal S does not cancel the term when variances differ |

## Decision

1. **Rounding class.** Iray under the fixed pipeline is not bit-repeatable; outside the face-confined class its run-to-run difference is at the level of binary16 rounding of the linear result. The mechanism is not identified. (a) stays the oracle-stability result (07 §4).
2. **Face-confined class.** The hypothesis is recorded, not adopted as an explanation: a sampling frame chosen by the sign of an exactly-zero normal component makes renders draw mirrored sample sets, whose values differ where the environment is asymmetric about that mirror. Branching on a degenerate value or other state-dependent sampling remain alternatives. Until the capture request below returns, (a) of `plane-mid-grey`, `cube-mid-grey` and `cube-saturated--ref-match-000` is provisional and reported per face; it does not enter the floor, and a bound on those faces must respect it.
3. **Capture request** (coordinator; 18 references, about 45 minutes of Painter time; procedure `iray-capture/1`, S = 256): the plane and the cube turned by +1 and by -1 degree about +Y, two separate-session references each; `plane-mid-grey` twice more in separate sessions and twice in one session; `cube-saturated--ref-match-180` twice more; `plane-mid-grey` under `ref_match` at rotations 0 and 180, two each. The hypothesis predicts rounding-level (a) for every turned fixture.
4. **Nested samples.** The k*S render continues the S render's sample sequence. The S-render sigma is the nested reading with the high-pass sigma_S per golden, replacing the range of decision 046 item 7. The measured sigma_K^2 / sigma_S^2 (0.13 to 0.19) is recorded for this pair of sample counts only; bounds derived from (b) are never rescaled by 1/k.
5. **Bias.** Jensen's inequality on the encoding contributes to the negative S - K; it is not shown to be the whole bias. Bias tests of UzPainter against Iray report the comparison at equal S and the k*S comparison raw and with the predicted term subtracted, with the prediction's spread, and note that equal S does not cancel the term when the two renderers' variances differ.

## Alternatives Considered

- Fold the face-confined (a) into the floor now. Rejected: (b) already holds each S render's own noise, and the cause is testable with a short capture.
- Treat the nested reading as unproven and keep the range. Rejected: 13 of 13 noise-dominated goldens match the nested prediction.

## Consequences

Phase3.6 builds bounds from the nested (b) per region, the prototype's or the shipped tracer's (c), the per-face (a) of the three goldens, and both bias readings. The capture request goes to the coordinator; its result amends this decision.

## Amendment (2026-10-11, decision 062)

The capture request of item 3 was recorded by task `phase0.9_render-reference-capture`: 18 S renders, none refused, numbers in `parity/reports/phase0/iray-noise-floor.md` §9. Model panel on the results (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5): the trigger claim PARTLY x3 (necessary in the tested conditions, not sufficient); the mechanism claim AGREE x1, PARTLY x2 (the two-set model is contradicted; the redrawn share and "Monte-Carlo" are model statements); the environment claim AGREE x1, PARTLY x2; the floor claim PARTLY x3 (scope it to the measured conditions; no double counting; flag, then measure, other zero components).

1. **Trigger (item 2), confirmed in the tested conditions.** Turned by +-1 degree about +Y, the plane and the bevelled cube are at the rounding level on all 14 facets (0.1-4.4% of pixels differ, rms 0.2-1.2 codes); unturned, the plane facet differs on 83-98% of its pixels. An exactly-zero normal x component is necessary under rotation-0 environments; finer turns are untested.
2. **Mechanism (item 2), two mirrored sample sets contradicted.** Six S renders of `plane-mid-grey` (two admitted, two new sessions, two in one session and one project) give 15 decorrelated pairs and six classes, where two sample sets allow at most two. The component is redrawn by every render, also within one session. Under rms(a)^2 = 2 sigma_r^2, rms(a)^2 / (2 rms(b)^2) = 0.08-0.15 of the facet's per-render variance is redrawn. The mechanism is not identified.
3. **Environment.** The class depends on the environment's rotation: the plane under `ref_match` is decorrelated at rotation 0 and at the rounding level at 180, and `cube-saturated--ref-match-180` stays at the rounding level in four renders, although both facets keep an exactly-zero x component. Environment asymmetry about the x mirror or around the normal does not separate the two rotations. Recorded hypothesis, not adopted: the exact zero must survive into the frame in which the environment is sampled; rotation 0 is the identity, 180 degrees leaves sin(pi) != 0 in floating point. Predicted: rounding level at rotation 360 (void if Painter folds 360 to 0). Phase3.6 runs that test.
4. **Floor (replaces item 2's provisional status).** The per-face (a) of `plane-mid-grey`, `cube-mid-grey` and `cube-saturated--ref-match-000` is final as measured Iray variability, scoped to facets with an exactly-zero normal x component under rotation-0 environments. Phase3.6 combines it with (b) per region by an explicit rule that does not count the redrawn component twice, flags facets with exactly-zero normal components in production meshes as a risk indicator and measures a y-zero and a z-zero facet before a bound relies on them. UzPainter's tracer does not imitate the class.
