# 265. The seam and border-ring weights are not 1/d of decision 261's float32 object-space distance: the rounding is two orders too small and absent on exact geometry

**Status**: accepted
**Date**: 2026-10-18
**Related Tasks**: phase1.25_pilot-wand, phase1.18_export-engine, phase1.16_export-processing-encoders

## Context

On 2026-10-18 the owner ruled that the Wand must match Painter everywhere, padding included. Exact `infinite` padding on UV islands (item 2.7 of `phase1.25_pilot-wand`) is the critical path.

What decisions 261 and 262 left:
- **The border-ring sign** is the nearer diagonal by float32 squared distance in mesh-box-normalised object space, under one FMA order (decision 261).
- **The seam's tie order** is that same sign (decision 262 finding 3).
- **The seam weights** are not 1/d. On r2-p25's B ring, two taps at equal unfolded distance need multipliers 1.0038 and 1.0084 against 1/d (decision 262 finding 1).

**The hypothesis.** Since the sign and the tie both come from decision 261's float32 distances, the seam weights might be 1/d with d computed the same way, instead of in UV or the unfolded plane. That would give equidistant-in-UV taps unequal weights. The brief also asked to test the same reading on the straight-edge ring (decision 206):
- the 1/(1 + e) factor on one diagonal, with e ≈ 1/384 (decision 217);
- the corner fraction f ≈ 0.4142245 instead of √2 − 1 (decision 206).

**Decision 261's distance, as used here:**
1. Vertices: p′ = fl(fl(p/h) − fl(c/h)), with c the mesh box centre and h half its largest extent.
2. Texel-centre barycentrics: float32 UV edge functions divided by the float32 area. An exactly rounded variant was also run.
3. Position: fma(l₂, P₂, fma(l₀, P₀, l₁·P₁)) in the face's vertex order. Covered taps are interpolated in their own triangle. The ring point is extrapolated in the triangle of its nearest own-island tap.
4. Distance: d = √fl(fma(dz, dz, fma(dy, dy, dx·dx))); weight fl(1/d). The FMA is exactly single-rounded.

**The data:**
- **Seam interior.** The 3,684 interior seam-ring texels of decision 262, outside the ratio-1 probes. They come from the r1 `infinite` OpenEXR 32f exports of `export-padding-ramp-{r2,r15}-{p0,p25,p75}-v2` and `export-padding-seam-ramp-1024`. Taps are decision 262's: own 8-neighbours plus the far strip, the four nearest, with the tied 4th slot resolved to Painter's pick.
- **Seam corners.** Decision 262's 40 seam corners, r1 included.
- **Straight edges.** Decision 261's 18,252 straight-edge ring texels: Mixed T 3,792, Mixed R 3,438, fixed set 11,022.
- **Corners.** The 144 non-seam corner ring texels of the same 12 probes. Each has one covered side neighbour and one covered diagonal.
- **Pinned Height.** The 2,467 Height ring texels pinned from Painter's EXR32 normals (decision 263 scratch; 1,000 of them to a single float32 value). They come from `export-padding`, `export-padding-sphere` and `export-padding-bevelled-cube`. Unlike the ramp probes, the sphere and the bevelled cube are curved and folded, so object-space distance differs from UV distance there by more than rounding.

**The fit measures:**
- decision 262's least-norm per-tap weight change, at 0.6 % and at 10⁻⁴;
- **bit-exact:** the prediction, rounded to float32 and then to the 2⁻²⁴ grid (decision 206), equals Painter's value on both channels. For pinned Height, the float32 prediction lies in the pinned set.

Everything ran on the CPU, from the private store: no Painter, no GPU, no writes to Assets3D, within the 2-hour time box. The scripts are in private scratch (`pad265/`) and reuse `pad261/`, `pad262/` and `pn/`.

## Findings

### 1. Seam interior: float32 object-space 1/d changes no texel

Counts are out of 3,684.

