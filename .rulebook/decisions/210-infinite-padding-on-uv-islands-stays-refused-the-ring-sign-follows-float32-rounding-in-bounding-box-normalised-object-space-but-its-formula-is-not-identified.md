# 210. `infinite` padding on UV islands stays refused: the ring sign follows float32 rounding in bounding-box-normalised object space, but its formula is not identified

**Status**: accepted
**Date**: 2026-10-13
**Related Tasks**: phase1.25_pilot-wand, phase1.18_export-engine, phase1.16_export-processing-encoders

## Context

Item 2.7 of `phase1.25_pilot-wand` asks for a bit-exact fit of `infinite` padding on UV-islanded sets. Decision 206 fixed the border-ring value up to one unknown: the sign of its along-edge shift of ±E·2⁻¹⁵ texel. The sign is fixed per side on 10,278 texels and mixed on the rest. Decision 206 showed that the mixed sign cannot come from any UV-space quantity, so it comes from some per-island float32 quantity outside UV space.

This pass tested the four hypotheses the brief named, all of which place that quantity in world or raster space:
1. **H1.** A float32 UV → world → UV round trip through the mesh triangles.
2. **H2.** Tangent-frame quantities (dP/du, dP/dv and their normalisation).
3. **H3.** The texel centre computed in another space, scaled through the world map, and the mesh's world bounding box used to normalise positions.
4. **H4.** The rasteriser's fixed-point vertex snap at the texture's resolution.

**Data.** The data is that of decision 206: the 17,508 straight-edge ring texels of the P-ramp and P-tie probes (User0 RGB32F, r1 step 10), with the meshes `parity/fixtures/tier0-semantics/meshes/tie.obj` and `seam-ramp-*.obj`.

| Set | What it covers | Texels | The fixed rule (+x on horizontal edges, −row on vertical edges) predicts |
|---|---|---|---|
| Mixed | tie-512 (744), tie-2048 (3,048), and r15's 384-texel island (1,146 per phase) | 7,230 | 4,513: tie 2,333 of 3,792, r15 2,180 of 3,438 |
| Fixed | r1, r2, and r15's 256-texel island | 10,278 | 10,278 |

**Scoring.** A hypothesis predicts +, − or "no sign". A prediction of no sign takes the fixed rule. To pass, a hypothesis must agree with Painter on all 7,230 mixed texels and keep 10,278 of 10,278 fixed ones.

**Method.**
- Everything ran on the CPU from the private store, without Painter, within the 2-hour time box.
- Everything was computed in float32 (vectorised numpy, correctly rounded per operation).
- Only counts are recorded here. The scripts stay in private scratch (`pad210/`).

## Findings

### 1. H1, H2 and H4 are rejected: they carry no sign on tie

On tie every input is exact:
- UVs are dyadic (multiples of 1/16, or of a power of two);
- world vertices are integers;
- every scale between UV, world and texels is a power of two (80 world units per UV, 64 or 256 texels per island);
- the vertices land on integer texel coordinates at 512 and 2048.

So any computation that goes from UV to world or raster and back is exact on tie. It leaves no residual, and so no sign, on any of tie's 3,792 texels.

