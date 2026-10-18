# 264. The ring weights are inverse object-space distance with one diagonal divided by 1 + 1/382, and the GPU square root fixes tie's four 1-ulp misses, but the sign on non-dyadic UVs is still not found

**Status**: accepted
**Date**: 2026-10-18
**Related Tasks**: phase1.25_pilot-wand, phase1.18_export-engine, phase1.16_export-processing-encoders

## Context

On 2026-10-18 the owner ruled that the Wand must match Painter everywhere, padding included. Exact `infinite` padding on UV islands (item 2.7 of `phase1.25_pilot-wand`) is therefore the critical path.

Decision 261 found a sign rule for the border ring's along-edge shift. It gets 3,787 of 3,792 texels on tie and keeps the fixed set (11,022 of 11,022). Three things were left open:
- **(a)** the barycentric arithmetic for non-dyadic UVs. r15's 384-texel island gets only 2,083 of 3,438;
- **(b)** four tie-2048 texels whose two squared distances differ by 1 ulp, where Painter took the tie direction;
- **(c)** the tie-512 texel that lies on the quad's split diagonal.

Decision 262 showed that the seam's tie order is the same sign. Decision 263 pinned 1,000 float32 ring values of Painter's `infinite`-padded Height on three goldens that are not UV ramps.

**This pass used those values as new evidence.**
- **Source.** The values are pinned from the OpenEXR 32f `Normal_OpenGL` of the r1 recordings (`pn/recover.py`).
- **Selection.** Only straight-edge ring taps were kept, the ones with exactly three covered neighbours in a line: 315 on `export-padding` (`islands.obj`), 310 on the sphere and 1,136 on the bevelled cube.
- **Use.** Each value is a weighted mean of three covered Height values that are not collinear, so it gives the kernel weights as well as the sign.

**The brief's hypotheses.**
- **G1.** GPU rasteriser barycentrics: fixed-point edge functions with sub-pixel bits, then a float32 multiply by fl(1/area).
- **G2.** Plane-equation interpolation a + b·x + c·y, with the coefficients per triangle in float32.
- **V.** Using the ring values, not only their signs, as a constraint.

**How it ran.**
- On the CPU, from the private store. No Painter, no GPU, no writes to Assets3D.
- Within the 2-hour box.
- Every operation in float32, correctly rounded, except where the recording GPU's own `sqrt` and `rcp` tables (`tools/parity/fit/hwmath.py`, decisions 064 and 065) are named.
- The scripts stay in private scratch (`pad264/`), because they read oracle values.

**Scoring.** Decision 261's sets are kept: Mixed T (tie, 3,792), Mixed R (r15's 384-texel island, 3,438) and the fixed set (11,022). This pass adds:

| Set | Texels | Source | Fixed rule |
|---|---|---|---|
| isl | 295 | `export-padding`: island 1's top ring, island 2's top ring, island 3's top and left rings | 172 |

A prediction of "tie" takes the fixed rule, as in decision 261.

## Findings

### 1. The straight-edge weights are inverse object-space distance, with one diagonal divided by 1 + e and e = 1/381.9

**Where the model applies.** Only the `islands.obj` taps fit a three-tap mean.
- On the sphere and the bevelled cube, the straight-edge taps read across seams.
- Under any three-tap kernel they miss by 0.03 to 0.5. They are left out.

**What makes the test possible.** The islands of `islands.obj` are 10 × 10 world units, but their texel aspect differs: 96.30, 63.40 and 66.50 texels across against 96.20 down. In texel-space 1/d the diagonal weight would be 1/√2 on every island. In object space it is p/√(p² + l²), where p and l are the world sizes of one texel across and along the edge.

**The fit.** The model is v = (h_s + a·h_full + (a/(1 + e))·h_reduced) / (1 + a + (a/(1 + e))), fitted per island. Here h_s is the side neighbour and h_full, h_reduced are the two diagonals.

