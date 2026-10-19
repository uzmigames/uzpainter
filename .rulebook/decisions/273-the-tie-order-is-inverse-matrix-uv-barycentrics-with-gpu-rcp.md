# 273. The straight-edge tie order is decision 267's comparator with inverse-matrix UV barycentrics, the GPU reciprocal and a reciprocal box scale: exact on all 17,472 sweep ties and on 18,350 of 18,351 older ones

**Status**: accepted
**Date**: 2026-10-19
**Related Tasks**: phase1.25_pilot-wand, phase1.18_export-engine, phase1.16_export-processing-encoders

## Context

On 2026-10-18 the owner ruled that the Wand must match Painter everywhere, padding included. Exact `infinite` padding on UV islands (item 2.7 of `phase1.25_pilot-wand`) is the critical path.

**What was known.** Every ring value is an FMA lerp chain over quantised 1/d shares, bit-exact given the order of the taps (decisions 267, 268 and 270). The one unknown left was the **tie order**: which of two exactly equal shares leads the chain.
- Decision 267's comparator (own-triangle extrapolation, edge-function barycentrics, GPU sqrt, ties toward +u and +v) was exact on tie, r1 and r2, but got 1,150 of 1,661 on the atlas.
- Decision 271 ruled out reduced-precision positions, mixed tap and ring arithmetic, derivative extrapolation, fixed neighbour orders and packed keys.
- Decision 272 recorded six sweep probes: hundreds of copies of one tie configuration, with swept 3D positions, k-ulp translations, scales, vertex orders and three mesh boxes.

**This pass** reads the order of every straight-edge tie on the three strips probes (5,824 ties each), lets the sweeps say which inputs the order depends on, fits the arithmetic, and checks it on every earlier probe.

**How it ran:**
- On the CPU with numpy, from the private store. No Painter, no GPU and no writes to Assets3D. The time box was 2.5 hours.
- Every operation is float32, correctly rounded per operation, except the recording GPU's own sqrt and rcp tables (`tools/parity/fit/hwmath.py`). Each FMA is one rounding; on the moved atlas, an exact rational FMA gives the same result as the float64 one.
- The order is read directly. In each ring texel, the one-hot slots (User0 to User2 of r1 `infinite`, step 45) give each diagonal's weight, and the larger weight leads.
- Each copy's geometry is the written float32 mesh, rebuilt with `request_fixtures.sweep_layout` and `SweepCopy`.
- The scripts stay in private scratch (`pad273/`), because they read oracle values.

## Findings

### 1. What the sweeps say about the order, before any fit

| Probe of decision 272 | Response of Painter's order | What it shows |
|---|---|---|
| F3 (y = ±40, ±44, ±48 cm, distant UV slots) | identical to the base in all three boxes | y and the UV slot do not enter |
| F5, face order reversed | identical, 23 of 23 copies in every box | no last-writer or face-order effect |
| F5, vertex rotation | changes the order | the arithmetic is not symmetric in the vertex list |
| offcentre against centred | identical wherever the normalised vertices of both diagonals' triangles are identical (4,720 of 4,720 ties). The 204 changed orders are all copies whose vertices round differently at 356 cm | the order is a function of the box-normalised vertices; world-space interpolation is ruled out |
| F2, one-ulp steps across x | 1 to 7 of the 12 orders change per step. The ring below the first column of the row strip has period 3 in k at bases A and B (`--+--+…`) | the interpolation multiplies absolute positions by non-dyadic weights. A vertex-relative (delta) form would not depend on k |
| F1, strips at binade-scaled positions (40, 80, 160 cm; −64 and −128 cm) | often identical in the centred box, never in box320 | the rounding scales with the position's binade, as Σ lᵢPᵢ does |

### 2. The comparator

Decision 267's structure is kept:
- The ring texel is extrapolated through each diagonal's own triangle.
- The squared distance uses FMA, then the GPU sqrt.
- An exact tie leads toward +u on rows and toward +v on columns.

**Three of its parts change:**

**(a) Box normalisation.** The mesh's float32 bounding box lo, hi gives:
- ext = hi − lo;
- c = fl(lo + fl(ext · 0.5));
- r = fl(1 / fl(max(ext) · 0.5)), correctly rounded;
- P′ = fl(fl(P · r) − fl(c · r)).

**(b) Barycentrics.** They are computed in UV space (float32 u, v; texel centre u = fl((x + 0.5)/N), v = fl(1 − fl((y + 0.5)/N))), from a per-triangle inverse matrix based at the triangle's third vertex V₂:

```
e0 = U0 − U2            e1 = U1 − U2
det = fl(fl(e0.u·e1.v) − fl(e0.v·e1.u))
r   = rcp_gpu(det)                                  (the recording GPU's reciprocal)
m00 = fl(e1.v·r)  m01 = fl(−e1.u·r)  m10 = fl(−e0.v·r)  m11 = fl(e0.u·r)
dx = fl(pu − U2.u)      dy = fl(pv − U2.v)
l0 = fma(m00, dx, fl(m01·dy))     l1 = fma(m10, dx, fl(m11·dy))
l2 = fl(1 − fl(l0 + l1))
```

**(c) Interpolation.** P = fma(l₂, P′₂, fma(l₀, P′₀, l₁·P′₁)), the same order as decision 267.

### 3. Counts

**Sweep strips** (decision 272, every straight-edge tie):

| Probe | Decision 267's rule | Fixed direction | **This rule** |
|---|---|---|---|
| `tie-sweep-strips-centred` | 4,054 | 4,180 | **5,824 / 5,824** |
| `tie-sweep-strips-offcentre` | 4,102 | 4,256 | **5,824 / 5,824** |
| `tie-sweep-strips-box320` | 3,605 | 3,225 | **5,824 / 5,824** |

