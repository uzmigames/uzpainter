# 217. `infinite` padding on UV islands stays refused: the ring shift and the seam weight error survive exact geometry, so they are not float32 errors

**Status**: accepted
**Date**: 2026-10-13
**Related Tasks**: phase1.25_pilot-wand, phase1.18_export-engine, phase1.16_export-processing-encoders

## Context

Item 2.7 of `phase1.25_pilot-wand` asks for a bit-exact fit of `infinite` padding on UV-islanded sets. It is the last blocker of the Wand pilot. What earlier passes settled:

| Part | State | Decision |
|---|---|---|
| Gutter | A jump flood seeded with the ring. Bit-exact given the ring. | 197 |
| Straight-edge ring value | The covered centre, shifted along the edge by ±E·2⁻¹⁵ texel (E in [24.75, 25.0]). Bit-exact given the sign. | 206 |
| Ring sign | Fixed on r1, r2 and r15's 256-texel island. Mixed on tie and on r15's 384-texel island. Follows float32 rounding of positions normalised by the mesh box. | 206, 210 |
| Box test | tie with its mesh box centred at the origin (`export-padding-tie-512-box16`) takes the fixed sign on 744 of 744 texels. A uniform world scale of 1.7 changes nothing. | 216 |
| Seam ring | A mean of at most four taps across the unfolded seam, weighted about 1/d, with weights off by about 10⁻³. | 211 |

The brief's hypothesis was that the ring shift and the seam weight error are one thing: the float32 error of a computation in normalised object space. Examples are 3D distances between float32 positions, or 1/d through an approximate rsqrt. If so, one exact computation would give both the sign sequences and the seam weights:
- B's share at r2-p0 is 0.3695015.
- B's ring at r2-p25 is (0.351196, 0.649719).

The data are the decision-206 P-ramp and P-tie probes and the three decision-216 records, all r1 `infinite` (User0 RGB32F). Everything ran on the CPU from the private store, without Painter, within the 2-hour time box. Only counts are recorded here, and the scripts stay in private scratch (`pad217/`).

## Findings

### 1. The shift's size and the seam weight error do not depend on rounding

Both are present, unchanged, on geometry where every float32 quantity is exact.

**The straight-edge ring.** On `export-padding-tie-512-box16`:
- the box is centred at the origin with half-extent 16;
- every vertex, texel centre and normalised position is dyadic, so every float32 operation on them is exact;
- all 744 straight-edge ring texels shift by exactly 25·2⁻¹⁵ texel, the same as tie-512's 744;
- the perpendicular channel is the covered centre on all 744.

Only the sign changed between the two probes (decision 216). So the size of the shift is a fixed part of the rule, and a rounding-level difference only chooses its direction.

**The seam.** On r2-p0, every position is a multiple of 2⁻⁹ in normalised object space, and every distance is exact. These weight kernels are evaluated on that exact geometry, in the units noted:

| Weights | B share at r2-p0 | Corner fraction f |
|---|---|---|
| Painter | **0.3695015** | **[0.4142230, 0.4142260]** (decision 206) |
| 1/d, exact float32 | 0.3693981 | 0.4142136 |
| 1/d with fp16 weights (texel or normalised units) | 0.369386 to 0.369388 | below 0.41421 |
| SSE `rsqrtss` on this machine's AMD Ryzen 9 7950X3D (any power-of-two unit) | 0.3693996 | 0.4142173 |

- The SSE estimate's error depends only on the mantissa, so every power-of-two unit gives the same result.
- None of these reaches Painter's values. On exact geometry the only error left is in the kernel itself, at most 1.2·10⁻⁴ relative for these estimates. Painter's B weight is 4.5·10⁻⁴ relative above √2.

**Rejected:** the brief's hypothesis that the shift and the seam weights are the float32 error of an object-space computation, including approximate rsqrt, fp16 intermediates and the normalisation choices. The shift has a fixed size. The seam deviation exists without any rounding.

### 2. The sign does not depend on where the island sits in UV

`export-padding-seam-ramp-1024` (decision 216) has the same world vertices as `export-padding-ramp-r15-p0-v2`. Its island A is moved 64 texels left in UV (u − 0.0625).

| Ring texels | Compared | Same sign |
|---|---|---|
| A's top and bottom rings, matched by position within the island | 764 | **764** |
| B's straight-edge rings (B is unchanged) | 762 | **762** |

A's period-3 sequences and their phase slip are therefore unchanged. The slip sits at island column 192, where the normalised world x′ = −0.5, and not at a UV value.

