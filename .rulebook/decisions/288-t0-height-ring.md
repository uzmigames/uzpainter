# 288. The Tier 0 float32 Height ring: no 1 − (1 − m) rounding, ties at float32 precision, same-island taps at their 3D distance, value-welded vertices and no self-fold window; `export-padding` is exact end to end, the sphere and the cube are left with the tile-border rows and the bevel seams

**Status**: accepted
**Date**: 2026-10-19
**Related Tasks**: phase1.25_pilot-wand, phase1.12_compositor-height-normal, phase1.18_export-engine

## Context

Decision 263 found that Painter's virtual normal reads, at covered island-edge texels, the float32 `infinite`-padded Height ring. Decision 287 found that this ring is the only thing still keeping the Tier 0 Normal from being exact end to end. With UzPainter's own covered normal and the current kernel, the covered Normal was 28,118 of 28,322 (`export-padding`), 60,669 of 61,440 (`export-padding-sphere`) and 52,947 of 53,336 (`export-padding-bevelled-cube`). Every miss came from a covered edge texel.

This pass fitted that float32 Height ring on the three goldens. Their Height is float, so it gives two checks:
- the exported OpenEXR 32f Height is the half toward zero of Painter's float32 ring (decision 263);
- at the stencil taps, decision 263's pinned float32 sets (647, 672 and 1,148 taps) must hold the value.

**Method.**
- **Setting.** CPU only (numpy and scipy). No Painter, no GPU and no `src/` change. The scripts read oracle values, so they stay in private scratch (`pad288/`). Only counts are recorded here.
- **The current kernel ("before").** `tests/export/padding_reference.py` at main (decisions 278, 279), with decision 280's tie order and tap count, and decision 281's 1/256 coverage snap and nearer fewest-hinge path for no-hinge taps. The snap covers no new texel on any of the three meshes.
- **Probes.** `sphere-256` and `bevelled-cube-256` (decision 266) have the same mesh and the same coverage as the sphere and cube goldens (0 differing texels). Their 24 channels are a stronger check of the tap set and the weights, so a sphere or cube ring texel counts as exact only when it is Height-consistent and also bit-exact on all 24 probe channels. The probes keep decision 206's 1 − (1 − m).
- **Holdout.** Every rule was also scored on decision 280's 16 probes (ramps, tie, atlas ×4, sweeps ×3, concave ×3). Each rule is compared per texel, so a loss cannot be hidden by gains elsewhere.
- **End to end.** This is decision 287's check (`pad287/e2e.py`, copied, not edited). The fitted float32 ring is padded with decision 197's flood, then UzPainter's own covered normal is computed (`tools/parity/fit/normal.py`), then decision 287's Normal padding. r1 and r2 give the same counts.

## Findings

### 1. The Height ring before and after

| Golden | Ring | Half-consistent before → after | Height-consistent (half and pinned) before → after | Exact (with the probe) before → after |
|---|---|---|---|---|
| `export-padding` | 1,387 | 1,379 → **1,387** | 1,183 → **1,387** | 1,183 → **1,387** |
| `export-padding-sphere` | 2,176 | 1,583 → 2,010 | 1,149 → 2,010 | 803 → **1,978** |
| `export-padding-bevelled-cube` | 2,344 | 2,041 → 2,043 | 1,823 → 2,002 | 1,768 → **1,947** |

Each rule added in turn. The exact column of the table above, then the covered Normal:

| Step | export-padding (exact / covered N) | sphere (exact / covered N) | cube (exact / covered N) |
|---|---|---|---|
| Current kernel | 1,183 / 28,118 | 803 / 60,668 | 1,768 / 52,962 |
| + no 1 − (1 − m) (§2) | 1,364 / 28,302 | 913 / 60,871 | 1,947 / 53,141 |
| + ties at float32 precision (§3) | **1,387 / 28,322** | 913 / 60,871 | 1,947 / 53,141 |
| + same-island far taps at 3D distance (§4) | 1,387 / 28,322 | 1,563 / 61,206 | 1,947 / 53,141 |
| + vertices welded by value (§5) | 1,387 / 28,322 | 1,758 / 61,297 | 1,947 / 53,141 |
| + no self-fold window (§6) | 1,387 / 28,322 | 1,934 / 61,352 | 1,947 / 53,141 |
| + same-island own taps at 3D distance (§4) | 1,387 / 28,322 | **1,978 / 61,395** | **1,947 / 53,141** |