The exact count holds in every group: F1 3,808, F2 1,488, F3 72, F4 180 and F5 276 per box.

**Older probes.** These are the directly read signs of decisions 264 and 267, with the caches read and not changed:

| Probe | Ties | Decision 267's rule | **This rule** |
|---|---|---|---|
| `atlas-512` / `-1024` / `-2048` | 1,661 each | 1,150 | **1,661** each |
| `atlas-1024-moved` (held out) | 1,661 | 1,014 | **1,660** |
| `tie-512` / `tie-2048` | 744 / 3,048 | 744 / 3,048 | **744 / 3,048** |
| `ramp-r1-p0` | 1,524 | 1,524 | **1,524** |
| `ramp-r2-p0` / `-p25` | 1,140 each | 1,140 | **1,140** each |
| `ramp-r15-p0` / `-p25` | 1,908 each | 1,454 / 1,499 | **1,908** each |
| `islands.obj` | 295 | 164 | **295** |
| **Total** | 18,351 | — | **18,350** |

### 4. Why each part is needed

Each alternative below was scored on the same sets. Each loses texels.

| Change from the rule | Effect |
|---|---|
| Edge-function barycentrics l = e/A, all orders and remainder forms | strips ≤ 4,248 (centred) |
| The inverse matrix with a correctly rounded rcp, or a divide | atlas 1,459 / 1,448 |
| Raster space instead of UV space | r15-p0 1,504 (atlas, tie and `islands.obj` unchanged) |
| The inverse-matrix dot product without FMA | atlas 1,587; r15-p0 1,739 |
| l₂ = (1 − l₀) − l₁, or (1 − l₁) − l₀ | fewer, on every probe |
| P′ = fl(P/h) − fl(c/h) (decision 261) | box320 4,942 |
| c = fl((lo + hi)/2) | moved atlas 1,245 |
| P′ = fl((P − c)·r) or fma(P, r, −c·r) | tie-512 665 or 710 |
| Comparing d² without the sqrt | tie-2048 3,044 |

**The GPU sqrt does real work.** On tie-2048 it merges 5 d² values that are 1 ulp apart, and Painter takes the fixed direction on all 5.

**The one miss** is the moved atlas texel (162, 326), on its left side.
- The GPU sqrt makes it a tie, so the rule takes the fixed +v direction. Painter takes −v, which is the d² order.
- On the moved atlas, Painter goes with the merged tie on 3 of the 4 texels where the sqrt merges unequal d².
- No sqrt, rsqrt, distance-order, box-centre or reciprocal variant fixes it without breaking others.

### 5. Seam own-diagonal ties are not explained by this rule

On the sweep seams probes (79 seam copies), ring A has 6 own-diagonal ties per copy, 474 in all:
- **385 are invisible in the one-hot slots.** The tied pair sits at the chain's last level, where σ = 1/2 codes t = 1/2, so both weights are equal.
- **Of the 89 visible, the rule's 3D comparator matches 79 or 12**, depending on the tie direction. It predicts the same direction on all of them.

This agrees with decision 271's finding that the seam path compares taps in other coordinates, likely the unfolded frame. The r2 and r15 seam decodes of decision 268 and decision 270's V-gap texels were not scored in this pass.

## Decision

1. **Pinned for the integration.** The straight-edge tie comparator is finding 2: box normalisation (a), inverse-matrix UV barycentrics with the GPU reciprocal (b), and the fma(l₂, P₂, fma(l₀, P₀, l₁·P₁)) interpolation (c), all on the triangle's stored vertex order. Then come own-triangle extrapolation, the FMA squared distance and the GPU sqrt. An exact tie goes toward +u on rows and +v on columns.
   - It replaces decision 267's comparator.
   - It closes decision 267 open item 4(a) and decision 271 open item 4(a): 18,350 of 18,351 older ties, and 17,472 of 17,472 sweep ties.
2. **Recorded here, implemented separately.** The kernel in `src/export` (commit 975f6e4, `wt/pad-kernel`) is owned by another task. This decision changes no production code, semantics entry, capability, conformance case, exception or test.
3. **Rejected, with the counts above:**
   - edge-function barycentrics;
   - correctly rounded reciprocals and divides in the barycentrics;
   - raster-space barycentrics;
   - decision 261's p/h − c/h normalisation;
   - the (lo + hi)/2 box centre;
   - comparing d² without the GPU sqrt.
4. **Still open:**
   - **(a)** The moved-atlas texel (162, 326): 1 of 18,351.
   - **(b)** The seam tie order: the own-diagonal ties of the sweep seams, r2-p0, r2-p25 and r15-p25, and the far/far ties. It needs the unfolded-frame comparator. The 385 sweep seam ties that the one-hot slots cannot show can be read only through the value chain's rounding.
   - **(c)** The V-gap position choice of decision 270 and the seams probes' H groups, which were not scored.
5. **No new recording is requested.** Owner: `phase1.25_pilot-wand` item 2.7.

## Consequences

- The straight-edge ring of every isotropic island edge is now determined bit for bit: the value from decisions 267 and 268, and the order from this decision. That covers dyadic and non-dyadic UVs, exact and rounded geometry, and every tested box.
- Exact `infinite` on general meshes still waits on the seam and V-gap orders (4(b) and 4(c)) and on decision 267's anisotropic item 4(c).
- The sweeps' structural findings need no retesting: face order, the UV slot, y stacking, box offset at equal normalised vertices, and the dependence on vertex rotation.
