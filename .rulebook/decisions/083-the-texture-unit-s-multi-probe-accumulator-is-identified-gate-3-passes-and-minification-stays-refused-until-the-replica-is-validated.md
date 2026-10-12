# 83. The texture unit's multi-probe accumulator is identified; gate 3 passes and minification stays refused until the replica is validated

**Status**: accepted
**Date**: 2026-10-11
**Related Tasks**: phase1.9_compositor-resample-gaps

## Context

Decision 071 stopped the tabulated texture-unit replica at gate 3: summing the probes of a sample exactly and rounding once to float32 left one-ulp-low misses (51 of 150 000 on dark 16-bit bitmaps). The misses lay just above a rounding midpoint, and a dial experiment showed a deficit only when the larger-exponent probe's integer sum was odd, but not in every such case. Item 3 of decision 071 asked for designed measurements of the multi-probe accumulator.

Everything below was measured on the RTX 4090 with driver 617.14 through Vulkan, with `tools/parity/vk_sampler_probe` on synthetic textures only. `python -m tools.parity.vk_sampler_probe.replica_gates <work-dir> 3` reprints every count (about 8 minutes).

**The rule.** A probe is one bilinear footprint of the anisotropic kernel on one mip level. Each probe is as in decision 071:
- E is the binary exponent of its largest texel of non-zero weight, so that t lies in [2^(E-1), 2^E);
- S is the sum of w floor(t 2^(28 - E)) over its taps, with the tap weights w in 1/1024;
- its value is S 2^(E - 38).

The probes are then summed as follows:
1. Let coarse(E) = E - ((E + 126) mod 4). This is E lowered until the biased float32 exponent E + 126 is a multiple of 4.
2. Each probe enters truncated toward zero to a multiple of 2^(coarse(E) - 36).
3. **Order.** The lower mip level comes first. Within a level, the probes go by offset along the major-axis gradient: ascending for a positive gradient, descending for a negative one.
4. **Pairs.** The probes of a level form consecutive pairs. Before each addition after the first, the running sum is truncated to a multiple of 2^(coarse(G) - 36). G is the largest E over every probe of every pair up to and including the incoming probe's pair. A pair's second probe therefore already counts when its first probe is added.
5. The decoder's "pair at offset 0" is one probe of the pair's weight: one truncation and a group of its own.
6. The sum is rounded to the nearest float32, ties up.

A probe whose texels are all 0 adds nothing and keeps its place in the order. Within the domain every texel is 0 or at least 2^-18: 8- and 16-bit codes and their mip means. So E + 126 is positive, and no subnormal or overflow occurs.

**The fit.** Every count below is exact.

| Data | Samples | Exact sum (decision 071) | Accumulator |
|---|---|---|---|
| Decision 071's datasets, same seeds: one probe per level | 400 000 | 400 000 | 400 000 |
| two probes, 3-bit mantissas | 320 000 | 319 997 | 320 000 |
| uniform 16-bit codes | 150 000 | 150 000 | 150 000 |
| dark 16-bit codes | 150 000 | 149 949 | 150 000 |
| dark 8-bit codes | 150 000 | 149 998 | 150 000 |
| Decision 071's dial: steps of 613 cases | 58 848 | 559 cases with the exact sum | 58 848 (every case) |
| 23 footprints the rule was found on | 1 840 000 | 0 to 329 misses each | 1 840 000 |
| 10 held-out footprints and seeds | 800 000 | 0 to 225 misses each | 800 000 |

- The 23 footprints have 2 to 8 probes: four per level for ratios above 2, both levels, both gradient signs, both axes, ddx and ddy swapped, and biases from -8 to 0.5. The texels are wide-exponent: 24-bit mantissas over 24 octaves.
- The held-out footprints add five texture families: wide-exponent, dark 16-bit, dark 8-bit, uniform 16-bit with 20 % zeros and 10 % ones, and 3-bit mantissas over 20 octaves.
- The rule explains the dial: the 54 late flips are the larger-exponent probe losing its low bit to its own grid. The 210 odd sums without a deficit are probes whose grid keeps that bit.
- Rejected on the same data:
  - a running maximum over single probes instead of pairs (8 to 45 misses per footprint);
  - a per-level maximum (3 to 33) and a global maximum;
  - summing each pair before accumulating, and per-level accumulators combined at the end (121 to 832);
  - grids one to four bits finer or coarser (39 to 207).

Model panel under the owner's delegation (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5, 2026-10-11):

| Claim | Verdicts |
|---|---|
| C1: gate 3 passes; the rule is the accumulation on this GPU and driver within the tested domain | PARTLY x3. Record it as a behavioural model matched with these counts in a stated domain, not as the circuit. Define the all-zero probe and the exponent range. Adopted above. |
| C2: the rule is behavioural (grids, order, pairs); no claim about the hardware's structure | AGREE x3 |
| C3: next, gate 4: tables, replica, validation sample for sample against the hardware before any golden; the refusal stays until then | AGREE x1, PARTLY x2. The table keys stay hypotheses that gate 4 must falsify. Fix the validation matrix: boundaries, both signs and axes, zero texels, the offset-0 probe, LOD clamps. |
| C4: no exception entry or approximate mode; tables pinned to the RTX 4090 and driver 617.14 | AGREE x1, PARTLY x2. Pin the sampler state as well: maxAnisotropy 4, linear filter and mip mode, float32 texture, Vulkan. A mismatch must refuse. |

## Decision

1. **Gate 3 passes.** The accumulator above is recorded as the measured behaviour of the texture unit's multi-probe sum, within the domain described above. The domain is non-negative texels of 0 or at least 2^-18, at most four probes per level, two levels, RTX 4090 with driver 617.14, and the sampler state of decision 060. It is a behavioural model fitted and held out with the counts above. It is not a description of the circuit.
2. **Next is gate 4.** The steps are, in order:
   1. Acquire the LOD table over the 9-bit mantissa pair and exponent difference. Acquire the probe geometry over (rho, f, sign), with an offset-0 pair stored as one probe.
   2. Build the replica.
   3. Validate it sample for sample against the hardware before any recorded golden. The validation covers random inputs, LOD and anisotropy boundaries, the LOD clamps, both signs and axes, zero texels and the offset-0 probe.
   The table keys stay hypotheses until that validation is exact.
3. **The refusal stays.** The evaluator keeps refusing bilinear minification (`evaluator:unsupported_source`) until gate 4 is exact. No exception-register entry and no approximate mode is proposed. The tables are pinned to the recording GPU, its driver and the sampler state.
4. **The evidence is `replica_gates.py`.** Its gate-3 sections print the exact-sum and the accumulator counts side by side. `uv-sampling.json` `uv-bilinear-minification` stays a gap and cites this decision.

## Alternatives Considered

- **Keep the exact sum and propose an exception for the misses.** Rejected: an exact rule exists and fits every sample.
- **Fit a wider floating accumulator.** Rejected: decision 071 tried 24 to 40 bits in both orders. The truncation grid follows the exponent in steps of four, not the width of a register.

## Consequences

- The last open piece of decision 071's accumulation is closed. A replica can now be exact if its tables are.
- The replica must sort each level's probes by the sign of the major-axis gradient and group them in pairs, so the geometry tables keep the probe order.