| Hypothesis | Variants | Nonzero residual on tie (raw world) | Best mixed agreement | Fixed kept |
|---|---|---|---|---|
| H1: ring centre or side neighbour → barycentrics → world → UV, back through the same, the other or the side neighbour's triangle | 432: 3 forward barycentric forms; 2 interpolation forms; xz-Cramer or dot-product back-projection, each divided or reciprocal-multiplied; raw world or 2 bbox normalisations | 0 of 3,792 | 4,622 / 7,230 | 360 of 432 variants keep 10,278; the rest drop to as low as 9,790 |
| H2: tangent-frame extrapolation of the ring centre from the side neighbour or vertex 0, then back-projection; rounding of the normalised T and B along the edge | 48 | 0 of 3,792 | 4,513 / 7,230 (the fixed rule's count) | 42 of 48 |
| H4: vertex snap to 1/256 (also 1/16 and 1/4096) texel, v up or down; sign of the snapped-minus-exact edge offset, along or across the edge, at each ring texel | 18 | 0 of 3,792 (all vertices are on the grid) | 4,513 / 7,230 | 3 of 18 |

**H4's phase slip.** The phase slip at power-of-two ranges does not come from the snap either. H4's offsets on r15's 384-texel island agree with Painter's sign at chance (986 of 2,674 nonzero).

### 2. H3: only the mesh bounding box carries the sign

**What is exact on tie.** These carry no sign on tie:
- the texel centre as (x + 0.5)/N, (x + 0.5)·(1/N) or x/N + 0.5/N;
- each of those multiplied through the world map;
- normalisation by the island's own world range, by division, because the island is 10 units wide and its positions are k·10/64 or k·10/256.

**What is not.** Normalising by the **mesh's** bounding box is inexact on tie, whose box is x ∈ [−5, 29] by z ∈ [−5, 5]:
- the box's centre is (12, 0, 0);
- half its largest extent is 17.

On the ramp meshes it is exact, because their box is [0, 20] by [0, 10], with centre (10, 0, 5) and half-extent 10.

That matches every fact of decision 206 at once:
- **Exact where the sign is fixed.** The normalisation is exact on r1, r2 and r15's 256-texel island.
- **Inexact where the sign varies.** On tie the cause is 1/17. On r15's 384-texel island it is 1/384 in the barycentrics.
- **The world-x reading.** It depends on the island's world x, as decision 206's world-x reading of the tie edges requires.

**The candidate rule.**
1. Normalise each vertex in float32 as p/h − c/h.
2. Interpolate the texel centres with l₀P₀ + l₁P₁ + l₂P₂ in that order. The ring centre is extrapolated in its edge triangle.
3. The sign points to the diagonal neighbour with the smaller float32 squared distance.

**How it scores.**

| Set | Agreement | Note |
|---|---|---|
| tie | **2,876 / 3,792 (75.8 %)** | The fixed rule gives 2,333 (61.5 %). |
| Fixed | **10,278 / 10,278** | The ramps' normalised vertices are exact, so the two distances tie and the fixed rule applies. |
| r15's 384-texel island | 1,818 / 3,438 | Below the fixed rule's 2,180. |

**The agreement is specific to the true box.**

| Centre (half-extent h) | tie agreement |
|---|---|
| (12, 0, 0), h = 17, or 17·2ᵏ (8.5 and 34 give identical results) | **2,876** |
| (12, 0, 0.5), h = 17 | 2,668 |
| (0, 0, 0), h = 17 | 2,183 |
| (−5, 0, −5), h = 17 | 2,138 |
| Any centre, h ∈ {1, 3, 5, 7.5, 10, 12, 15, 16, 18, 19, 20, 24, 29} | 2,374 at most |

On r15 no centre or scale stands out: 1,307 to 1,840 of 3,438, all below the fixed rule.

**Painter's own sequences show the same structure.**
- On tie-2048, island 1's top edge agrees on 250 of 254 texels and its bottom edge on 254 of 254.
- On island 3's right edge, the last 149 texels match run for run. That includes an isolated "++" inside a run of more than 100 "−".
- On r15's 384-texel bottom edge, the model's pattern changes at the same texel as Painter's: x = 256, where the normalised world x' = −0.5 crosses a power-of-two range. The patterns on either side differ, though.

**The rest of the computation is not identified.** These variants were run, and none exceeds 2,876 on tie:
- 2,016, 1,728 and 240 formulations, combining:
  - 14 normalisation forms: divide, reciprocal, FMA, centre or minimum, largest extent or diagonal;
  - 6 barycentric forms;
  - 6 interpolation orders, with and without FMA;
  - GPU-style plane-equation interpolation;
  - 3 constructions of the ring position: extrapolated, 2s − i, and s + (s − i);
  - distances from the ring or from the side neighbour, plain or with FMA.
- Every pairing of both float32 roundings of each normalised tie vertex coordinate, under every interpolation order: 768 combinations, 2,851 at most.
- Interpolating world positions first and normalising afterwards, which also breaks the fixed set: 2,201 at most.

So the source of the sign is the mesh-box-normalised object space, but the comparison Painter makes there is not reproduced. Its r15 counterpart is not reproduced either: there the inexactness is in the barycentrics, not the vertices.

**The magnitude stays unexplained.** No float32 rounding is as large as E·2⁻¹⁵ ≈ 7.6·10⁻⁴ texel. A rounding-level difference must therefore select between two fixed outcomes, as a branch or tie-break would.

## Decision

1. `infinite` padding on islanded sets stays refused before writing (`padding.h`, `NotYetSupported` naming R-090).
   - Item 2.7 stays unchecked.
   - No production code, semantics entry, capability, conformance case or golden-comparison test changes.
   - **Why.** The sign rule is not exact on any mixed probe, so the brief's gates were not met. The full infinite exports (ring plus the decision-197 flood) were not assembled, and `padding.h` was not touched. The seams and poles are left to the parallel seam fit.
2. **Rejected, with the counts above:**
   - H1: the world round trip, 432 variants;
   - H2: tangent-frame quantities, 48 variants;
   - H4: the rasteriser vertex snap, 18 variants;
   - from H3: the texel-centre constructions, the world-scale products, island-range normalisation, and normalising after interpolation.
3. **Identified, as a lead and not as an exact rule.** The mixed sign follows float32 rounding of positions normalised by the mesh's world bounding box (centre, and half the largest extent). The evidence is the tie agreement that appears only at the true box, the fixed set kept intact, and the shared run structure. Whatever Painter computes from those positions is not identified.
4. **Still open:**
   - **(a)** The sign rule: the comparison made in normalised space, and the r15 barycentric counterpart.
   - **(b)** The seam blend (decision 176, 3(b)).
   - **(c)** The sphere poles (decision 129 (c)).
   - **(d)** Confirming the decision-197 gutter on `export-padding`, `export-padding-bevelled-cube` and `export-padding-sphere`.
5. **Recordings that would settle finding 2 (owner: Painter, `phase1.25_pilot-wand` item 2.7).** Two cheap P-tie variants, recorded like `export-padding-tie-512`:
   - **P-tie-dyadic-box.** The same three UV islands, with the world quads moved so that the mesh's box is centred at the origin with half-extent 16. For example x ∈ [−16, −6], [−5, 5] and [6, 16], with z ∈ [−5, 5]. The bounding-box reading predicts the fixed sign (+u, +v) on every tie ring texel.
   - **P-ramp-17.** `seam-ramp-r1-p0` with its world positions scaled so that the box's largest extent is 34. The bounding-box reading predicts a mixed sign on r1, which is fixed today.

   Either result decides whether the object-space normalisation is real, before any more formula search.

## Consequences

- G1's P1-WAND gate and the wand's five-map export stay blocked on 2.7, as decisions 127, 129, 176, 184, 197 and 206 recorded.
- The next offline step works in mesh-box-normalised object space and looks for the comparison that selects between the two diagonals.
- World round trips, tangent frames, the vertex snap and texel-centre constructions need no retesting as the source of the sign.