| Weights | Fit at 0.6 % | Fit at 10⁻⁴ | Bit-exact | Largest weight change against unfolded 1/d (normalised) |
|---|---|---|---|---|
| 1/d, unfolded, float64 (decision 262) | 3,557 | 126 | 126 (r2-p0 B only) | — |
| 1/d, decision 261's float32 object space | **3,557** | **126** | **126** | 3.4·10⁻⁵ |
| The same, with exactly rounded barycentrics | 3,557 | 126 | 126 | 2.1·10⁻⁵ |
| 1/d² in the same space | 126 | 126 | 126 | — |

The counts are the same in every probe class, including r15-p25 B's 127 texels that miss.

**The deciding case is r2-p25 and r2-p75 B.** There, the two far taps tied in unfolded distance have **bit-equal** float32 object-space squared distances on all 252 texels (126 per probe). Their geometry is exact in float32:
- the UVs are dyadic, and the triangle areas are powers of two;
- the normalised vertices lie in {−1, 0, 1} × {±0.5}.

So the hypothesis gives those two taps equal weights. Painter's weights for them differ by a factor of 1.0046.

**The sizes do not match.** Anywhere the rounding is not exact:
- the normalised positions have |x′| ≤ 1, with an ulp of at most 2⁻²³;
- one texel spans 1/384 to 1/128 of the box in normalised units;
- so the rounding moves a relative distance by at most a few 10⁻⁵, as measured above.

Painter's seam deviations are 10⁻³ to 8·10⁻³, two orders larger.

### 2. Decision 261's discrete rule, carried to the seam, breaks the one exact class

The test: in every pair of taps tied in unfolded distance, the nearer by decision 261's float32 squared distance keeps 1/d, and the other gets 1/(d(1 + e)). An exact tie keeps the tap later in a v-up, row-major scan.

| e and preference | Fit at 0.6 % | Fit at 10⁻⁴ | Bit-exact |
|---|---|---|---|
| +1/384, as decision 261 | 3,557 | 0 | 0 |
| −1/384 | 3,557 | 0 | 0 |
| +1/384, preference swapped | 3,557 | 0 | 0 |

The rule moves r2-p0 B's 126 equidistant texels, which plain 1/d reproduces bit-exactly, off Painter's values. It is rejected.

### 3. Seam corners: unchanged

For each of the 40 seam corners, the best 1/d subset (2 to 5 of the 10 nearest) was scored:
- with either kernel, 22 of 40 fit at 0.6 %, and none is bit-exact;
- the 9 corners with no fit (decision 262 finding 4) keep a best perturbation of about 1.0 under the object-space weights.

### 4. Straight edges and their corners: the object-space rounding is far too small

**Straight edges, 18,252 texels.** Painter's along shift is E·2⁻¹⁵ texel, with |E| = 25 at 512 and 24 at 1024 and 2048. Under float32 object-space 1/d, the two diagonals' weights give this shift:

| Set | Painter's \|E\| | Predicted \|E\|, median / max |
|---|---|---|
| tie-512 | 25 | 0.009 / 0.077 |
| tie-2048-v2 | 24 | 0.062 / 0.311 |
| r15 (both islands, three phases) | 24 | 0.000 / at most 0.275 |
| tie-512-box16, r1 and r2 (three phases each) | 24 to 25 | exactly 0 |

No texel comes within 0.25 of Painter's E: 0 of 18,252. The factor's size, 1/384, is not a distance-rounding effect. This confirms decision 217 finding 1 with decision 261's exact arithmetic. Only the sign comes from the rounding (decision 261).

**Non-seam corners, 144 texels.**

| Corner fraction f | Bit-exact (both channels) |
|---|---|
| Float32 object-space 1/d: f in [0.4142073, 0.4142167] | 61 |
| √2 − 1 | 58 |
| Decision 206's f = 0.4142245 | **144** |

On tie-512-box16, r1 and r2, the object-space f is exactly √2 − 1, while Painter's f is still 0.4142245 there. Decision 206's constant f therefore holds on the ramp probes too, and it is a fixed part of the kernel, not rounding.

### 5. The seam residual is not a normalisation error

A further check: whether Painter's seam value is Σ wP / D with D ≠ Σ w, which would push the residual along the absolute position. The solved δ scatters on the A rings (median −3·10⁻⁵ to +5·10⁻⁵, interquartile range up to 2·10⁻⁴). The residual left perpendicular to the position is the same order as the residual itself on every class. Rejected.

