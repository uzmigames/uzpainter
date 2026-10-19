# 269. Corner ring texels are a float32 FMA lerp chain with fixed fractions, bit-exact on every isotropic corner, but the fractions are not 1/d and the poles stay open

**Status**: accepted
**Date**: 2026-10-19
**Related Tasks**: phase1.25_pilot-wand, phase1.18_export-engine, phase1.16_export-processing-encoders

## Context

On 2026-10-18 the owner ruled that the Wand must match Painter everywhere, padding included. Exact `infinite` padding on UV islands (item 2.7 of `phase1.25_pilot-wand`) is the critical path.

Decision 266's 13 kernel-code probes were recorded and admitted on 2026-10-19. Each ring texel's one-hot slots (User0–User2) give each tap's normalised weight directly, and the codes (User4–User7) show any tap outside the 3×3 window.

**What this pass covers:**
- **In scope:** corner and pole ring texels only. That means convex and concave island corners, staircase corners, cube corners (`corner-r1`, `corner-r1-r1.5-r2`), the atlas fans (`pole-4`, `pole-8`, `pole-8-pyramid`, `pole-12`) and `sphere-256`.
- **Out of scope:** straight edges (decision 267) and seams (decision 268) belong to other passes. A straight-edge sample was used here only to check the arithmetic.

**How it ran:**
- On the CPU, from the private store: no Painter, no GPU, no writes to Assets3D, within the 2-hour box.
- The r1 `infinite` (step 45) and `passthrough` (step 47) exports of all 13 probes were read.
- **Coverage.** A covered texel is one where `infinite` equals `passthrough` on all 24 channels. `passthrough` equals the source bitmap on every texel.
- **Tile wrap.** Neighbours wrap at the tile border (decision 265).
- **Outputs compared.** Every comparison covers all 24 output channels, as float32 bit patterns, after decision 206's output rounding: float32, then the 2⁻²⁴ grid with ties to even.
- **Scripts.** They stay in private scratch (`pad269/`), because they read oracle values.

## Findings

### 1. Flat corners take exactly the covered UV 8-neighbours; poles and cube corners take their taps by 3D proximity

**Flat items.** On every flat atlas item, the 3×3 one-hot weights reproduce all four code channels to within 9.5·10⁻⁸. The taps are exactly the covered 8-neighbours. This holds for all 25 flat items (2,928 covered texels), at 512, 1024 and 2048 and on the moved copy.

**Cube corners and fans.** Most of their ring texels take taps outside the 3×3 window. The decode used candidates chosen by 3D distance instead of UV distance:
- **Candidates:** the item's covered texels within 3.6 cm, in 3D, of the ring texel's extrapolation through each own neighbour's triangle;
- **Solver:** non-negative least squares over 19 scalars;
- **Acceptance:** all 24 channels reproduced to within 10⁻⁶.

On `atlas-512` this decodes 951 of the 952 ring texels of the six items. The tap counts are:

| Item | Ring texels decoded | Taps per texel |
|---|---|---|
| `corner-r1` | 60 / 60 | 1–7 |
| `corner-r1-r1.5-r2` | 63 / 64 | 1–4 |
| `pole-4` | 143 / 143 | 1–12 |
| `pole-8` | 244 / 244 | 1–12 |
| `pole-8-pyramid` | 244 / 244 | 1–8 |
| `pole-12` | 196 / 196 | 1–12 |

Most texels take at most 4 taps (decision 262). Up to 12 appear only next to a fan's apex.

### 2. The mean is a chain of float32 FMA lerps with fixed fractions

**Equal weights do not mean equal arithmetic.** Two configurations with the same normalised weights are not interchangeable: the arithmetic order decides the bits. The forms were compared on the isotropic set, meaning every corner whose taps lie in one isometric piece (finding 3).

**Side plus diagonal: 423 ring texels.**

| Form | Bit-exact (all 24 channels) |
|---|---|
| fma(t, v_diag − v_side, v_side), or fma(1 − t, v_side − v_diag, v_diag), with t = 0x3ED41506 | **423** |
| The same lerp without FMA | 156 |
| Normalised weights, multiply and add | 18 |
| Unnormalised weights 1 and a, then a divide | 44 |
| The exact real mean, rounded twice | 423 for t in [0.4142228961, 0.4142228968], which contains 0x3ED41506. The 2-tap texels alone cannot tell this form from the FMA lerp; the L can |

