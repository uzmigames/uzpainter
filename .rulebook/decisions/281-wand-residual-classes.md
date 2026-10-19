# 281. The Wand's remaining infinite-padding misses, classified: Painter's coverage snaps UV vertices to 1/256 texel, a tap with no hinge to the ring face is moved along the fewest-hinge face path, and the gutter is decision 197's flood up to 81 seed ties

**Status**: accepted
**Date**: 2026-10-19
**Related Tasks**: phase1.25_pilot-wand, phase1.18_export-engine, phase1.16_export-processing-encoders

## Context

On 2026-10-18 the owner ruled that the Wand must match Painter everywhere, padding included. Exact `infinite` padding (item 2.7 of `phase1.25_pilot-wand`) is the critical path, and the Wand is the G1 pilot.

**Where main stood (22acbc8, the measured C++ ring).** Every count in this decision is against 22acbc8. Decision 280, which landed while this pass ran, gets 28 more all-four texels from its tap-count fix. Its tie order and that fix were not combined with the rules here.

| Map | Ring exact (of 6,334) | Gutter exact (of 3,679,665) |
|---|---|---|
| BaseColor | 5,794 | 2,458,666 |
| Roughness | 6,195 | 3,594,889 |
| Metallic | 6,247 | 3,587,768 |
| Height | 5,941 (LP-consistent 6,248) | 3,349,244 |
| All four | **5,509** | **2,408,035** |

**This pass:**
1. classifies every all-four ring miss and every gutter miss;
2. fits the largest classes it can.

**How it ran:**
- **The model.** `tests/export/padding_reference.py` at 22acbc8, run on decision 279's pickled Wand geometry. It reproduces the C++ `ring.json` on all 6,334 texels (same taps, distances within 10⁻⁶) and the production counts above exactly, for the ring and the gutter.
- **Scoring.**
  - BaseColor, Roughness and Metallic (BRM) must be exact.
  - Height is scored as decision 277's LP consistency, because it is L16F behind PNG 16 and its exact operand cannot be recovered.
  - The orders of exactly tied shares (relative 10⁻⁹) were all enumerated.
- **Probes.** `bevelled-cube-256` and `sphere-256` (decision 266), all 24 channels bit-exact.
- **Setting.** CPU only (numpy and scipy): no Painter and no GPU. The scripts read oracle values, so they stay in private scratch (`pad281/`).

## Findings

### 1. The 825 all-four ring misses at main

| Class | Texels | BaseColor only | BRM | Height only |
|---|---|---|---|---|
| Height operand: BRM exact, Height LP-consistent | 266 | — | — | 266 |
| Seam tie order: exact under another order of tied shares | **0** | — | — | — |
| Multi-facet: a chain tap in a face with no edge to τ's face | 308 | 231 | 76 | 1 |
| Flagged (`mixed-gates`, `reach-bracket`) | 64 | 29 | 35 | — |
| Curved same-island multi-triangle | 46 | 11 | 35 | — |
| Seam edge 1.5 to 2 texels away (the reach cap) | 10 | 5 | 5 | — |
| Far point on an exact texel boundary | **0** | — | — | — |
| Other | 131 | 92 | 39 | — |

What the classes mean:
- **The Height operand class is not a padding miss.** Those 266 texels need the L16F tap values, which a PNG 16 recording cannot give.
- **No Wand texel turns exact under another tie order.** Decision 280's seam tie order does not show on the Wand's all-four count.
- **A tap with no hinge is the strongest signal.** Texels whose chain taps all lie in τ's face or a face adjacent to it miss on 477 of 5,729. Texels with a no-hinge tap miss on 348 of 605. The multi-facet row counts 308 of them, because the rows above it take the rest.

### 2. BaseColor-only misses: BaseColor is the most sensitive map, not wrong sRGB8 rounding

368 of the 825 misses differ only in BaseColor. They are not rounding misses:
- **Most are well clear of a code boundary.** 276 differ by one sRGB8 code. On all but 4 channel cases, the blended linear value lies more than 10³ float32 ulps from the code threshold, so the blend itself differs.
- **27 cannot be a blend error.** All their BaseColor taps are equal, so the chain can only copy that value: their tap set is wrong.
- **Roughness and Metallic cannot catch these errors.** Their taps are constant on 2,784 of the 6,334 ring texels, so they pass weight errors that BaseColor shows.
- **The operand and the store are right.** Decision 274's operand (the sRGB8 decode) and its store (the thresholds, then the OCIO PNG 16 table) are confirmed. One texel, (567, 1934) channel B, lands exactly on threshold 56|57. Painter gives 56, but it lies in the reach-cap class, so it is not evidence either way.