### 2. The stencil reads the chain's value without decision 206's 1 − (1 − m)

The Height values are signed. For m in [−1, −½], 1 − m lies in [1.5, 2], so 1 − (1 − m) drops m's last bit.

**On the pinned taps.** The chain with the 1 − (1 − m) step matches 447, 105 and 774 pinned taps. Without it, it matches 627, 215 and 953. The variants below match fewer:

| Variant | Pinned taps matched (export-padding, sphere, cube) |
|---|---|
| No output rounding | **627 / 215 / 953** |
| Rounding mirrored by sign | 527 / 131 / 779 |
| The chain over the encoded fma(h, ½, ½), with or without the rounding, then decoded | ≤ 374 / 109 / 604 |
| Current, 1 − (1 − m) | 447 / 105 / 774 |

**The exported halves cannot tell the variants apart:** 1,379 or 1,380 of 1,387 texels either way.

**The probes keep the step.** Their exported channels still need decision 206's step. Whether it belongs to the write is not observed. What is observed is narrower: the value the stencil reads is the chain's raw float32 result.

### 3. Exactly tied taps are tied at float32 precision

**The misses.** On `export-padding` the remaining 23 misses lie on the island turned 30°. Their two side taps are 4.1·10⁻⁸ apart in relative distance. That is less than one float32 ulp, but above decision 280's tie tolerance (10⁻⁹), so the float64 distance ordered them.

**The fix.** A brute-force search over every tap subset of the 5 × 5 window, in every tie order, finds the pinned value on all 23 texels. Painter takes the left side tap (−1, 0) before the vertical one. Decision 280's own-tap order gives exactly that, once the two are treated as tied.

**The tolerance.** The tie tolerance (`EQUAL_SHARE`) is raised to 10⁻⁷:
- `export-padding` becomes 1,387 of 1,387.
- The 16 holdout probes lose no texel and gain 114: `concave-shape` +77, `concave-fold` +36, `atlas-1024-moved` +1.
- On the goldens, a tolerance of 10⁻⁸ changes nothing. 10⁻⁶ gains 3 more cube texels; it was not run on the holdout.

### 4. The curved same-island class: same-island taps take their 3D distance

**The sphere's ring is its pole fans.** Every sphere ring texel lies in rows 0–14 or 241–255. Each pole triangle is UV-separated from its neighbour by a V-gap, but joined to it in 3D by a spoke and in UV through the quads below. So the taps across a V-gap are in the same island, but in another non-coplanar face.

