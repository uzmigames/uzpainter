# 267. The straight-edge ring is a two-step float32 FMA lerp chain, bit-exact on all 18,056 texels given the sign; extrapolating through each diagonal's own triangle closes tie, but the sign on non-dyadic UVs is still not found

**Status**: accepted
**Date**: 2026-10-19
**Related Tasks**: phase1.25_pilot-wand, phase1.18_export-engine, phase1.16_export-processing-encoders

## Context

On 2026-10-18 the owner ruled that the Wand must match Painter everywhere, padding included. Exact `infinite` padding on UV islands (item 2.7 of `phase1.25_pilot-wand`) is the critical path.

**What was known:**
- the gutter is a jump flood seeded by the ring (decision 197);
- the straight-edge ring is a mean of the side tap and the two diagonals. One diagonal is weakened by 1/(1 + e), e ≈ 1/381.9 (decisions 217 and 264);
- the sign (which diagonal is weakened) is the nearer diagonal in mesh-box-normalised object space (decision 261). With the recording GPU's square root as comparator (decision 264), that rule is exact on tie except the tie-512 texel on the split diagonal. It fails on non-dyadic UVs: r15's 384-texel island and `islands.obj`.

Decision 266's 13 kernel-code probes were recorded on 2026-10-19 (commit c1f30c3). In each ring texel, the one-hot slots (User0–User2) give each tap's normalised weight directly. The codes (User4–User7) show any tap outside the 3×3 window. Decision 269 (corners) found that the corner ring is a float32 FMA lerp chain, not a weighted mean. It also reported a chain for a random 300 straight-edge texels and left the full test to this pass.

**This pass covers:**
- **In scope:** straight-edge ring texels, meaning uncovered texels whose only covered 8-neighbours are three in a line (one side tap and two diagonals). The probes are `atlas-512`, `-1024`, `-1024-moved` and `-2048`, `tie-512`, `tie-2048`, and the ramps r1-p0, r2-p0, r2-p25, r15-p0 and r15-p25.
- **Out of scope:** seams (decision 268) and corners and poles (decision 269).

**How it ran:**
- On the CPU, from the private store: no Painter, no GPU and no writes to Assets3D, within the 2-hour box.
- The r1 `infinite` (step 45) and `passthrough` (step 47) exports of the 11 probes were read.
- **Coverage.** A covered texel is one where `infinite` equals the authored source on all 24 channels. `passthrough` equals the source on every texel.
- **Outputs compared.** Every comparison covers the 15 value channels (User3–User7, three components each) as float32 bit patterns, after decision 206's output rounding: float32, then the 2⁻²⁴ grid with ties to even.
- **Scripts.** They stay in private scratch (`pad267/`), because they read oracle values.

## Findings

### 1. The taps and weights are the same on every probe

The straight-edge ring texels split into two classes on every probe:

| Probe | Straight-edge texels | Main class | Other |
|---|---|---|---|
| `atlas-512`, `-1024`, `-1024-moved`, `-2048` | 1,813 each | 1,661 | 152 |
| `tie-512` | 744 | 744 | 0 |
| `tie-2048` | 3,048 | 3,048 | 0 |
| `ramp-r1-p0` | 2,032 | 1,524 | 508 |
| `ramp-r2-p0`, `-p25` | 1,520 each | 1,140 | 380 |
| `ramp-r15-p0`, `-p25` | 2,544 each | 1,908 | 636 |

- **The main class** is 18,056 texels in all.
  - **Taps.** Exactly the three covered neighbours. The codes reproduce within 2·2⁻²⁴ with no other tap.
  - **Weights.** The one-hot slots read (side, strong diagonal, weak diagonal) = (6,949,506, 4,920,278, 4,907,431)·2⁻²⁴ on every texel of every probe. That holds at every resolution, on exact and on rounded geometry, and on dyadic and non-dyadic UVs. Only which diagonal is the strong one varies.
  - **The weights fitted per texel** (least squares over the 15 value scalars) are constant within the output rounding. The real weights are (6,949,506.45, 4,920,278.4, 4,907,431.1)·2⁻²⁴.
- **The other class** reads across a seam (taps outside the 3×3 window), or has a different weight set. On the ramps it is the seam rings. On the atlas it lies in the multi-piece items: seams, folds, cube corners and fans. These were not checked item by item. They belong to decisions 268 and 269.

### 2. The value is a two-step FMA lerp chain, bit-exact on all 18,056 texels

D₁ is the strong diagonal, D₂ the weak one and S the side tap:

```
m = fma(t₁, v_D₂ − v_D₁, v_D₁)    t₁ = 0x3EFFAA54 = 0.49934638
v = fma(t₂, v_S − m, m)           t₂ = 0x3ED41505 = 0.41422287
```