### 3. Painter's coverage snaps UV vertices to 1/256 texel

- **The two texels.** Ring texels (448, 442) and (454, 548) lie 0.0009 and 0.00015 texels outside a triangle edge.
- **The rule.** Painter covers both. Snapping each vertex's texel-space UV to the nearest 1/256 texel before the edge test gains exactly these 2 texels. It loses none, and no texel centre lies on a snapped edge. This matches the 8-bit sub-pixel vertex precision of a hardware rasteriser.
- **Other grids fail.** 1/512 gains 1 texel, 1/1024 none, and 1/128 gains 4, 3 of which are exact ring texels.
- **The probes.** The snap leaves `bevelled-cube-256` and `sphere-256` coverage equal to Painter's (0 differences).
- **The effect.** The 2 covered texels are new seeds. Their 8-neighbours become new ring texels, whose flood cells (4,418 and about 453 gutter texels) carried values that no seed of ours had.

### 4. The gutter is decision 197's flood: inherited misses, then 81 seed ties

**At main** there were 1,271,630 all-four gutter misses. With our seeds, every one of our gutter texels copies its jump-flood seed, and that seed is an exact nearest seed on all but 5 texels.

| Map | Gutter misses | Inherited (Painter's value = Painter's value at our seed) | Seed differs |
|---|---|---|---|
| BaseColor | 1,220,999 | 1,216,045 | 4,954 |
| Roughness | 84,776 | 80,336 | 4,440 |
| Metallic | 91,897 | 88,418 | 3,479 |
| Height | 330,421 | 325,980 | 4,441 |

- **Given Painter's own ring values,** 4,954 gutter texels (0.135%) differ.
- **With finding 3's coverage, 83 remain:**
  - 81 are **exact flood-seed ties**: an equidistant seed carries Painter's value;
  - 2 take a non-equidistant seed.
- **So every other gutter miss is inherited from a ring miss.**

**The tie-break was fitted, and nothing beats the current flood.** Each variant was scored as the number of gutter texels that differ given Painter's seed values:

| Variant | Differing texels |
|---|---|
| Decision 197's offset order and strict `<` (current) | **83** |
| Same, start step 2048 | 83 |
| Same, float32 UV distance (either sum order) or float32 texel distance | 83 |
| JFA+1 or JFA+2 | 88 |
| 1+JFA | 719 |
| y-flipped, x-flipped or xy-flipped offset order | 206 to 534 |
| `<=`, scan order, reversed scan order or swapped axes | 12,480 to 13,527 |

The 81 ties fall on 18 seed pairs with no common direction. They stay open. Decision 276's 4,370 Normal flood-seed ties are on another map and were not rescored.

### 5. Multi-facet distances: move the tap along the fewest-hinge face path

**`bevelled-cube-256` under the current reference** gives 1,872 exact texels, plus 71 under another tied order: 1,943 of 2,344.
- Decision 270 reported all 2,341 multi-tap texels failing. Its scratch geometry welded vertices by OBJ index, and this mesh gives every chart its own vertices, so no seam ever shared an edge.
- All 133 texels with a chain tap in a face that has no edge to τ's face miss.

**The rule.**
- **The face graph.** Faces are decision 270's planar faces. Two faces are adjacent when they share an edge in the position-welded mesh.
- **The path.** A tap in a face with no edge to τ's face is unfolded hinge by hinge along a fewest-hinge path (breadth first, depth at most 4) into τ's plane.
- **The choice.** When several fewest-hinge paths exist, the one that gives the smaller |q − tap| is used.
- **The rest is unchanged.** Taps in τ's face, or in a face adjacent to it, keep decision 270's single unfold.

| Variant | Cube: no-hinge texels exact (of 133) | Cube total | Wand all four | Wand BRM + Height consistent |
|---|---|---|---|---|
| Reference (raw 3D position) | 0 | 1,943 | 5,509 | 5,775 |
| First fewest-hinge path | 25 | — | 5,710 | 5,993 |
| **Nearer of the fewest-hinge paths** | **30** | **1,988** | **5,719** | **6,003** |
| The same, far taps only (own taps raw) | — | — | 5,720 | 6,002 |
| Nearer of all paths up to one hinge more | 29 | 1,987 | 5,715 | 5,999 |
| At most 2 hinges | — | — | 5,702 | 5,986 |
| q folded about the reaching seam edge, the tap unfolded into the far face | 31 | 1,990 | 5,710 | 5,993 |