**What the decoded weights show.** Of the 683 texels where our taps equal decision 270's decoded taps but the weights differ:
- **raw 3D distance** for those taps reproduces the decoded weights, and the probe bit for bit, on 650;
- it loses none of the 901 that were already right;
- the single-hinge unfold (decision 270's frame), the tap's own-triangle extrapolation, and the nearer of the two give fewer.

**The rule.** A tap in τ's own island (chart) that lies in another face is measured at its 3D distance from q, not unfolded. This holds:
- for far taps (the seam window): sphere exact 913 → 1,563;
- for own 8-neighbours in another pole triangle: 1,934 → 1,978.

Taps in another island keep decision 270's unfold.

**Holdout.** No texel is lost or gained on the 16 probes: their same-island taps across a hinge already agree. Applying raw 3D distance to every far tap instead breaks the cube (0 of 2,344) and is rejected.

### 5. Vertices are welded by value: −0 and +0 are one coordinate

**The bug.** `sphere.obj` writes the pole and the u = 0 | 1 seam column with both −0.000000 and 0.000000. The reference welds vertices by their float32 bits, and so does `src/export/padding.cpp` (`std::bit_cast<uint32_t>` keys). That splits 21 of the 482 positions (503 unique keys instead of 482), so:
- the seam between the first and last pole triangles (u = 0 | 1) does not exist;
- the 32 pole copies are not one vertex.

**What Painter does.** Its decoded taps cross that seam: ring texels at x ≈ 0–8 take taps at x = 249–255.

**The rule.** Weld by value (−0 = +0). This takes the sphere from 1,563 to 1,758 exact. No other Tier 0 fixture mesh has a negative zero, so the holdout is unchanged.

### 6. A seam edge that folds back into τ adds no window

**The case.** Decision 279 opens the seam edges of every island owning an own neighbour. On the fans, one of them is the neighbouring pole triangle's spoke, whose far triangle J is τ itself. Folding q across that hinge lands back on the ring texel's own centre (f − (x, y) = (0.49991, 0.50000) in float64). So the 3 × 3 window is decided by a 10⁻⁴ offset, and it adds τ's texel two columns away as a "far" tap.

**The rule.** Skip a seam edge whose far triangle is τ. In exact arithmetic its window is the ring texel's own 3 × 3, which adds no far tap.

**Counts.**
- Sphere exact rises from 1,758 to 1,934: 202 texels gained, 13 lost.
- The 13 need that tap. They are spread over segments with no pattern, so Painter's own rounding of this boundary decides them. They stay open.
- Holdout: `atlas-1024-moved` loses 1 and gains 1. The other 15 probes are unchanged.

### 7. What still misses

**`export-padding`: none.** The ring is exact on all 1,387 texels.

**`export-padding-sphere`: 198 texels.**

| Class | Texels |
|---|---|
| Tile-border rows 0, 1, 254, 255 (decision 270's border-row item: Painter's apex rows at the tile edge) | 164 (96 tap set, 32 same taps, 36 undecoded) |
| Self-fold window flip (§6) | 13 |
| Undecoded (decision 270's decode needs more than 18 candidates) | 11 |
| Other tap set | 10 (4 with own neighbours in two triangles) |

**`export-padding-bevelled-cube`: 397 texels.** None of them is a concave hinge: the mesh is convex.

| Class | Texels | Owner |
|---|---|---|
| Single-hinge convex far taps across a bevel seam (the far tap's face shares an edge with τ's face; 200 decode to another tap set, 27 to the same set with other weights) | 227 | the bevelled cube's seam distance, with decision 284 |
| Multi-facet: a chain or decoded tap in a face with no edge to τ's face | 122 | decision 284 |
| Exact under another order of tied far shares | 41 | open (decision 280's far order) |
| Flagged `mixed-gates` | 7 | decision 279 (c) |

**Not fitted, as briefed:** the multi-facet distance and the bevelled cube's seam distance (decision 284), and the concave single-hinge distance (decision 282; none on these meshes).

### 8. End to end (decision 287's check, with the fitted float32 Height ring)

| Golden | Covered Normal | Ring Normal | Gutter Normal | Before (decision 287 §5): covered / ring / gutter |
|---|---|---|---|---|
| `export-padding` | **28,322 / 28,322** | **1,387 / 1,387** | 35,822 / 35,827 | 28,118 / 1,147 / 30,663 |
| `export-padding-sphere` | 61,395 / 61,440 | 2,002 / 2,176 | 1,685 / 1,920 | 60,669 / 1,020 / 771 |
| `export-padding-bevelled-cube` | 53,141 / 53,336 | 2,137 / 2,344 | 8,908 / 9,856 | 52,947 / 1,929 / 7,936 |

- **`export-padding` is exact end to end.** Its 5 gutter misses are decision 276's seed ties. They are the same count as with Painter's own ring.
- **The sphere and the cube.** The remaining 45 and 195 covered misses are edge texels whose stencil tap is a §7 ring miss.
- **The exported Height** (the half of the padded ring) is exact on 1,387, 2,010 and 2,043 ring texels. The interior is unchanged and exact.

### 9. With decision 285, which landed during this pass

Decision 285 (b) measures an own tap in a triangle that shares a UV edge with τ through its own triangle, and (c) sets the seam reach D to 1.78.

**Combined.** Both added on top of §2–§6:

| Golden | Exact | Covered Normal | Ring Normal | Gutter Normal |
|---|---|---|---|---|
| `export-padding` | 1,387 | 28,322 | 1,387 | 35,822 |
| `export-padding-sphere` | 1,978 | 61,395 | 2,002 | 1,685 |
| `export-padding-bevelled-cube` | 1,949 | 53,142 | 2,138 | 8,912 |

- The cube gains 2 texels and loses none, as decision 285 saw on its probe. The sphere is unchanged.
- **V-gap own taps.** Decision 285 kept decision 279's unfold for own taps whose triangle shares only a UV corner with τ (the sphere's V-gaps). Under §3 and §5, §4's 3D distance gains 44 sphere texels over that unfold and loses none.
- **Not rerun on the holdout.** This combination was not rerun on the 16 holdout probes. Each part was checked there on its own: §3–§6 here, and decision 285's (b) and (c) in decision 285.

## Decision

1. **Recorded, not implemented.** No `src/`, test, semantics entry, capability, conformance case or exception changes. Item 2.7 stays open, and decision 245's refusal (`CheckIslandNormal`), decision 259's `CheckPadding` refusal and R-090 are unchanged.
2. **Identified for the ring kernel's integration** (with decisions 278–281), all checked per texel on the 16 holdout probes with no net loss:
   - **(a) No 1 − (1 − m) on the Height the stencil reads.** The float32 ring the virtual normal reads is the chain's raw result. The probes' exported channels keep decision 206's step; where the step lives for other maps is not observed.
   - **(b) Ties at float32 precision.** The tap-order tie tolerance is 10⁻⁷ relative, not 10⁻⁹; decision 280's orders then apply.
   - **(c) Same-island taps at 3D distance.** A tap in τ's own island that lies in another face is measured at |q − p|, not unfolded. This covers far taps and own taps whose triangle shares at most a UV corner with τ. An own tap across a shared UV edge follows decision 285 (b). Taps in another island keep decision 270's unfold.
   - **(d) Weld by value.** −0 and +0 are one coordinate, in both the reference and `padding.cpp`.
   - **(e) No self-fold window.** A seam edge whose far triangle is τ opens no window.
3. **Rejected:** decision 206's step and its sign-mirrored or encoded-space variants on the Height ring (§2); raw 3D distance for every far tap (§4: 0 of 2,344 on the cube); keeping the self-fold window (§6: 13 texels against 202).
4. **Still open:**
   - the sphere's tile-border rows (164);
   - the self-fold boundary's rounding (13);
   - the cube's single-hinge bevel-seam distance (227) and its multi-facet distance (122), with decision 284;
   - 41 cube texels exact only under another order of tied far shares;
   - the flagged and undecoded texels of §7.
   **Not rescored:** the Wand (decision 281's 42 curved same-island texels, 34 of them exact under decision 285) under rules (c) and (e). Its geometry comes from an OBJ with the same weld keys, so (d) must be checked there too.
5. **No new recording is requested.**

## Alternatives Considered

- **Keep 1 − (1 − m) and look for a different chain on signed values.** Rejected: every rounded or encoded variant matches fewer pinned taps than the raw chain (§2).
- **Order near-tied taps by float64 distance (decision 280's 10⁻⁹).** Rejected: it gets the 30° island's tie wrong on 23 texels, and 10⁻⁷ costs nothing on the holdout (§3).
- **Unfold same-island taps about the hinge (decision 270's frame).** Rejected on the sphere: 650 of 683 texels need the 3D distance (§4).

## Consequences

- With these rules, the Height ring and the virtual normal of `export-padding` (four flat islands, one turned 30°) are exact everywhere but decision 276's 5 gutter seed ties.
- What still blocks the Tier 0 Normal is now:
  - the sphere's tile-border rows;
  - the bevelled cube's seam and multi-facet distances (decision 284);
  - a 13-texel float32 boundary.
- **These need no retesting:** the 1/256 snap on these three meshes (it covers nothing new); decision 206's step and its variants on the Height ring; tie tolerances of 10⁻⁸ and 10⁻⁹.