Then comes decision 206's output rounding. Each difference is a float32 subtraction.

| Probe | Bit-exact (all 15 scalars) |
|---|---|
| `atlas-512` / `-1024` / `-1024-moved` / `-2048` | 1,661 / 1,661 each |
| `tie-512` | 744 / 744 |
| `tie-2048` | 3,048 / 3,048 |
| `ramp-r1-p0` | 1,524 / 1,524 |
| `ramp-r2-p0` / `-p25` | 1,140 / 1,140 each |
| `ramp-r15-p0` / `-p25` | 1,908 / 1,908 each |
| **Total** | **18,056 / 18,056** |

**The fractions are unique.** Moving either fraction by 1 float32 ulp drops the count:

| Fractions | Bit-exact, of 4,313 (tie-512, atlas-512, r15-p0) |
|---|---|
| Both as above | 4,313 |
| t₂ moved 1 ulp | 764 or 856 |
| t₁ moved 1 ulp | 1,471 or 1,684 |

- **t₂ against the corners.** t₂ is 1 ulp below the side-plus-diagonal fraction 0x3ED41506 of decision 269.
- **The sign decides the value.** With the two diagonals swapped, no texel is exact (0 of 1,908 on r15-p0). So the ring value is exact exactly where the sign is right.

**What the chain explains.**
- **Decision 264's 1 + e.** It is the first lerp's fraction: (1 − t₁)/t₁ = 1.0026179, so e = 1/381.97. The kernel is not a weighted mean with a weakened weight. The "strong" diagonal is simply the chain's starting value.
- **Weighted means rejected.** Each was given per-texel freedom in its weights, and none is exact on more than 299 of tie-512's 744 texels:
  - normalised float32 weights with multiply-add, or with FMA, in all 6 orders;
  - unnormalised weights with a divide or a reciprocal;
  - the mean in 1 − v space;
  - the mean relative to the side tap.

**The fractions are decision 268's generator.** Decision 268 found how the fractions are generated: exact 1/d shares, sorted largest first and quantised level by level, with (k, L) = (4, 1023), (3, 255), (2, 63). On a straight edge that gives:
- **The side tap.** Its share is 1/(1 + √2). At level 1 that is code 224 of 1023, so t = 1/4 + (3/4)(224/1023) = 565/1364, which rounds to 0x3ED41505 = t₂.
- **The two diagonals.** Their shares tie at 1/2. At level 2 the leading diagonal gets code 64 of 255, so t = 383/765, which rounds to 0x3F002AD6. The inner step's fl(1 − t) is 0x3EFFAA54 = t₁.

Both are the constants of the table above, so the generator is bit-exact on the same 18,056 texels. The along-edge "sign" is therefore a **tie order**: it decides which of two equal 1/d shares leads the sort and takes code 383 rather than 382 of 765.

### 3. Extrapolating the ring texel through each diagonal's own triangle closes tie

**The rule.** Decision 264's rule extrapolates the ring texel through the side tap's triangle. The comparator here instead extrapolates it through each diagonal's own triangle, then compares the GPU-sqrt lengths to that diagonal. That fixes the tie-512 texel (158, 223) on the split diagonal (decision 264, open item (c)). The comparator is otherwise unchanged:
- mesh-box normalisation;
- fma(l₂, P₂, fma(l₀, P₀, l₁·P₁));
- the squared distance with FMA;
- the GPU sqrt;
- an exact tie toward +u, +v.

| Probe | Fixed rule | Decision 264's rule | Own-triangle rule | Texels |
|---|---|---|---|---|
| `tie-512` | 430 | 743 | **744** | 744 |
| `tie-2048` | 1,903 | 3,048 | **3,048** | 3,048 |
| `ramp-r1-p0` | 1,524 | 1,524 | **1,524** | 1,524 |
| `ramp-r2-p0` | 1,140 | 1,140 | **1,140** | 1,140 |
| `ramp-r2-p25` | 1,140 | 1,140 | **1,140** | 1,140 |
| `ramp-r15-p0` | 1,498 | 1,343 | 1,454 | 1,908 |
| `ramp-r15-p25` | 1,497 | 1,327 | 1,499 | 1,908 |
| `atlas-512`, `-1024`, `-2048` | 1,007 | 1,150 | 1,150 | 1,661 each |
| `atlas-1024-moved` | 967 | 1,016 | 1,014 | 1,661 |

With the chain of finding 2, the straight-edge ring is bit-exact on every texel of tie (3,792 of 3,792), r1 and r2 (3,804 of 3,804).

### 4. The sign on non-dyadic UVs is still not found, and the atlas shows it is not the vertices

