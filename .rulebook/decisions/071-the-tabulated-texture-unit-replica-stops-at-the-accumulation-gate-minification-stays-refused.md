# 71. The tabulated texture-unit replica stops at the accumulation gate; minification stays refused

**Status**: accepted
**Date**: 2026-10-11
**Related Tasks**: phase1.9_compositor-resample-gaps

## Context

Decision 061 set the next step for bilinear minification: a tabulated software replica of the recording GPU's texture unit for axis-aligned footprints. Its gates come in order:

1. bound the domain;
2. prove the table keys sufficient;
3. resolve how the probes are summed;
4. validate sample for sample against the hardware before any golden.

If a gate fails, the work stops there. The tables would be pinned to the RTX 4090 and driver 617.14.

Everything below was measured on that GPU through Vulkan with `tools/parity/vk_sampler_probe` (synthetic textures only). `python -m tools.parity.vk_sampler_probe.replica_gates <work-dir>` reprints every count except the two marked "(session scratch)".

**Gate 1, the arithmetic around the probes (passes)**
- LOD lambda is fixed point in 1/256. The weight of the upper level is t = min(256, floor(7 f / 4)), with f the fraction of lambda. The lower level takes 256 - t.
- Each probe splits its weight w over four taps by rule F:
  - x1 = rhu(w fx / 256) and x0 = w - x1;
  - w11 = rhu(x1 fy / 256) and w01 = rhd(x0 fy / 256);
  - rhu and rhd round half up and half down.
- One isotropic probe at 33 LOD fractions, both levels, every one of the 65 536 sub-texel phases: 4 325 376 tap weights, 0 differing.
- A clamped lambda (below 0) uses the probe geometry of f = 0. An isotropic footprint whose major axis has lambda <= 0 is a single bilinear probe.
- Clamp-to-edge clamps the fixed-point probe coordinate, not the tap index. This is observed at the edges; the evaluator would need it for RepeatNone.

**Gate 2, the table keys (passes, as tested)**
- Two-level kernels, 300 random footprints per bias, six levels each:
  - changing the gradient bits below the 9-bit mantissas changes 0 of 1 800 kernels at bias 0 and 0 of 1 800 at -1.5;
  - swapping the roles of ddx and ddy (rotation 90) changes 0 of 1 800 at both biases.
- Flipping the sign of the major-axis gradient changes 82 and 56 kernels. The sign is therefore a table dimension: it moves the two-probe offset by one 1/128 step.
- Shifting both gradient exponents by one shifts the kernel one level: 600 of 600 kernels identical (session scratch).
- The geometry of a level is a set of symmetric probe pairs (offset p; weights wl and wr in 1/256, 1/512 or 1/1024). A decoder recovers it uniquely from 256-phase sweeps of the column weights.
- The geometry is a function of (rho, f, sign), with rho = lambda_major - lambda and lambda_major the LOD of the major axis alone:
  - 200 cells, two different keys each at bias 0: 0 differ;
  - 200 cells, one key at bias 0 and another at bias -1.5: 0 differ.
  - The sign changes 116 of 200 cells.
- The tables would be keyed on:
  - lambda over (major mantissa, minor mantissa, exponent difference 0-2), about 786 000 entries;
  - the geometry over (rho 0-512, f 0-255, sign).

**Gate 3, the accumulation (fails)**
- Each probe works like decision 043's bilinear: E is the exponent of its largest texel of non-zero weight, the operands are floor(t 2^(28 - E)), and their weighted sum is an exact integer.
- With one probe per level (two levels, texels spread over 24 octaves), the exact sum rounded ties-up matches 400 000 of 400 000 samples.
- With two probes (texels with 3-bit mantissas), every exactly representable sum matches: 126 817 of 126 817.
- But sums that need rounding miss 3 of 193 183, one float32 ulp low. The misses grow with the exponent spread inside a footprint (probe sets decoded per footprint, five footprints):

| Texture | Samples | Misses |
|---|---|---|
| Uniform 16-bit codes | 150 000 | 0 |
| Log-uniform dark 8-bit codes | 150 000 | 2 |
| Log-uniform dark 16-bit codes | 150 000 | 51 |