### 6. Pinned Height on curved and folded meshes

The pinned values were predicted from the covered Height with three kernels:
- the 4 nearest covered texels by decision 261's float32 object-space distance;
- the own UV 8-neighbours with object-space weights;
- the own UV 8-neighbours with UV weights.

**`export-padding`** (flat islands):
- **At the tile wrap,** the ring texel at column 255 beside the island on u = 0 equals the 1/d mean of its 8-neighbours across the tile border, bit-exact on 96 of 96. Here the ring takes its taps by UV adjacency across the wrap.
- **Straight edges.** Only 12 of 315 are exact, with object-space or UV weights alike. The 1/(1 + e) shift is missing, as finding 4 predicts.

**`export-padding-sphere` (672 pinned, pole rings) and `export-padding-bevelled-cube` (1,148 pinned, folded seams).** No kernel reproduces a single pinned value. The median absolute errors, against a value range of about 1.9:

| Mesh | Object-space 4 nearest, 1/d_obj | Own 8-neighbours |
|---|---|---|
| Sphere | 2.0·10⁻³ | 2.2·10⁻² |
| Bevelled cube | 3.6·10⁻² | 0.50 |

On the folded seams the far taps carry most of the value, since the own-only mean is off by 0.5. But the object-space 4 nearest with 1/d_obj is not Painter's rule there either.

## Decision

1. **Nothing in production changes.** `src/export/padding.h` keeps decision 223's coverage-only rule.
   - Item 2.7 stays unchecked, and EXC-007 is unchanged.
   - No production code, semantics entry, capability, conformance case, exception or test changes.
2. **Rejected, with the counts above:**
   - the seam weights as 1/d of decision 261's float32 object-space distance, with either barycentric form, and as 1/d² (finding 1);
   - decision 261's nearer-tap 1/(1 + e) rule applied to the seam's tied pairs, for e = ±1/384 and either preference (finding 2);
   - the same distance as the source of the seam-corner weights (finding 3);
   - the same distance as the source of the straight-edge factor 1/384 and of the corner f (finding 4);
   - a mis-normalised seam mean (finding 5);
   - the object-space 4 nearest with 1/d_obj on the sphere's pole rings and the bevelled cube's folded seams (finding 6).
3. **Confirmed:**
   - **Decision 206's corner fraction.** f = 0.4142245 is bit-exact on all 144 non-seam corners of the 12 tie and ramp probes, including exact-geometry probes where float32 gives √2 − 1 exactly.
   - **The tile wrap.** The ring texel at the tile wrap takes its 8-neighbours across the border: 96 of 96 bit-exact on `export-padding`.
4. **Still open,** as decision 262 left them:
   - **(a)** the seam weight asymmetry. It is a fixed-size effect of 10⁻³ to 8·10⁻³, present on exact geometry, so it is not a distance computation in any float32 frame;
   - **(b)** r15-p25 B's 127 texels;
   - **(c)** 18 of the 40 seam corners;
   - **(d)** the sphere poles.

   The folded-seam tap rule of the bevelled cube joins them. The ramp probes are flat, so they cannot separate unfolded distance from object-space distance there.
5. **No new recording is requested.** The next offline step is the one decision 262 named: identify the per-row ordering quantity from the r15 exceptions and decision 206's tie sequences. The size of the weight deviation should be treated as a fixed part of the kernel, as decision 217 found for the border ring.

## Consequences

- The owner's 2026-10-18 ruling (the Wand identical to Painter everywhere, padding included) stays unmet. Its blocker is still item 2.7.
- The float32 object-space distance is now known to fix only orderings, the border sign and the seam tie, and never weight sizes. Later passes need not look for the seam's 10⁻³ deviations, the 1/384 factor or the corner f in distance rounding of any frame.
- These need no retesting:
  - float32 object-space 1/d or 1/d² weights;
  - decision 261's tie rule as a seam weight;
  - a mis-normalised mean;
  - object-space nearest-4 taps on curved meshes.