**It is close but not exact.**
- On the 38 cube texels with one no-hinge tap and an exact decoded tap set, there is an exact interval for that tap's distance.
  - The nearer development lies inside it on 23.
  - On 14 it lies 0.03% to 0.5% outside, in both directions.
- The construction is therefore near a surface distance, but neither a straight-line development nor a lower bound of one.
- Of the other 95: 30 have two or more no-hinge taps, 17 have no exact interval for their one no-hinge tap, and 48 decode to a different tap set.

### 6. Wand counts after findings 3 and 5

Both rules were modelled together: snapped coverage plus the nearer fewest-hinge path, for own and far taps.

| Map | Ring before | **Ring after** | Gutter before | **Gutter after** |
|---|---|---|---|---|
| BaseColor | 5,794 | **6,034** | 2,458,666 | **3,059,257** |
| Roughness | 6,195 | **6,240** | 3,594,889 | **3,640,905** |
| Metallic | 6,247 | **6,287** | 3,587,768 | **3,640,175** |
| Height (LP-consistent) | 5,941 (6,248) | **5,989 (6,304)** | 3,349,244 | **3,586,479** |
| All four | 5,509 | **5,729** | 2,408,035 | **2,996,125** (of 3,679,663) |
| BRM + Height consistent | 5,775 | **6,013** | — | — |

The snapped coverage alone gives 5,519 ring and 2,413,024 gutter all-four texels.

**What still misses** (605 all-four ring misses):

| Class | Texels |
|---|---|
| Height operand (not a padding miss) | 284 |
| Multi-facet (finding 5 not exact) | 122 |
| Other | 96 |
| Flagged | 55 |
| Curved same-island multi-triangle | 42 |
| Reach cap | 6 |

Without the Height operand class, 321 texels are open.

## Decision

1. **Recorded, not implemented.**
   - Item 2.7 stays open, and EXC-007 stays withdrawn (decision 259).
   - No production code, semantics entry, capability, conformance case, exception or test changes. `src/export/` and `tests/export/padding_reference.py` are unchanged; the integration pass takes these rules.
2. **Identified, for the integration:**
   - **(a) Coverage.** A texel is covered when its centre is inside a triangle whose texel-space UV vertices are first rounded to the nearest 1/256 texel. On the Wand, the cube and the sphere this changes nothing but the 2 texels of finding 3. The fill rule for a centre exactly on a snapped edge is not observed (no such centre exists).
   - **(b) Multi-facet taps.** A tap in a face with no edge to τ's face is unfolded along the nearer of the fewest-hinge face paths (finding 5). It is not exact: it raises the Wand from 5,509 to 5,729 all four with (a), and the cube from 1,943 to 1,988.
   - **(c) The gutter** is decision 197's flood unchanged: its offset order and strict comparison beat every variant tried.
3. **Rejected, with the counts above:**
   - sRGB8 operand or store rounding as the cause of the BaseColor-only misses;
   - conservative coverage, and snapping at 1/16, 1/64, 1/128, 1/512 or 1/1024 texel;
   - a missing seam tie order on the Wand (0 texels);
   - a far point on an exact texel boundary on the Wand (0 texels);
   - the flood variants of finding 4;
   - decision 270's "all bevelled-cube multi-tap texels fail" (an unwelded-geometry artefact).
4. **Still open:**
   - **(a)** The exact multi-facet distance: within 0.5% of the nearer development on the cube, but not it. A true surface (geodesic) distance from q is the next candidate. It leaves 122 Wand texels and 103 of the cube's 133 no-hinge texels.
   - **(b)** The 81 flood-seed ties and the 2 non-equidistant gutter texels.
   - **(c)** The Wand's 42 curved same-island multi-triangle texels, 96 other texels and 55 flagged texels (decision 279, items (e) and (c)).
   - **(d)** The 284 Height-operand texels can be scored exactly only from a float Height recording of the Wand (EXR 32f, or the L16F document). That is the owner's call; no recording is requested here.
5. **No new recording is requested.** Owner: `phase1.25_pilot-wand` item 2.7.

## Consequences

- **The gutter needs no new rule.** Once the ring and the coverage are exact, the gutter follows, except 81 tie texels.
- **The integration changes two things:**
  - rasterised coverage with 1/256 snapping;
  - a face-path unfold for no-hinge taps.
  Together they move the Wand's measured all-four ring from 5,509 to 5,729, and its gutter from 2,408,035 to 2,996,125.
- **These need no retesting:**
  - sRGB8 store rounding for padded BaseColor;
  - alternative jump-flood orders and step sequences;
  - Wand tie orders as the cause of all-four misses.