This adds to decision 216's box test: the sign is a function of the 3D geometry and the texel's position within its island. Absolute UV plays no part. Any UV-space difference quantity is exact under this translation, so this does not separate the remaining object-space formulations.

### 3. The fixed shift is not a fixed sample offset

The shift and the seam deviations were each converted into an equivalent displacement of the sampling point q, in own-island texels.

| Ring | Displacement that reproduces Painter (1/d) |
|---|---|
| Straight edges | 0.00258 to 0.00260 along the edge. Equivalently, one diagonal's weight divided by 1 + e with e in [1/387.1, 1/383.2]. |
| r2-p0, A ring | 0.00026 ± 0.00014 across the seam, and 0 ± 0.00023 along it. No ±0.0026 along-shift, though A's two diagonals are tied as on a straight edge. |
| r2-p25, B ring | (0.00094, −0.00049), the same on all 124 texels |
| r2-p75, B ring | (0.00055, −0.00096), the same on all 124 texels |
| r15-p0, B ring | alternating (0.00146, −0.00122) and (−0.00228, −0.00133) |

No single displacement, fixed or sign-flipped, covers these cases.
- The along-shift appears only where the ring has its three own taps and no far-island tap.
- With a fourth (far-island) tap, the tied diagonals stay symmetric.

So the straight-edge shift and the seam weight error are not one mechanism.

### 4. The nearer-diagonal rule fails again on r15's 384-texel island

On this island the normalised vertices are exact and only the barycentrics round.
- 96 variants were run: 4 barycentric forms (edge functions, three-edge, reciprocal area, Cramer) × 3 interpolation orders × 2 texel-centre forms × 2 distance forms × 2 triangle choices.
- The best predicts 441 of 764 horizontal ring texels, against 492 for the fixed rule.
- This confirms decision 210's r15 result on the exact-vertex case.

### 5. The output grid is absolute

Every ring value below 0.5 lies on the 2⁻²⁴ grid in every binade (power-of-two range) present, down to 2⁻¹¹ on `export-padding-seam-ramp-1024`. The values in [0.5, 1) use their full float32 precision.
- This is the decision-206 double rounding, now seen on seam blends too.
- It matches a 1 − (1 − v) stage.
- It is not a blend toward the texel's background value: the `passthrough` export shows uncovered texels hold the ramp, not a constant.

## Decision

1. `infinite` padding on islanded sets stays refused before writing (`padding.h`, `NotYetSupported` naming R-090).
   - Item 2.7 stays unchecked.
   - No production code, semantics entry, capability, conformance case or golden-comparison test changes.
   - **Why.** Neither the ring sign nor the seam weights is exact on any mixed or seam probe. The brief gated the full-padding check (ring, flood, seams, corners and sphere poles on `export-padding`, `-bevelled-cube`, `-sphere` and `-seam-*`) on both, so it was not run.
2. **Rejected, with the counts above:**
   - the shift or the seam weight error as a float32, fp16 or approximate-rsqrt error (finding 1);
   - a fixed or sign-flipped sample offset as the common cause (finding 3);
   - the nearer-diagonal rule on r15's 384-texel island, 96 variants (finding 4).
3. **Identified, recorded for the implementation:**
   - the straight-edge shift is a fixed weight asymmetry between the two tied diagonals: one weight divided by 1 + e, e in [1/387.1, 1/383.2]. Rounding in normalised object space only chooses which diagonal;
   - the sign is invariant under a UV translation of the island (1,526 of 1,526);
   - the absolute 2⁻²⁴ output grid below 0.5.
4. **Still open:**
   - **(a)** The rule that chooses the sign (decision 210, 4(a)). It is now known to be the order of two tied taps in object space.
   - **(b)** The origin of the fixed asymmetry e ≈ 1/384, which only three-tap rings show.
   - **(c)** The seam weights (decision 211, 4(a)). They are a structural kernel or tap-position effect, not a rounding effect.
   - **(d)** Decision 211's 4(b) to 4(d): the tap choice on 208 texels, the seam corners and the sphere poles.
5. **No new recording is requested.** The next step is offline: find the tap-ordering rule behind 4(a) and the three-tap asymmetry behind 4(b) from the existing records. Owner: `phase1.25_pilot-wand` item 2.7.

## Consequences

- G1's P1-WAND gate and the wand's five-map export stay blocked on 2.7, as decisions 127, 129, 176, 184, 197, 206, 210 and 211 recorded.
- These need no retesting:
  - explanations of the shift's size or the seam weights by float32 or fp16 rounding, or by approximate rsqrt;
  - a fixed sample offset;
  - UV-position dependence of the sign.