- Every miss lies 0 to 1/16 ulp above a rounding midpoint and is rounded down.
- A dial experiment steps one operand unit of probe B across a float32 tie. Probe A is the probe with the larger E.
  - The hardware sum is exactly the exact sum in 559 cases.
  - It is one or more units of A's last bit lower in 54 cases, all with A's integer sum odd.
  - But 210 odd cases show no deficit.
- No rule tested fits every dataset:
  - truncating each probe to the coarsest probe's last bit or one bit above (exact on an 84 672-sample motif, wrong elsewhere; session scratch);
  - floating accumulators of 24 to 40 bits, sequential in either order;
  - each probe rounded to 24-40 bits (truncation, ties-up, ties-even);
  - guard-bit final rounding with either tie rule;
  - exponent alignment per pair or per level;
  - alternative exponent choices per probe.
- A one-ulp float32 error can move a 16-bit code across a write boundary. A replica built now would therefore differ from Painter on ordinary dark bitmaps.

Model panel under the owner's delegation (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5, 2026-10-11):

| Claim | Verdicts |
|---|---|
| C1: gate 3 fails; no replica now, the refusal stays, items 2.2-2.4, 3.1, 3.2, 4.1 stay open | AGREE x2, PARTLY x1. The rates describe the tested distributions; no 16-bit code crossing was demonstrated. |
| C2: record gates 1-2 as established, with gate 2's cross-bias part still untested | AGREE x1, PARTLY x1, DISAGREE x1. Record measured results with their sample sizes, not universal facts. Do the cross-bias check before recording gate 2 (bias -1.5 is Sharp). It was then done: 0 of 200 cells differ. |
| C3: no exception-register entry, no approximate mode | AGREE x3 |
| C4: next, a focused measurement of the multi-probe accumulator, not table acquisition; afterwards, if still unresolved, put a domain restriction or a permanent refusal to the owner | AGREE x2, PARTLY x1. A restricted domain needs portable admission criteria. Hardware may be used only when the replica is qualified, never at run time. |
| C5: the validation goldens of decision 078 stay unused until a replica exists | AGREE x3 |

## Decision

1. **Gate 3 fails.** The tabulated replica is not built. How the texture unit combines several probes has an unresolved sub-ulp truncation, so no replica can be exact.
   - The evaluator keeps refusing bilinear minification with `evaluator:unsupported_source`.
   - Items 2.2-2.4, 3.1, 3.2 and 4.1 of phase1.9 stay open.
   - No exception-register entry and no approximate mode is proposed.
2. **Gates 1 and 2 are recorded as measured, with the sample sizes above.** They are not proven over the whole key space. The tables are pinned to the RTX 4090 and driver 617.14 and are not acquired before gate 3 passes.
3. **Next step: measure the multi-probe accumulator.** This means designed dial experiments over the probe count, the weight unit (1/512 against 1/1024), the exponent gap and the parity of each probe's sum. It is measurement on the recording GPU; no Painter recording is needed.
   - If that still yields no consistent rule, the owner chooses between two options:
     - a domain restriction with portable admission criteria, qualified against the hardware offline, never at run time;
     - keeping the refusal permanently.
4. **The validation goldens stay untouched until a replica exists:** `resample-uv-anisotropic`, `-anisotropic-impulse`, `-lod`, `-lod-boundaries` and `-rotation` (decision 078). They are validation data, not fitting data.
5. **The evidence is `replica_gates.py`.** It is print-only and uses synthetic inputs, like `texture_unit.py`.
   - `uv-sampling.json` `uv-bilinear-minification` stays a gap and cites this decision.
   - It was re-derived byte for byte (`test_published_fits_reproduce`).

## Alternatives Considered

- **Build the tables and the replica anyway, exact on uniform textures.** Rejected: a measured 51 of 150 000 one-ulp misses on dark 16-bit bitmaps breaks exact equality, and the refusal exists so that such cases are not approximated.
- **Restrict the replica to 8-bit bitmaps.** Rejected: dark 8-bit bitmaps also miss (2 of 150 000).
- **Keep searching the accumulator in this task without a stop.** Rejected: the families tested here are exhausted. The next search needs designed experiments of its own.

## Consequences

- Scaled bitmap fills that minify stay refused.
- The measurements and the decoder carry over, so a later attempt starts at gate 3.
- The owner should know that the replica's last missing piece is a sub-ulp rounding detail of the hardware. It affects about 3 in 10 000 samples of very dark bitmaps and none of uniform ones.