| Edge (taps) | Object-space p/√(p² + l²) | Fitted a | 1/e | Residual, median / max (ulps) |
|---|---|---|---|---|
| island 1 top (94) | 0.707474 | 0.70680 | 381.85 | 1.15 / 10.8 |
| island 2 top (46) | 0.550286 | 0.55174 | 381.82 | 0.26 / 0.84 |
| island 3 top (60) | 0.568633 | 0.56971 | 382.05 | 0.36 / 1.42 |
| island 3 left (95) | 0.822592 | 0.82280 | 381.93 | 0.50 / 23.2 |

- **The weights follow object-space distance, not texel distance.** The texel-space value would be 0.7071 on every island.
- **The factor e is a constant.** It is 1/381.9 ± 0.1 on four geometries whose diagonal weights range from 0.55 to 0.82.
- **A shift of the query point is rejected.** That model fits equally well per island, but it needs a different shift on each: 0.0019 to 0.0040 texel along the edge. So the asymmetry is a fixed factor on one diagonal, as decision 217 inferred, and not a sample offset.
- **One part is unexplained.** The diagonal-to-side ratio deviates from exact object-space 1/d by −0.1 % to +0.26 % per island (a/geo = 0.9990 to 1.0026, standard errors 3·10⁻⁶ to 2·10⁻⁴). These rejected kernels do not reproduce it:
  - 1/d^p (p from 0.9956 to 1.0027);
  - 1/(d + ε) and 1/d + c;
  - √(d² + κ);
  - one anisotropic metric (island 3's top and left edges need u/v = 1.4426 and 1.4477).

### 2. The recording GPU's square root fixes tie's four 1-ulp misses

The comparison is made on d = sqrt(d²), using the recording GPU's sqrt. Everything else is decision 261's rule.

| Comparator | Mixed T | Mixed R | Fixed | isl |
|---|---|---|---|---|
| d² (decision 261) | 3,787 | 2,083 | 11,022 | 165 |
| correctly rounded sqrt(d²) | 3,787 | 2,083 | 11,022 | 165 |
| **GPU sqrt(d²)** | **3,791** | 2,082 | 11,022 | 165 |
| GPU rcp(GPU sqrt(d²)), the larger weight wins | **3,791** | 2,082 | 11,022 | 165 |
| GPU rsqrt(d²) | 3,787 | 2,081 | 11,022 | 165 |
| GPU rcp(d²) | 3,787 | 2,083 | 11,022 | 165 |

- **How it fixes them.** The GPU sqrt maps each of the four tie-2048 pairs (1407, 612), (1407, 617), (1407, 634) and (1652, 640) to equal lengths. They become exact ties and take the fixed direction, which is Painter's.
- **Open item (b) is closed.** Tie-2048 is now 3,048 of 3,048.
- **Open item (c) is unchanged.** The only tie miss left is tie-512 (158, 223), the split-diagonal texel.

### 3. Decision 261's rule does not generalise to non-dyadic UVs

On `islands.obj`, decision 261's rule gives 165 of 295 signs. The fixed rule gives 172, and chance is about 148.

So r15's failure is not specific to that island: the rule fails wherever the UVs are non-dyadic. The table gives the best count each family reached, with the pinned distance unless noted.

| Hypothesis | Variants | Mixed T | Mixed R | Fixed | isl |
|---|---|---|---|---|---|
| Decision 261's grid (normalisation × barycentric form × space × interpolation × order × distance) | 8,640 | 3,787 | 2,262 | 11,022 | 180 (148 to 175 where T ≥ 3,787) |
| **G1:** raster barycentrics; vertices snapped to none, 4, 8 or 16 sub-pixel bits; direct, NDC or NDC-up chain; divide, fl(1/area) multiply, exact, or 1 − l; 3 orders; 3 interpolation forms | 540 | 3,787 | 2,083 | 11,022 | 198 |
| **G2:** plane equation a + b·x + c·y, relative to vertex 0 or absolute, FMA or not, divide or reciprocal | 72 | 2,317 | 2,074 | 11,022 | 172 |
| Per-triangle affine UV → object map (the tangent frame dP/du, dP/dv); 3 normalisations, 3 spaces, 6 evaluation forms, each vertex as origin | 1,080 | 2,331 | 2,422 | 11,022 | 183 |
| Barycentrics from shader-style float32 arithmetic: 5 edge-function forms (with FMA contraction), 3 area forms, division as x·rcp_GPU(y) or 1 − l, GPU sqrt comparator | 720 | 3,791 | 2,082 | 10,956 to 11,022 | 189 |
| Positions interpolated near-exactly and rounded once to float32 (normalised vertices, or world then normalised), then exact, FMA or dot distance | 15 | 2,394 | 1,931 | 11,013 to 11,022 | 173 |
| The texel sample point moved by (±0.25, ±0.5) texel in x and y | 24 | 2,464 | 2,374 | 11,022 | 182 |

**Hypothesis V.** The values constrain the kernel, as finding 1 shows, but not the position arithmetic. A one-ulp change in a weight moves the mean by about 10⁻⁹ relative, far below the value's own ulp. So the values pin weights to about 10⁻⁵ and cannot discriminate float32 positions. The position arithmetic is visible only through the sign.

**Structure on r15.** Against decision 261's rule:
- the top edge is the rule's sequence inverted and moved one column back (Painter's sign at column j is minus the rule's sign at j − 1);
- the left edge is the rule's sequence inverted and moved one row forward;
- the bottom edge agrees until |x′| becomes small near its end.

No variant above reproduces that inversion and shift. The quantity Painter compares on non-dyadic UVs therefore uses different positions from every barycentric reconstruction of the texel centre tested here.

## Decision

1. **Recorded, not implemented.**
   - Item 2.7 stays open. EXC-007 and the coverage-only write (decision 223) are unchanged.
   - No production code, semantics entry, capability, conformance case or test changes.
2. **Pinned for the integration:**
   - **The kernel weights.** The straight-edge ring weights are inverse object-space distance. The diagonal that loses the sign comparison is divided by 1 + e, with e = 1/381.9 ± 0.1. Its per-island deviation of −0.1 % to +0.26 % is still open (finding 1).
   - **The comparator.** The sign compares the lengths through the recording GPU's sqrt, not the squared distances. An exact tie of the lengths goes toward +u, +v. This closes decision 261 4(b): tie-2048 is 3,048 of 3,048.
3. **Rejected, with the counts above:**
   - G1, raster fixed-point barycentrics with fl(1/area);
   - G2, plane-equation interpolation;
   - the per-triangle affine (tangent-frame) map;
   - shader-style barycentrics with the GPU rcp;
   - once-rounded positions;
   - texel sample offsets;
   - a query-point shift in place of the 1 + e factor.

   None of them reproduces the sign on non-dyadic UVs (at most 198 of 295 on `islands.obj`, at most 2,422 of 3,438 on r15, and never both with tie kept).
4. **Still open:**
   - **(a)** The positions Painter compares on non-dyadic UVs: r15 and `islands.obj`.
   - **(b)** The per-island deviation of the diagonal-to-side weight ratio.
   - **(c)** The tie-512 split-diagonal texel.
   - **(d)** Decision 262's seam weights. Finding 1 suggests they too are object-space distances; the seam fits used the unfolded UV plane.
5. **No new recording is requested.** The `islands.obj` set (295 signs) joins tie and r15 as the scoring set for the next pass. Owner: `phase1.25_pilot-wand` item 2.7.

## Consequences

- An integration now has the weight form and the comparator, given the sign: inverse object-space distance, 1/(1 + 1/381.9) on one diagonal, and the GPU sqrt.
  - On tie and the fixed set, the sign is exact except one texel.
  - On non-dyadic UVs it is not, so `infinite` padding on islands stays refused in the exact sense.
- The per-island weight deviation and the seam weights should be tested in object space before any further UV-plane kernel search.
- These need no retesting as the source of the sign on non-dyadic UVs:
  - GPU-snapped barycentrics;
  - plane equations;
  - tangent-frame maps;
  - shader-style rcp barycentrics;
  - once-rounded positions;
  - sample offsets.
