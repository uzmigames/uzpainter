# 271. The tie order is not reduced-precision positions, mixed tap and ring arithmetic, derivative extrapolation or a fixed neighbour order; decision 267's comparator stays the best, and seam own-diagonal ties break even on exact geometry

**Status**: accepted
**Date**: 2026-10-19
**Related Tasks**: phase1.25_pilot-wand, phase1.18_export-engine, phase1.16_export-processing-encoders

## Context

On 2026-10-18 the owner ruled that the Wand must match Painter everywhere, padding included. Exact `infinite` padding on UV islands (item 2.7 of `phase1.25_pilot-wand`) is the critical path.

**What was known:**
- The straight-edge and seam rings are an FMA lerp chain over 1/d shares, quantised to 10, 8 and 6 bits (decisions 267 and 268). Given the order of the taps, they are bit-exact on every decoded texel.
- **The one unknown left is the tie order.** It decides which of two exactly equal shares leads the chain.
- Decision 267's comparator works like this:
  - mesh-box-normalised vertices;
  - edge-function barycentrics;
  - interpolation fma(l₂, P₂, fma(l₀, P₀, l₁·P₁));
  - the ring texel extrapolated through each diagonal's own triangle;
  - FMA squared distance, then the GPU sqrt;
  - an exact tie toward +u, +v.
- **Where that comparator stands:**

| Set | Exact |
|---|---|
| tie | 3,792 of 3,792 |
| r1 and r2 | all |
| `atlas-512` / `-1024` / `-2048` | 1,150 of 1,661 each |
| `atlas-1024-moved` | 1,014 of 1,661 |
| `ramp-r15-p0` | 1,454 of 1,908 |
| `ramp-r15-p25` | 1,499 of 1,908 |
| `islands.obj` | 164 of 295 |

- Decision 268 left the seam tie order open:
  - which tied tap leads on 254 + 128 interior texels of r2-p0 and 127 + 128 of r2-p25;
  - the 220 tied 4th slots.

**What this pass tested.** The hypotheses decision 267 had not tried:
- **(1)** Positions stored at reduced precision (RGBA16F, UNORM16 of the box-normalised position).
- **(2)** The distance taken to the tap's stored position, computed differently from the ring texel's extrapolated position.
- **(3)** The ring position extrapolated from a covered texel's stored value.
- **(4)** A sort on quantised codes or packed keys, with ties broken by a fixed neighbour order.

**The data.** Decision 267's per-texel orders. Its scratch caches (`pad267/sign_*.pkl`) were read, not changed.
- **The fitting set** is the atlas: 6,644 texels on exact vertices, made of 1,661 configurations repeated at 512, 1024 and 2048 with identical orders.
- **The held-out set** is `atlas-1024-moved`.
- **The constraints** are tie and r15.

**How it ran:**
- On the CPU with numpy, from the private store: no Painter, no GPU and no writes to Assets3D, within the 2-hour box.
- Every operation is float32, correctly rounded per operation, except the recording GPU's own sqrt and rcp tables (`tools/parity/fit/hwmath.py`).
- Exact positions are rational arithmetic, rounded once.
- The scripts stay in private scratch (`pad271/`), because they read oracle values.

**Scoring** is decision 267's: a predicted exact tie takes the fixed direction (+u, +v).

## Findings

### 1. Reduced-precision stored positions are ruled out by the moved atlas

| Storage (taps, or taps and ring) | Atlas | Moved | tie-512 | Orders that change, atlas → moved |
|---|---|---|---|---|
| Painter | — | — | — | **368** |
| float32, decision 267's rule | 1,150 | 1,014 | 744 | — |
| RGBA16F, taps only | 1,134 | 970 | 388 | 360 |
| RGBA16F, taps and ring | 1,005 | 967 | 398 | 0 |
| UNORM16 of (p + 1)/2, three decode forms, any combination | 879 to 1,008 | 867 to 964 | 352 to 374 | 2 to 6 |

- **The moved atlas.** Its normalised vertices are the atlas's values moved by at most 1 float32 ulp (499 of 723 coordinates), yet Painter changes 368 orders.
  - **UNORM16** cannot do that. Its codes absorb 1-ulp changes, so it changes at most 6.
  - **Half precision** stores every atlas texel centre exactly, so it reduces to ties. It also breaks tie (388 to 398 of 744), which needs float32 rounding of the normalised vertices.
- **The deciding rounding is at float32 scale.** It is not a texture quantisation.

### 2. Different arithmetic for taps and ring texel does not reach past 1,150

**(a) Mixed recipes.** Tap positions under one recipe, ring positions under another, with the ring extrapolated through the side triangle or through each diagonal's own triangle. That is 432 × 432 × 2 = 373,248 combinations. Each recipe combines:
- 6 barycentric forms;
- 3 spaces (UV, v-flipped UV, raster);
- 4 interpolation forms;
- 6 orders.

