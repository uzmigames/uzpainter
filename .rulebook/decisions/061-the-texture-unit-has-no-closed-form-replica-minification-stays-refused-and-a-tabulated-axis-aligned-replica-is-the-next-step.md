# 61. The texture unit has no closed-form replica; minification stays refused, and a tabulated axis-aligned replica is the next step

**Status**: accepted
**Date**: 2026-10-11
**Related Tasks**: phase1.9_compositor-resample-gaps

## Context

Decision 060 identified exactly the part of Painter's minification that runs outside the texture unit. The evaluator may not sample through a GPU's sampler (decision 043), so lifting the refusal needs a bit-exact software model of the recording GPU's anisotropic texture unit (RTX 4090, driver 617.14, Vulkan, maxAnisotropy 4). Decision 056 required measuring it with designed inputs and setting a stop point in case it resisted a bit-exact model.

`tools/parity/vk_sampler_probe/texture_unit.py` reprints the following from synthetic textures only (impulses, coordinate ramps, random texels).

**Coordinates and inputs**
- The texel coordinate is X = floor(256 (u W - 1/2) + 1/2), exactly from the float32 u: 0 differences on 300 000 adversarial u, with |u| < 12 and W up to 4 096.
- The gradient lengths enter as 9-bit truncated mantissas. On 20 000 pairs, the two ends of each 1/512 bin give identical outputs. The 141 steps of the anisotropic LOD over p in [1, 2) all fall on the 1/512 grid.

**Probe count and placement** (r = major / minor, in units of the selected level)
- The probe count is 2 for r in (1, 2] and 4 for r in (2, 4]. Above 4 it is clamped: r = 5, 8 and 12 give the kernel of r = 4.
- For r in (1, 2], two probes sit at +-d. d is a multiple of 1/128 texel: about 1 - 1/r, with irregular one-step deviations. Isotropic footprints give d > 0 for some mantissas, which is the "two probes at 1.2825" of decision 056.
- For r in (2, 4], the probes sit at +-1/2 and +-3/2, weighted by their coverage of [-r/2, r/2] in units of 1/512. For example, at r = 2.25 the inner probes weigh 227 and the outer ones 29, split 14 and 15 over the outer taps.
- Each probe splits its weight over its taps. On 1 920 probes decoded from four-probe kernels, the x split is round-half-up(w fx / 256), and the y split rounds half up in the far column and half down in the near one. Equal-weight probes (r = 4) instead tie to even, which suggests the probe weights carry more than 9 bits internally.
- The probe offsets follow the trilinear position. With a 2.8 x 1.4 footprint at LOD 0.49, the level-1 offset is 0.447 level-1 texels, not 0.5.
- The switch to plain magnification depends on the major axis.

**Arithmetic**
- With the measured per-texel weights (multiples of 2^-17), the decision-043 rule reproduces 6 911 of 6 912 level-0 multi-probe samples in `texture_unit.py`, and 108 790 of 108 864 in a wider set that includes LOD-biased footprints. The rest are one ulp off.

**Rotated footprints**
- The decoded two-probe offsets of a 1.5 x 1 footprint at 10, 30, 45 and 60 degrees are (90, 20), (76, 48), (46, 46) and (48, 76) / 256. Along the true axis they would be (84.7, 14.9), (74.5, 43.0), (60.8, 60.8) and (43.0, 74.5). The 2-D length and direction path has its own approximations, over four float inputs.

**The two-probe offset is not closed-form**
- Over all 131 328 pairs of 9-bit mantissas (one octave), d is monotone in the minor axis but has 8 834 reversals along the major one.
- Linear-programming feasibility (scipy HiGHS) rejects d = G(F(a) + P(b)) for any monotone G and P and any F, which covers every separable and log-domain form.
- It also rejects d = G(log2(a - b) + F(a)), and a floor of an affine function of b for each a.

Model panel under the owner's delegation (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5, 2026-10-11):

