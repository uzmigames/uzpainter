# 73. The component modes' float32 hue is identified on the hue grid, and Tint, Saturation, Color and Value are exact

**Status**: accepted
**Date**: 2026-10-11
**Related Tasks**: phase1.11_compositor-blend-gaps

## Context

`phase1.11_compositor-blend-gaps` fitted the hue law of Tint, Saturation, Color and Value in double precision. The smallest component selects a centre C (blue 1, red 3, green 5; ties: red first, then green before blue). With p and q the other two components (g and r, b and g, r and b), d = max - min and e = 2^-12, the law is:

h6 = C + (p - q - 3e) / (d + e)

Its float32 form left one-code residuals on `blend-component`:

- up to 194 RGB16 values per map;
- 8 228 to 20 122 RGB32F values per map.

So the four modes stayed release gaps (compositor-blend-gaps.md §3).

Decision 067 recorded the requested golden `tier0/semantics/blend-component-hue`: a 16-bit hue grid in five texture sets on eight channels, r1 = r2 on all 40 maps. On s0 (Tint of the grid over the uniform colour (0.5, 0, 0)), the RGB32F channel gives the hue weights at amplitude 1, readable to about 2^-24.

The old float32 form left 43 375 of its 196 608 values off. The measurements that identified the arithmetic (CPU reference and numpy emulation; scratch tooling only):

- **The weights are centred on the primaries.** The low bits of the recorded weights depend on the hue range:
  - in hue sector [3, 4), all 5 179 weights in [0.5, 1) are odd multiples of 2^-24;
  - in [4, 6) every weight is a multiple of 2^-23.

  The hexcone form 2 - |6h - 2| can only give multiples of 2^-23 there. The form 2 - 6 |h - float32(1/3)| gives odd multiples, because float32(1/3) = 11 184 811 x 2^-25. The weights are therefore taken as:
  - red fma(6, |h - 1/2|, -1);
  - green fma(-6, |h - float32(1/3)|, 2);
  - blue fma(-6, |h - float32(2/3)|, 2).

  With these weights and the old hue, 43 values remain off, all in the random validation cases. The hexcone form, and the centred form without the fused multiply-add, leave 33 144 and 20 251 texels with no admissible hue at all.
- **The numerator is p - (q + 3e).** The orders (p - q) - 3e and (p - 3e) - q leave 43 and 40 values off. A hue computed in turns (h = fma(., rcp(6 (d + e)), C/6) and variants) leaves about 20 000 off.
- **A hue that wraps to exactly 1 is not reduced.** A hue just below 0 moved up by one turn rounds to 1.0. If it were reduced to 0, 52 values would be off: there the blue weight is 2 - 6 |1 - float32(2/3)| = 2^-23, not 0.
- **Reciprocal argument.** (max - min) + e and max - (min - e) both give 0 values off, and they are equal on every hue source of both goldens. (max + e) - min leaves 5 values off.

The model panel was consulted under the owner's delegation (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5):

| Claim | Verdicts |
|---|---|
| C1 Adopt the float32 hue; report the four modes exact; lift their release-gap notes | AGREE x1, PARTLY x2: state the result as equality with every recorded map within the recording profile, not as a proof over all inputs. The held-out golden validates the float32 refinement; the double-precision law was fitted on it earlier |
| C2 Keep (max - min) + e; record the ambiguity; no new recording now | AGREE x1, PARTLY x2: state precisely where the two forms can differ. One model asks for a cheap distinguishing recording |
| C3 Scope to the recording profile; no new evaluator profile | AGREE x1, PARTLY x2: pin the GPU, driver and Vulkan path in the scope, and give regression evidence that the modes already exact are unchanged |
| C4 "Centred on the primaries" with measured provenance is clean-room compliant | AGREE x3: describe it as a model equivalent on the observations, not as Painter's source |

## Decision

1. **The float32 hue.** `arith::Hue` and `HueWeights`, and the HLSL `Hue` and `HueWeights` (GPU = CPU bit for bit), compute:
   - h6 = fma(p - (q + 3e), rcp(d + e), C), with the hardware reciprocal;
   - h = h6 float32(1/6), plus 1 when negative, and 1.0 is kept;
   - the weights centred on the primaries, each clamped to [0, 1].

   The rest of the component kernel is unchanged: the saturation, the doubled value and the reconstruction fma(v - lo, w, lo).
2. **Tint, Saturation, Color and Value are exact.** Every map of `blend-component-hue` s0-s4 and the held-out `blend-component` s0-s3 equals both recordings on the CPU and on the GPU: 72 maps x 2 recordings, on every channel format.
   - `parity/semantics/blend-kernels.json` is re-derived with both goldens: every entry is `exact`.
   - The four release-gap notes leave the capability inventory.
   - `test_compositor_blend_kernels.py` has no release gaps left.
3. **Scope.** Like the other hardware-dependent fits (decisions 053 and 056), the result describes the recording profile: Painter 12.1.5 on the RTX 4090, driver 617.14, through Vulkan.
   - The modes already exact are unchanged: `blend-kernels.json` re-derived with every other entry still exact, `kernel-sweep` and `gpu-vs-cpu`.
   - No new evaluator profile is registered. The change makes kernels exact that were not, and the meaning of no mode already reported exact changes.
4. **The open point.** No recording distinguishes (max - min) + e from max - (min - e).
   - The two forms round the same exact value. The first rounds twice when max - min is inexact, and the second rounds once whenever min - e is exact (min >= e/2).
   - An exhaustive scan of the 16-bit sources finds 9 946 of the 2^31 (min, max) code pairs where the two forms differ: min codes 1 to 4 047, max codes 1 014 to 36 735. The hue grid holds none of them.
   - The evaluator keeps (max - min) + e, the form of the earlier fit.
   - compositor-blend-gaps.md §3.5 specifies an optional recording that would settle it.
5. The form is documented as a model equal to every observation, with its measurement provenance. It is not a claim about Painter's source.

## Alternatives Considered

- **Keep the release gaps until the reciprocal argument is pinned.** Rejected: both forms give identical results on every recorded input. The difference lies outside the recorded domain and is stated as such.
- **A new evaluator profile for the corrected kernel.** Rejected: profiles pin quantisation and compositing rules. Making a release-gap kernel exact follows the precedent of decision 053.

## Consequences

- Items 2.1 and 3.1 of phase1.11_compositor-blend-gaps are met.
- Item 4.1 is met by this local run on the owner's machine (decision 028).
- Every documented BlendingMode with a kernel is exact against the Tier 0 sweeps.
- The other recording of decision 067 for this task, `blend-normal-opacity`, is exact on all 48 maps without a change: off-grid opacities 0.1, 1/3, 0.7 and 0.99, and flat normals. Its residuals join the normal-map entries of `blend-kernels.json`.