**What the atlas adds.**
- **The geometry is exact.** Every atlas vertex is dyadic, the box is exactly [−256, 256] cm, and every texel centre's exact normalised position is a float32.
- **But the sign is not fixed.** Painter's signs agree with the fixed rule on only 1,007 of 1,661 texels. So, as on r15's island (decision 261), the rounding that picks the sign happens after the vertices. It is in the barycentrics or the interpolation.
- **It depends on 3D rounding only.**
  - The signs are identical at 512, 1024 and 2048 (1,661 of 1,661), where the UVs scale by powers of two.
  - The moved atlas changes 368 of them. Its normalised positions are the same values with different rounding.

**Rejected on the new data.** Each was scored on tie-512, atlas-512 and r15-p0. None moves the atlas past 1,150. None keeps tie at 743 or more and moves r15-p0 past 1,486; the highest r15-p0 count, 1,542, costs tie 278 texels:
- decision 261's grid of barycentric forms, spaces, interpolation forms and orders (432 variants);
- barycentrics rounded once from exact values, with or without l = 1 − the other two (192);
- point-relative and vertex-relative cross products, with or without FMA, and the area as the sum of the sub-areas or as one cross product (486), with the ring extrapolated through each diagonal's own triangle.

The first two families extrapolate through the side tap's triangle, as decision 264 did; the third extrapolates through each diagonal's own triangle.

**The tie order as a sort on float32 shares.** These sorts were also scored: float32 1/d weights, or shares w/Σw by divide or by reciprocal, in 6 summation orders. The square root and reciprocal were each the GPU's or correctly rounded, or the GPU rsqrt was used. Ties went to the fixed direction. That is 72 variants, each with own-triangle or side-triangle extrapolation. The best keeps tie at 744 and 3,048 but leaves atlas-512 at 1,150, r15-p0 at 1,454 and `islands.obj` at 165 to 167.

**`islands.obj`.** This is decision 264's 295 signs, decided from the pinned Height values. The fixed rule gets 172, decision 264's rule 165 and the own-triangle rule 164. The best barycentric variant gets 179.

**Where the comparator is wrong.** Under the best variant, in the atlas, the computed distances:
- tie on 671 texels, where Painter breaks 199 of the ties away from the fixed direction;
- differ on 990 texels, where only 678 have the right sign.

So the float32 positions Painter compares are not the ones any reconstruction above produces. This is decision 264's finding, now on exact vertices.

## Decision

1. **Recorded, not implemented.**
   - Item 2.7 stays open.
   - `src/export/padding.h` keeps decision 223's coverage-only rule. `infinite` on UV islands stays refused before writing. EXC-007 stays withdrawn (decision 259).
   - No production code, semantics entry, capability, conformance case, exception or test changes.
2. **Pinned for the integration:**
   - **The straight-edge value.** The chain of finding 2, whose fractions are decision 268's generated codes, with t₁ = 0x3EFFAA54 and t₂ = 0x3ED41505, strong diagonal first and side last, then decision 206's output rounding. It replaces decision 264's "inverse object-space distance with one diagonal divided by 1 + 1/381.9" on isotropic texels. The fractions are the same on exact and on rounded geometry.
   - **The sign comparator.** Decision 264's comparator, but with the ring texel extrapolated through each diagonal's own triangle. It is exact on tie (3,792 of 3,792), r1 and r2. This closes decision 264's open item (c).
3. **Rejected, with the counts above:**
   - weighted-mean arithmetic of any order or normalisation, with per-texel weight freedom;
   - once-rounded barycentrics;
   - point-relative and vertex-relative cross-product barycentrics as the source of the non-dyadic sign.
4. **Still open:**
   - **(a)** The tie order of the two equal diagonal shares on non-dyadic UVs: atlas 1,150 of 1,661, the moved atlas 1,014, r15-p0 1,454 to 1,486 and r15-p25 1,499 (of 1,908 each), and `islands.obj` at best 179 of 295.
   - **(b)** Closed by decision 268: t₁ and t₂ are its quantised 1/d shares.
   - **(c)** Decision 264's per-island weight deviation on the anisotropic `islands.obj`. No kernel probe has anisotropic straight edges, so it is untested whether the chain's fractions there come from object-space texel sizes.
5. **No new recording is requested.** The next pass searches the position arithmetic against the atlas's direct signs: 6,644 texels on exact vertices, with the moved copy as a held-out test. Owner: `phase1.25_pilot-wand` item 2.7.

## Consequences

- Given the sign, every isotropic straight-edge ring texel is bit-exact: 18,056 of 18,056 on 11 probes. With decision 197's flood and decision 269's corners, the ring and gutter of tie, and of r1 and r2 away from their seams, are determined bit for bit by pinned rules. They have not yet been run end to end.
- Exact `infinite` on general meshes still needs four things:
  - the non-dyadic sign (4(a));
  - the anisotropic fractions (4(c));
  - the seams (decision 268);
  - the poles (decision 269).
