# 261. The border-ring sign is the nearer diagonal in mesh-box-normalised object space, under one FMA order: tie misses 5 texels, r15's 384-texel island still misses

**Status**: accepted
**Date**: 2026-10-18
**Related Tasks**: phase1.25_pilot-wand, phase1.18_export-engine, phase1.16_export-processing-encoders

## Context

On 2026-10-18 the owner ruled that the Wand must match Painter everywhere, padding included. Exact `infinite` padding on UV islands (item 2.7 of `phase1.25_pilot-wand`) is therefore the critical path. This pass took one piece of it: the sign of the border ring's along-edge shift.

What was known:

- **The ring value.** It is exact once the sign is known (decision 206): the covered centre, shifted along the edge by ±E·2⁻¹⁵ texel, with E in [24.75, 25].
- **The shift's size.** It is a fixed part of the rule. One of the two tied diagonals' weights is divided by 1 + e, with e ≈ 1/384. Rounding only picks which diagonal (decision 217).
- **Where the sign is fixed.** It is fixed (+x on horizontal edges, −row on vertical edges) on r1, r2, r15's 256-texel island and `export-padding-tie-512-box16`.
- **Where it is mixed.** It is mixed on tie-512, tie-2048 and r15's 384-texel island. It depends on world position through the mesh bounding box (decisions 210 and 216).
- **The best earlier candidate** was the nearer diagonal in box-normalised space. It reached 2,876 of 3,792 on tie (decision 210).

**The brief's hypotheses:**

- **H1.** The ring is weighted by world-space distance, and the nearer diagonal in world space wins. Its float32 world distances are computed from the real mesh.
- **H2.** A GPU-order tie-break: the primitive ID of the triangle that covers each diagonal.

**The data** are decision 206's straight-edge ring texels: uncovered, with exactly three covered neighbours in a line, and the perpendicular channel exact. They come from the r1 `infinite` OpenEXR 32f exports (User0 RGB32F) of the probes below.

| Set | Probes | Texels | The fixed rule predicts |
|---|---|---|---|
| Mixed T | tie-512 (744), tie-2048-v2 (3,048) | 3,792 | 2,333 |
| Mixed R | r15-p0, p25 and p75, 384-texel island (1,146 each) | 3,438 | 2,180 (736, 735 and 709) |
| Fixed | tie-512-box16, r1 and r2 at three phases each, r15's 256-texel island | 11,022 | 11,022 |

**Pass criterion.** Every mixed texel agrees, with the fixed set kept at 11,022 of 11,022. A prediction of "tie" takes the fixed rule.

**How it ran.**

- On the CPU, from the private store. No Painter, no GPU, no writes to Assets3D.
- Every operation in float32, correctly rounded per operation. An FMA is rounded once, checked against an exact single-rounding FMA.
- Within the 2-hour box.
- The scripts stay in private scratch (`pad261/`). The `pad176/` to `pad220/` folders were not on this machine, so the loaders were rebuilt. They reproduce decision 197's per-side counts and decision 210's 2,876.

## Findings

### 1. The rule found: 3,787 of 3,792 on tie, fixed set kept

The sign points to the diagonal with the smaller float32 squared distance to the ring texel, computed in mesh-box-normalised object space.

1. **Normalise the vertices.** Each vertex becomes p' = fl(fl(p/h) − fl(c/h)).
   - c is the mesh's world bounding-box centre, and h is half its largest extent.
   - Multiplying by fl(1/h) gives the same counts.
2. **Interpolate each texel.** The texel centre's float32 barycentrics are (l₀, l₁, l₂), indexed in the face's vertex order as written. The texel's position is P = fma(l₂, P₂, fma(l₀, P₀, l₁·P₁)).
   - The covered diagonals are interpolated in their own triangle.
   - The ring texel is extrapolated in its side neighbour's triangle.
   - On tie the barycentrics are dyadic, so every barycentric form tested gives the same result there.