| Best by | Atlas | Moved | tie-512 |
|---|---|---|---|
| tie kept (743 or 744) | **1,150** | 1,016 | 743 |
| atlas alone | 1,211 | 1,020 | 508 |
| moved alone | 1,134 | 1,041 | 527 |

The only variants that keep tie are decision 267's rule and recipes that equal it on these probes.

**(b) Other tap arithmetic:**

| Variant | Atlas | Moved | tie-512 |
|---|---|---|---|
| Taps correctly rounded from exact positions, ring by decision 267's recipe | 1,134 | 1,038 | 616 |
| Ring exact, taps by decision 267's recipe | 989 | 965 | 632 |
| Both exact (everything ties) | 1,005 | 962 | 474 |
| Hardware-style plane equations for the taps (a + b·x + c·y, absolute or from a vertex, FMA, divide or reciprocal, all vertex orders, raster or UV space: 108 variants × 3 ring recipes × 2 modes) | at most 1,134 | at most 1,040 | at most 592 |

So the taps are not a stored map with different arithmetic from the ring texel.

### 3. The ring position is not extrapolated from a covered texel

| Variant | Variants | Atlas | tie-512 |
|---|---|---|---|
| q = P_side + Σ Δlᵢ Pᵢ (rounded barycentric step in the side or each diagonal's triangle, 3 forms × 6 orders, 2 spaces, 4 tap recipes) | 288 | at most 1,016 | at most 572 |
| q = P_tap + ddx·Δx + ddy·Δy, from the bake's 2×2-quad differences (coarse or fine, 3 evaluation forms) | 6 | at most 919 | at most 343 |

**Conservative rasterisation cannot supply ring positions here.**
- Atlas item 0 is a one-texel row whose quad spans pixel rows 16.25 to 16.75. Its ring rows 15 and 17 are 0.25 px clear of the triangles.
- So no fragment, conservative or not, is generated there, yet Painter orders those 764 ring texels.

### 4. No fixed neighbour order or packed key changes the count

**Every fixed order is covered.** A stable sort over a fixed 8-neighbour order only decides exact ties. On straight edges, every one of the 8! orders reduces to one tie direction per side (T, B, L, R), which gives 16 cases. All 16 were scored over the 9 probes, with own-triangle or side-triangle extrapolation and d or d²:

| Tie directions (T, B, L, R) | Total of 14,744 |
|---|---|
| (+x, +x, −row, −row), the fixed rule | **12,715** |
| next best | 11,619 |

**Packed keys.** The key is the float32 bits of d², d, the GPU's 1/d or rsqrt(d²), with the low b bits (b = 0 to 11) replaced by an index, truncated or rounded: 192 variants.
- None moves the atlas from 1,150.
- Every b ≥ 2 loses tie.

**Comparing quantised codes** is the fixed rule (1,007), because both tied diagonals always code 64 of 255.

### 5. Other barycentric sources, also rejected

| Variant | Variants | Atlas | Moved | tie-512 |
|---|---|---|---|---|
| Barycentric plane equations lᵢ = Aᵢx + Bᵢy + Cᵢ with float32 per-triangle coefficients (5 coefficient forms, 4 evaluation forms, l₀ = 1 − l₁ − l₂ or not, 3 spaces, 4 interpolations, 2 modes) | 960 | 958 to 961 with tie kept, at most 988 | at most 955 | 744 kept by some |
| Division by the GPU's rcp(area), with and without one refinement step, 1 − l | 192 | at most 1,150 | at most 1,016 | 743 to 744 |
| UV vertices stored as half, UNORM16 (rounded or truncated), UNORM15 or SNORM16 | 12 | at most 1,146 | at most 952 | 744 only for half |
| A free vertex order per triangle (coordinate descent, an upper bound) | — | 1,184 | — | — |

### 6. Where the rule fails, it is not missing a small extra rounding

Agreement of decision 267's rule with Painter, by the rule's margin |d₋ − d₊| in units of 2⁻²⁴:

| Probe | Exact tie | (0, 0.75] | (0.75, 1.5] | (1.5, 3] | > 3 |
|---|---|---|---|---|---|
| `atlas-512` | 472 / 671 | 191 / 320 | 252 / 342 | 205 / 281 | 30 / 47 |
| `atlas-1024-moved` | 223 / 350 | 342 / 581 | 228 / 373 | 187 / 304 | 34 / 53 |
| `ramp-r15-p0` | 900 / 1,027 | 418 / 690 | 136 / 160 | 0 / 31 | — |
| `tie-512` | 161 / 161 | 574 / 574 | 7 / 7 | 2 / 2 | — |

**Agreement barely grows with the margin.** On r15-p0, the 31 largest margins all disagree. So Painter's position errors are as large as the rule's own, and not a small correction on top of them. Its per-texel position arithmetic differs from every reconstruction tried.

**A localised signature on atlas item 0** (the one-texel row, triangle 0):

| Ring | Region (px) | Normalised x′ | Agreement | Painter "+x" | Rule "+x" |
|---|---|---|---|---|---|
| Top | 320 to 398 | ≥ 0.25 | 75 / 79 | 72 | 74 |
| Top | 208 to 319 | −0.19 to 0.25 | 49 / 112 | 32 | 91 |
| Bottom | 320 to 398 | ≥ 0.25 | 78 / 79 | 67 | 68 |
| Bottom | 208 to 319 | −0.19 to 0.25 | 76 / 112 | 46 | 72 |

- **In the 208–319 region** the rule's positions are mostly exact, so it mostly predicts the tie direction +x. Painter instead leans −x.
- **The switch sits at the float32 binade x′ = 0.25.** That marks the order as decided at the position's own float32 scale, not in the texture domain.

### 7. Seam ties: own diagonals break even where decision 267's positions are exact

The tied pairs were read from decision 268's decodes (`pad268/dec_ramp2.pkl`, read only). A pair is tied when the unfolded distances are equal. "Later" means the +u, +v tap.

| Probe | Pair | Pairs | Later leads | Earlier leads | Decision 267's own-triangle rule |
|---|---|---|---|---|---|
| r2-p0, ring A | own diagonals (−1, ±1) | 254 | 112 | 142 | 112 (all predicted ties) |
| r2-p25, ring A | own diagonals | 127 | 47 | 80 | 47 (all predicted ties) |
| r15-p25, ring A | own diagonals | 255 | 111 | 144 | 130 |
| r2-p0, ring B | far / far | 769 | 410 | 359 | not applicable |
| r2-p25, ring B | far / far | 128 | 0 | **128** | not applicable |

**The seam path compares in other coordinates.**
- On r2, decision 267's own-triangle positions are exact and every straight-edge order is the fixed one (1,140 of 1,140). Yet the same two own diagonals break both ways on the seam ring.
- So the seam ring compares its taps in coordinates that round even on exact geometry. The likeliest reading is the unfolded frame that decision 268 measures d in.
- r2-p25 B's far/far ties all go to the earlier tap (128 of 128), and r2-p0 B's split 410/359.

The comparator for far taps is not tested here, because extrapolating the ring texel through a far triangle has no meaning.

## Decision

1. **Recorded, not implemented.**
   - Item 2.7 stays open.
   - `src/export/padding.h` keeps decision 223's coverage-only rule, and `infinite` on UV islands stays refused before writing. EXC-007 stays withdrawn (decision 259).
   - No production code, semantics entry, capability, conformance case, exception or test changes.
2. **Kept:** decision 267's comparator as the best known tie order. It is exact on tie, r1 and r2 straight edges, and nothing tested here beats it on the atlas while keeping tie.
3. **Rejected, with the counts above:**
   - positions stored as RGBA16F or UNORM16 (the moved atlas's 368 changed orders rule out any texture quantisation);
   - mixed tap and ring arithmetic (373,248 combinations);
   - correctly rounded taps;
   - hardware-style plane-equation taps;
   - ring positions extrapolated from a covered texel by a barycentric step or by 2×2-quad derivatives;
   - conservative rasterisation as the ring position source;
   - any fixed neighbour order (all 16 restrictions of the 8! orders);
   - packed sort keys;
   - comparing quantised codes;
   - barycentric plane equations;
   - GPU-rcp barycentrics;
   - quantised UV vertices.
4. **Still open:**
   - **(a)** The straight-edge tie order on non-dyadic UVs:

     | Probe | Exact |
     |---|---|
     | atlas | 1,150 of 1,661 |
     | moved atlas | 1,014 |
     | r15-p0 | 1,454 of 1,908 |
     | r15-p25 | 1,499 of 1,908 |
     | `islands.obj` | 164 of 295 |

     The deciding arithmetic is float32 per-texel position arithmetic that is not a barycentric interpolation of the texel centre in any tested form.
   - **(b)** The seam tie order, in both parts:
     - own diagonals (254, 127 and 255 pairs; Painter breaks ties even where decision 267's positions are exact);
     - far taps (769 and 128 pairs).

     It needs the unfolded-frame arithmetic, which is untested.
5. **No new recording is requested.** The ideas left need no Painter run:
   - fit the seam own-diagonal ties on r2, whose geometry is exact. Their 254 + 127 orders isolate whatever transform the seam path applies;
   - test whether the same transform, applied on straight edges, explains the atlas.

   Owner: `phase1.25_pilot-wand` item 2.7.

## Consequences

- **The value side of the ring is solved, and the order is not.**
  - Every ring value is exact given the tap order (decisions 267 and 268).
  - The order is exact only where Painter's and decision 267's arithmetic agree: tie, and r1 and r2 straight edges.
  - Exact `infinite` on general meshes stays refused.
- **The search has narrowed:**
  - Texture-storage, rasteriser-coverage and sort-key explanations need no retesting.
  - The r2 seam ties are the cleanest remaining evidence. They are exact geometry with orders that break both ways, so any candidate frame transform can be scored there first.