**The concave L: 68 ring texels.** The taps are two sides and their diagonal. The search covered all 6 tap orders × FMA or not, scanning both fractions ±25 and ±8 float32 ulps:

| Form | Bit-exact |
|---|---|
| m = fma(t₁, v_D − v_A, v_A); v = fma(t₂, v_B − m, m), with t₁ = 0x3ED37E28 and t₂ = 0x3EBD2F4C, where A is the side with the larger weight and B the other | **68** |
| Any other order, or either fraction 1 ulp off | at most 31 |
| Constant real weights, exact mean, double rounding (best of a 61 × 61 scan) | 24 |

**Corner model.** Each case below is bit-exact, with the counts in the next table:

| Taps | Value |
|---|---|
| 1 | copy |
| 2 at equal distance (side + side or diagonal + diagonal, any angle) | fma(0.5, v₂ − v₁, v₁) |
| 2, side + diagonal (adjacent, or a knight's move apart) | fma(0x3ED41506, v_diag − v_side, v_side) |
| L (2 sides + diagonal) | the chain above |

As a cross-check, the straight edge is the same kind of chain. A random 300 of its texels are bit-exact as m = fma(0x3EFFAA54, v_D2 − v_D1, v_D1); v = fma(0x3ED41505, v_S − m, m). Here D1 is the diagonal with the larger weight, and the side comes last. It is recorded for decision 267 only.

### 3. Exact counts

The isotropic corners are every 3×3-only corner ring texel outside the fans: the flat items, the seam and cube-corner items' corners that do not cross a seam, tie and the ramps.

| Probe | Isotropic corners, bit-exact | Fans, `sphere-256` and bevelled cube, bit-exact under the corner model |
|---|---|---|
| `atlas-512` | 500 / 503 | 39 / 98 |
| `atlas-1024` | 500 / 503 | 39 / 98 |
| `atlas-2048` | 500 / 503 | 40 / 99 |
| `atlas-1024-moved` | 500 / 503 | 39 / 98 |
| `tie-512` | 36 / 36 | — |
| `tie-2048` | 36 / 36 | — |
| `ramp-r1-p0` | 12 / 12 | — |
| `ramp-r2-p0` | 14 / 14 | — |
| `ramp-r2-p25` | 14 / 14 | — |
| `ramp-r15-p0` | 14 / 14 | — |
| `ramp-r15-p25` | 17 / 17 | — |
| `bevelled-cube-256` | — | 3 / 3 (single taps) |
| `sphere-256` | — | 0 / 29 |

**Isotropic total: 2,157 of 2,166.**
- **Where it holds.** The fractions are the same on every isotropic probe: at 512, 1024 and 2048, with positions that round (moved atlas), on tie, and on ramps of ratio 1, 1.5 and 2 at phases 0 and +0.25.
- **The 9 misses.** They are the 3 texels per atlas probe of `seam-r1-turn30` that have 2 sides and 2 diagonals, a configuration the model has no fractions for yet.
- **The fan misses.** These are 2-tap and 4-tap texels whose 3D distances differ from their UV distances (finding 5). The corner model's single and equal-pair cases still hold there.

### 4. The fractions are not 1/d and depend on the order of the taps

Against inverse-distance weights, with each fraction read as the new tap's share of a running mean:

| Step | 1/d running mean | Painter | Difference |
|---|---|---|---|
| Side + diagonal | 0.41421356 (√2 − 1) | 0.41422290 | +9.34·10⁻⁶ |
| L: diagonal into the first side | 0.41421356 | 0.41307187 | −1.14·10⁻³ |
| L: second side | 0.36939806 | 0.36950147 | +1.03·10⁻⁴ |

**The L's two sides are tied in distance but not in weight.** Their weights differ by a factor of 1.0015044, and their diagonal is weighted 0.4 % below its 2-tap value. **Which side leads moves with object-space rounding:** it changes on 3 of the 17 L texels between `atlas-1024` and its moved copy. That is the kind of dependence decision 261's sign has, but its comparator was not tested on these texels.

**Kernel shapes rejected.** None reproduces the side-plus-diagonal, straight and L fractions together:
- 1/dᵖ (p = 0.99989 for the 2-tap, 1.0115 for the L);
- 1/(d + c), 1/√(d² + κ);
- a query point shifted by any vector under 1/d (the L keeps a residual of 2.5·10⁻³) or under 1/dᵖ for p from 0.9 to 1.2;
- three fast inverse-square-root constants with 0 to 2 Newton steps;
- sequential blends whose weight comes from the running sum, the running centroid's distance, or that distance times the tap count, under 1/d, 1/d² and 1/√d (errors 10⁻⁵ to 10⁻¹).

**Not rounding.** The fractions are the same on exact and rounded geometry, so they are not a rounding effect of any frame (as decision 265 found for f).

### 5. Fans and cube corners: object-space distance, with the ring texel's 3D position unresolved

**In-plane taps.** Where a 2-tap fan or cube-corner texel extrapolates to one unique 3D point:
- **At a 3D distance ratio of √2,** Painter's fraction differs from 1/d by +9.33·10⁻⁶ ± 3·10⁻⁸ on 33 texels. That is the corner constant of finding 2, now in object space.
- **At ratio 1.18585** (`pole-4`, isometric), it differs by −9.1·10⁻⁶ on 4 texels.
- **Equal 3D distances** give exactly 0.5 on 16 texels.

**Elsewhere.** The deviations from 1/d are 7·10⁻⁵ to 3·10⁻⁴ on the remaining 2-tap fan texels, and up to 0.18 on 3 cube-corner texels whose taps cross a seam.

**Ambiguous positions.** At the V-gap between two fan triangles, the two own triangles extrapolate the ring texel to different 3D points: 23 of the 2-tap fan texels. Where Painter's weights are 0.5 and 0.5, neither extrapolation is equidistant. So Painter's ring position at a V-gap is neither one.

**The other two meshes.**
- **`sphere-256`:** 29 ring texels lie inside the 3×3 window, with 7 taps each, and none is reproduced. Its other pole-ring texels need a 3D map of `sphere.obj`, which this pass did not build.
- **`bevelled-cube-256`:** outside its 3 single taps, every ring texel reads across a seam (decision 268).

## Decision

1. **Recorded, not implemented.**
   - Item 2.7 stays open. `src/export/padding.h` keeps decision 223's coverage-only rule, and EXC-007 stays withdrawn (decision 259).
   - No production code, semantics entry, capability, conformance case, exception or test changes.
2. **Pinned for the integration.** On isotropic corners, bit-exact on 2,157 of 2,166 texels:
   - **Taps:** the covered 8-neighbours.
   - **The value:** a float32 FMA lerp chain, then decision 206's double rounding.
   - **Fractions:** 0.5 for an equal-distance pair; 0x3ED41506 from the side to the diagonal; and, for the L, 0x3ED37E28 from the leading side to the diagonal, then 0x3EBD2F4C to the other side.
3. **Rejected, with the counts above:**
   - the exact real weighted mean with double rounding (it fails the L);
   - the non-FMA lerp;
   - multiply-and-add and divide forms;
   - every L order except leading side, diagonal, other side;
   - the kernel shapes and recurrences listed in finding 4.
4. **Still open:**
   - **(a)** The formula that generates the fractions. They are not 1/d (finding 4), and an implementation for anisotropic or curved geometry needs it; a per-configuration table holds only on isotropic islands.
   - **(b)** Which L side leads, on rounded geometry.
   - **(c)** The fractions for 2 sides plus 2 diagonals, and for every configuration with more than 3 taps.
   - **(d)** The ring texel's 3D position at a fan's V-gap, and the weights of fan texels with 3 or more taps.
   - **(e)** The `sphere-256` pole rings: a 3D decode on `sphere.obj`, then the same fit.
   - **(f)** The cube-corner texels whose taps cross a seam. They need decision 268's far-tap rule.
5. **No new recording is requested.** The next step is offline: fit (a) from the fan items, whose in-plane 2-tap texels give the fraction at 3D distance ratios other than √2, once (d) is fixed. Owner: `phase1.25_pilot-wand` item 2.7.

## Consequences

- The corner ring on isotropic islands is now exact given the leading-side choice. An implementation may use it only where the full ring is exact, which still waits on (a), (b), the straight-edge sign (decision 267) and the seams (decision 268).
- **Later fits should model the chain's order, not only a weight vector.** The same weights in another arithmetic form lose about two thirds of the texels: 24 of 68 L texels survive with the exact mean, and 156 of 423 side-plus-diagonal texels without the FMA (finding 2).
- These need no retesting as the corner kernel:
  - 1/dᵖ, 1/(d + c), 1/√(d² + κ);
  - a query-point shift;
  - fast inverse-square-root weights;
  - running-sum or running-centroid recurrences.