3. **Compare the distances.** Each squared distance is fma(dz, dz, fma(dy, dy, dx·dx)), with d = P_ring − P_diag.
   - The nearer diagonal keeps its full weight, and the other is divided by 1 + e.
   - An exact tie takes the fixed direction, toward +u and +v. That is the later tap in a v-up, row-major scan.

| Set | This rule | Fixed rule | Decision 210's best |
|---|---|---|---|
| tie-512 | **743 / 744** | 430 | — |
| tie-2048-v2 | **3,044 / 3,048** | 1,903 | — |
| Mixed T total | **3,787 / 3,792** | 2,333 | 2,876 |
| Fixed set | **11,022 / 11,022** | 11,022 | 10,278 / 10,278 |
| Mixed R (r15, 384-texel island) | 2,083 / 3,438 (692, 738, 653) | 2,180 | 1,818 |

**The rule is specific.** Each change below breaks it on tie (Mixed T):

| Change | Mixed T |
|---|---|
| Interpolation order (0,1,2) | 2,772 |
| Each of the other four orders | 2,093 to 2,460 |
| Plain sum, no FMA | 2,873 (decision 210's 2,876) |
| P₀ + l₁(P₁ − P₀) + l₂(P₂ − P₀), with or without FMA | 2,293 / 2,194 |
| Normalising as (p − c)/h | 3,432 |
| Normalising with an FMA | 3,639, and the fixed set drops to 10,988 |
| Raw world positions | 2,333, the fixed rule's count, because everything is exact |
| Distance accumulated z first | 3,777 |
| Distance as a plain dot product | 3,783 |
| Measured from the side neighbour instead of the extrapolated ring texel | 2,690 |
| Comparing lengths (sqrt) instead of squared distances | unchanged, 3,787 |

**The start runs come out.** Decision 206 recorded runs that every edge of a family starts with: "−−+−+−+−+" on the six vertical edges and "++−++−++−" on the top edges. Within this family, those runs come from the z-only part of the comparison. They diverge where z' crosses |z'| = 0.125, at the 18th texel at 512, as decision 206 recorded.

**The five misses.**

- **tie-512 (158, 223).** Its +row diagonal lies exactly on the quad's split diagonal and sits in the other triangle (4 against 5). Giving shared-edge texels to the later triangle does not fix it, and it costs 4 more on tie-2048.
- **tie-2048 (1407, 612), (1407, 617), (1407, 634) and (1652, 640).** The two squared distances differ by exactly 1 ulp, and Painter took the fixed (tie) direction on all four. A last-ulp difference in how the distance or the position is formed is left. It is not double rounding in the FMA emulation: the exact single-rounding FMA gives the same counts.

### 2. r15's 384-texel island is not reproduced

On this island the normalised vertices are exact (x' ∈ {−1, 0}, z' = ±0.5), so only the barycentrics round. The rule's sequences have Painter's period of 3, and they break at Painter's texels: island column 192, where x' = −0.5, and the binade edges of z'. But the phase and polarity are wrong (for example, Painter's "+−−" against the rule's "+−+" on the left edge). So the order, normalisation and distance are pinned by tie, but Painter's barycentric arithmetic for non-dyadic UVs is not.

These barycentric variants were run under the pinned interpolation and distance. None beats the fixed rule's 2,180:

- edge functions, divided or multiplied by the reciprocal;
- l₀ = 1 − l₁ − l₂;
- edge functions with FMA;
- two Cramer solves;
- UV space, v-flipped UV space, and raster space;
- GPU-style raster positions through NDC (normalised device coordinates) and the viewport, flipped or not;
- vertices snapped to 1/16, 1/256 or 1/65536 pixel, with exact edge functions then divided, multiplied by the reciprocal or rounded once.

The best is 2,099 (`rcp_fma`, which breaks the fixed set). The pinned-form variants all give 2,083.

The broad search covered 8,640 combinations: 5 normalisations × 6 barycentric forms × 3 spaces × 4 interpolation forms × 6 orders × 4 distance forms. With the fixed set kept, its best on r15 is 2,262 of 3,438, and that variant gives only 2,295 of 3,792 on tie.

### 3. The brief's hypotheses

| Hypothesis | Variants | Mixed T | Mixed R | Fixed kept |
|---|---|---|---|---|
| H1, world-space distance: raw world | 64 | 2,333 (no sign: tie's raw world is exact) | at most 1,665 | at most 11,003 |
| H1 in box-normalised space (finding 1) | 8,640 + 384 | **3,787** | 2,083 | 11,022 |
| H1, world-space Jacobian shear: sign of J_x·J_y from forward, backward, central, quad and coarse differences, at the side or at the diagonals | 200 | at most 2,333 | at most 2,464 | 11,022 at best |
| H2, primitive ID of each diagonal's triangle (lower or higher wins; same triangle as the side wins) | 4 | 2,327 to 2,337 | 2,179 to 2,180 | 10,995 to 11,019 |
| Sign of the float32 rounding error of the ring or side position (along, across or summed) | 288 | at most 2,372 | at most 2,282 | 11,022 at best |
| GPU plane-equation interpolation (a·x + b·y + c with FMA, absolute or relative to vertex 0) | 240 | at most 2,317 | at most 2,074 | 11,022 |
| A lookup table on the single-rounding residues of the four texels' along coordinate | 1 per probe | 236 to 244 of 744 conflict | 315 to 392 of 1,146 conflict | — |

- **H2 is structurally impossible.** The two diagonals share a triangle on every ring texel except 3 to 6 per probe.
- **The lookup table** shows that once-rounded positions alone cannot determine the sign. The sign needs the interpolation's own rounding, as finding 1 confirms.

## Decision

1. **Recorded, not implemented.** The tie-exact sign rule of finding 1 goes to the integration pass, which combines the sign with the seams (decision 262) and the corners. It is not written into `src/export/padding.h` here.
   - Item 2.7 stays open.
   - EXC-007 and the current coverage-only write (decision 223) are unchanged.
   - No production code, semantics entry, capability, conformance case or test changes.
2. **Pinned by tie:**
   - the normalisation p/h − c/h;
   - the interpolation fma(l₂, P₂, fma(l₀, P₀, l₁·P₁)) in face-vertex order;
   - the ring position extrapolated in the side neighbour's triangle;
   - the squared distance fma(dz, dz, fma(dy, dy, dx·dx));
   - the nearer diagonal keeps the full weight, and an exact tie goes toward +u, +v.
3. **Rejected, with the counts above:**
   - world distance on raw positions;
   - Jacobian shear;
   - the primitive-ID tie-break;
   - rounding-error direction;
   - plane-equation interpolation;
   - GPU-snapped barycentrics as the r15 fix.
4. **Still open:**
   - **(a)** Painter's barycentric arithmetic for non-dyadic UVs, which r15's 384-texel island needs (2,083 of 3,438).
   - **(b)** The 1-ulp tie handling of the four tie-2048 misses.
   - **(c)** The ownership of the one tie-512 texel that lies on the split diagonal.
5. **No new recording is requested.** Owner: `phase1.25_pilot-wand` item 2.7.

## Consequences

- An integration can reproduce every straight-edge ring sign on tie except 5, and every fixed-set sign. With these, given the sign rule, decision 206's ring value and decision 197's flood, tie-512 and tie-2048 are exact on the ring except 1 and 4 texels.
- The r15 pattern is matched in period and break points, so the next pass searches only the barycentric computation. The interpolation order, normalisation and distance stay fixed.
- These need no retesting as the source of the sign:
  - raw-world distance;
  - Jacobian shear;
  - primitive ID;
  - rounding-error direction;
  - plane-equation interpolation.