| Claim | Verdicts |
|---|---|
| The stop point is reached; the refusal stays; the items stay open; the one-code divergence is not adopted | PARTLY x2, DISAGREE x1. All three keep the refusal and the open items. The objection is to "not achievable": the LP rejects the tested families, not tabulation. The input space is finite, so a table is a bit-exact model. Read it as "the closed-form search stops; no exact model in this task", not as an absolute stop. |
| The next step is a separate task: a tabulated replica for axis-aligned footprints and Painter's two biases, with rotated minification still refused and no exception entry now | AGREE x2, PARTLY x1. Gate it on four things. (a) Show that the table keys are sufficient: the discarded bits must not matter anywhere in the domain. (b) Bound the domain explicitly. (c) Resolve the multi-probe accumulation before acquiring the tables. (d) Validate sample for sample against the hardware: boundary and adversarial cases plus random gradients, with CPU = GPU = hardware, before the goldens. Pin the device and the driver; re-qualify after an update. "Exactness reachable" is a hypothesis. |
| Commit the measurement code as evidence | AGREE x2, PARTLY x1: the scripts regenerate their claims from measurements, and the LP construction is part of them. |

## Decision

1. **The stop point of decision 056 is reached for a closed-form model.** No bit-exact software texture unit was produced in this task. The search for formulas stops. This does not claim that no exact model exists: a measured table is one, and the input space is finite.
2. **The refusal stays.** The evaluator keeps refusing bilinear minification with `evaluator:unsupported_source`.
   - The one-code model is not adopted, and no exception-register entry is proposed: unsupported cases are refused, not approximated.
   - Items 2.2-2.4, 3.1, 3.2 and 4.1 of phase1.9 stay open.
   - `uv-sampling.json` `uv-bilinear-minification` stays a gap and states decisions 060 and 061.
3. **The next step is a follow-up task: a tabulated texture-unit replica for axis-aligned footprints** (rotation a multiple of 90 degrees, so the per-pixel derivatives are exactly axis-aligned), for Painter's two biases (-1.5 Sharp, 0 HQ). Its gates, in order:
   1. Bound the domain: texture sizes, mip counts, gradient ranges, octave and anisotropy boundaries, the magnification switch, mip clamps and wraps.
   2. Show that the table keys suffice, by varying the omitted inputs independently: the 9-bit mantissas, the octave difference, the LOD and the bias.
   3. Resolve the multi-probe accumulation and the per-tap split (the weights' internal precision) before acquiring full tables, or stop again.
   4. Measure the tables: the two-probe offset, the four-probe weights, the LOD and trilinear fraction, and the level-dependent offsets.
   5. Validate sample for sample against the hardware on boundary, adversarial and random inputs, with the CPU reference = the GPU kernel = the hardware, before testing the goldens.
   6. Enable only the validated subset.
   - The tables are pinned to the RTX 4090 and driver 617.14; a driver update re-qualifies them through the probe.
   - Rotated minification stays refused, so `resample-uv-minify` user 7 stays a gap even if the follow-up succeeds. The owner is told now.
4. **The evidence is `texture_unit.py`:** print-only, synthetic inputs, regenerating every number above, including the LP construction.

## Alternatives Considered

- **Keep searching for a formula in this task.** Rejected: the LP results exclude the natural families, and the remaining datapath (approximate reciprocals, internal weight precision, 2-D direction) is open-ended.
- **Propose an exception-register entry for the one-code model.** Rejected: the evaluator refuses instead of returning approximate pixels, and an exact model is still reachable by tabulation.
- **Sample through the GPU's sampler.** Rejected by decision 043.

## Consequences

- Scaled bitmap fills that minify stay refused.
- The follow-up task needs the coordinator to open it. The probe and both scripts are its starting point.
- A Painter recording is needed only to validate a replica beyond the current captures: anisotropic HQ, LOD at or above 1, and rotations (decision 056).
