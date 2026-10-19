# 275. The seam ring's far taps come from the 3 × 3 far texels around floor(f − ½) in v-up texel space, exact on every decoded seam texel of the flat kernel probes; on the Wand it lifts the four-map count from 3,857 to 4,517, and 632 single-triangle seam misses are no chain over the window's taps

**Status**: accepted
**Date**: 2026-10-19
**Related Tasks**: phase1.25_pilot-wand, phase1.18_export-engine, phase1.16_export-processing-encoders

## Context

On 2026-10-18 the owner ruled that the Wand must match Painter everywhere, padding included. Exact `infinite` padding on UV islands (item 2.7 of `phase1.25_pilot-wand`) is the critical path.

**What was known:**
- A ring texel is an FMA lerp chain over at most 4 taps, weighted by quantised 1/d shares over unfolded distances (decisions 267, 268, 270). Given the taps and the order of tied shares, it is bit-exact on every decoded texel.
- **Decision 268's tap rule:** the own covered 8-neighbours plus the far island's covered texels, the 4 nearest by unfolded distance. It missed 127 of r15-p25 B's 256 texels. There, alternate rows keep a far texel 1.225 far texels along the seam and drop one at 1.275, and no along-seam window, across-seam window or 2 × 2 footprint separated the two.
- **The production measure path** (`src/export/padding.cpp`, commit 975f6e4) takes the far texels of a 6 × 6 window around the far point. On the Wand (G1 pilot) the brief's classification of its 6,334 ring texels left 1,552 "another subset of the 8 nearest" misses (1,408 single-triangle 4-tap seam texels) and 728 "none of the 8 nearest" misses (548 single-triangle 4-tap seam texels).

**This pass asked which far texels a seam ring texel may use.** The far point f is the ring point q mapped across the seam into the far island, in that island's texel space (u·W, (1 − v)·H, centres at + ½).

**The data**, all read from the private store:
- **Decision 266's kernel probes** (commit c1f30c3): the r1 `infinite` exports of the five ramp probes and the four atlas probes, with decisions 268 and 270's tap decodes (`pad268/`, read only). These codes are impulses, so each tap is read with no ambiguity.
- **The Wand v1's r1 PNG 16 maps** (`wand-v1`): BaseColor, Roughness, Metallic and Height. Each is padded in its document format, as the earlier scratch scripts did: BaseColor as sRGB8 with linear operands, Roughness and Metallic as 8-bit UNORM, Height as 16-bit.

**How it ran:**
- `padding.cpp`'s ring geometry (owners, islands, planar faces, hinges, far point) was ported to Python. On all 6,334 Wand ring texels it gives the same coverage and the same first 4 candidates as the C++ path.
- **Scoring.** A texel counts when some order of its exactly tied shares (relative 10⁻⁹) reproduces Painter's codes; the order of ties stays decision 273's. "All four" means every channel of the four maps.
- On the CPU with numpy, from the private store: no Painter, no GPU and no writes to Assets3D, within the 2.5-hour box. The scripts stay in private scratch (`pad275/`), because they read oracle values.

## Findings

### 1. The far window: 3 × 3 texels around floor(f − ½) in v-up texel space

**The rule.**
1. Let f = (f_u, f_v) be the far point in the far island's texel space, v down, centres at + ½.
2. The window's centre column is c = floor(f_u − ½), and its centre row is r = ceil(f_v − ½).
3. A far texel is a candidate when it is covered, lies in the far island, and |col − c| ≤ 1 and |row − r| ≤ 1.

**Read in v-up texel space with centres on integers**, (u·W − ½, v·H − ½), the rule is simpler: the 3 × 3 block around the truncated (floor) far texel coordinate. The centre is the texel at or below-left of f, which is not the texel that contains f. The window is therefore off-centre by half a texel toward −u and −v. This is what decision 268's r15-p25 B rows saw as an asymmetric along-seam window.

The taps are then decision 268's: the 4 nearest of the own covered 8-neighbours and this window, by unfolded distance.

**Ramp probes** (interior seam-ring texels, both rings of all five probes):

| Far pool | Exact tap sets |
|---|---|
| Any covered far texel (decision 268) | 2,429 / 2,560 |
| Decision 262's bracket, two lines along the seam | 2,173 / 2,560 |
| 3 × 3 around the containing texel floor(f) | 2,427 / 2,560 |
| 4 × 4 around f | 2,427 / 2,560 |
| **3 × 3 around floor(f − ½), v up** | **2,560 / 2,560** |
| The same 3 × 3 with the v convention flipped (v down) | 2,300 / 2,560 |

- r15-p25 B is 256 of 256, against decision 268's 127.
- The 19 decoded seam-corner texels of the ramps are 19 of 19, against 13 with any far texel.

**Both bounds are needed:**
- A window one texel wider toward +u (columns up to c + 2) loses r2-p0 A and r2-p25 A texels.
- A window moved half a texel in v (rows r − ½ … r + 2½) loses all of r15-p0 A, r15-p25 A, r2-p0 B and r2-p25 B.
- Toward −u and +v (v down) the ramps do not bound the window. The 3 × 3 is the smallest reading that fits, and it is the reading the Wand prefers (finding 3).

**Atlas flat seam items** (`seam-r1-single`, `-r1-turn90`, `-r1.5`, `-r1.5-single`, `-r2-turn90`, `-r2-single-b`, `-r1.25`, `-r1-turn30`). The turned items rotate the far island against the texel grid, so they test the axes.

| Probe | Any far texel | 3 × 3 around floor(f − ½), v up |
|---|---|---|
| `atlas-512` | 75 / 87 | **87 / 87** |
| `atlas-1024` | 75 / 87 | **87 / 87** |
| `atlas-2048` | 75 / 87 | **87 / 87** |
| `atlas-1024-moved` | 73 / 86 | 84 / 86 |

- **The two moved-atlas misses are boundary cases.** Both sit at an exact half-texel f (`seam-r1-single` (468, 25), f = (458.5, 25.5), and `seam-r1-turn90` (491, 27), f_v = 26.5).
  - There floor(f − ½) lands exactly on an integer, and the moved atlas's 1-ulp vertex changes tip it to the other side.
  - Painter's choice on the moved atlas is the window one row lower, which is what a float32 f just below the integer gives.
  - So the rule holds, and the rounding of f at exact boundaries is open (open item (b)).
- **On the unmoved atlases**, f is snapped to 2⁻²⁰ before the floor. Without the snap, double-precision noise at those same half-texel points loses 2 texels per probe.

### 2. The far triangle is not gated by "q beyond the seam edge"

- **Corner ring texels read the far island too.** At each 1-texel island of `seam-r1-single`, and at the corners of `seam-r2-single-b` and `seam-r1.5`, the ring texel lies beyond a non-seam edge and on the own side of the seam line. Painter still takes far taps there.
- **The production path misses them.** It searches the far island only across those of τ's edges whose barycentric is negative.
- **What fits.** The far point comes from the far island's map at q, whether q lies beyond the seam or not:
  - flat items: the far triangle's affine map, extrapolated;
  - folded items: q folded about each seam edge of the own island.

| Seam gating, with finding 1's window | Flat items, each unmoved atlas | Folded items, `atlas-512` (`-fold90` r1 and r2, `-fold53`) |
|---|---|---|
| Only τ's edges that q lies beyond (production) | — | 19 / 30 |
| Any own-island seam edge that q lies beyond | 67 / 87 | 27 / 30 |
| **Every own-island seam edge, no side test** | **87 / 87** | **27 / 30** |

- **The 3 folded misses** are on `seam-r1-turn90-fold53` (the atan(4/3) fold).
  - (236, 161) takes 3 taps where 4 are in the window.
  - At (252, 166) and (254, 166), Painter keeps an own texel two columns out rather than a far one.
  - They are open (open item (c)).
- **On the Wand the gate barely matters:**
  - production gate: 4,517;
  - every seam edge of the own triangles: 4,532;
  - τ's seam edges without the side test: 4,516.
- **Recorded, not decided.** Only the kernel probes separate the gates, and on them "every own-island seam edge" is the only one that fits. How far from q a seam edge may lie is not tested.

### 3. On the Wand the window is the best pool, and it removes most of the tap-set misses

All 6,334 ring texels. Here "4 nearest" is over the own covered 8-neighbours and the given far pool:

| Far pool | Height | BaseColor | Roughness | Metallic | **All four** |
|---|---|---|---|---|---|
| Production 6 × 6 window | 5,177 | 4,026 | 4,959 | 5,339 | 3,857 |
| **3 × 3 around floor(f − ½), v up** | **5,281** | **4,694** | **5,138** | **5,415** | **4,517** |

The other windows were scored on the 6,161 ring texels with a far candidate among their 8 nearest (all four maps):

| Far pool | All four |
|---|---|
| **3 × 3 around floor(f − ½), v up** (columns floor, rows ceil, v down) | **4,489** |
| 3 × 3 around the containing texel floor(f) | 3,832 |
| Any far texel of the island within 5 texels | 3,829 |
| 5 × 5 around floor(f − ½) | 3,829 |
| Rows floor(f_v − ½) (both axes floor, v down) | 3,697 |
| Columns ceil(f_u − ½) (both axes ceil, v down) | 3,696 |
| Columns ceil, rows floor | 3,193 |

- **The same offset wins on real geometry.** It is the only one of the six readings that improves on the production window. The Wand's islands lie at arbitrary angles to the texel grid, so this confirms the axis convention independently of the probes.
- **The gain is all in seam texels.** Single-triangle 4-tap seam texels go from 3,733 to 4,379 of about 5,850. Multi-triangle seam texels go from 96 to 109 of 308.
- **The earlier figures are not comparable.** The brief's 3,776 all-four texels took production's comparator order, and this pass frees the order of exact ties.

### 4. What is left on the Wand is not another subset of the window's taps

These are the 1,472 single-triangle seam texels the window misses:

| Which maps fail | Texels |
|---|---|
| All four | 678 |
| Some maps, Height exact (533 of them include BaseColor) | 544 |
| Height and some others, not all four | 250 |

- **The 544 texels where Height is exact** point at the 8-bit and sRGB domains: decision 274's padding domain, not this rule.
- **Of the 678 all-four misses:**
  - none is fixed by a near-tie order (10⁻³) or by fewer taps;
  - 46 are fixed by another 4-subset of the window pool;
  - **632 match no 4-subset of the 9 nearest window candidates.**
  - **They are not slightly-off weights either.** The search took the 4 window taps in every order, with level codes within ±12, ±4 and ±2 of the predicted ones (10, 8 and 6 bits). No such code set reproduced all four maps on 150 sampled residuals, nor Height alone on 60.
  - So those values are not a chain over these 4 taps at all. Either a tap lies outside the pool (a different far point or far island), or the tap values differ.
- **The positions are not the cause.** 1,255 of the 1,472 misses have every far tap in the planar face of the far triangle J that shares the seam edge, hinged correctly. A far tap in another face is used at its 3D position (production's fallback). Replacing that fallback did not help:
  - J's affine extrapolation, unfolded about the seam hinge: 29 of 300 sampled misses;
  - the tap's own triangle unfolded about the seam hinge: 38;
  - distances in τ's texel space: 24;
  - a seam-edge similarity in UV: 17.
- **What remains open** is where the 632 residuals' values come from (open item (a)). They are single-triangle texels whose window taps all lie in one hinged face, so they are what the next pass should take, decoding taps freely rather than fitting weights.

## Decision

1. **Recorded, not implemented.**
   - Item 2.7 stays open, and EXC-007 stays withdrawn (decision 259).
   - No production code, semantics entry, capability, conformance case, exception or test changes. `src/export/padding.cpp` belongs to decision 274's pass this round.
2. **Identified, for the integration:**
   - **The window.** The seam ring's far candidates are the far island's covered texels in the 3 × 3 block with columns floor(f_u − ½) ± 1 and rows ceil(f_v − ½) ± 1 (v down). That is the 3 × 3 around floor(f − ½) in v-up texel space.
   - **The taps** are the 4 nearest of the own covered 8-neighbours and that window, by unfolded distance.
   - **Where it is exact:**
     - on every decoded seam texel of the flat kernel probes: ramps 2,560 + 19 corners, flat atlas items 87 per unmoved atlas;
     - on 84 of 86 on the moved atlas, where the 2 misses are exact half-texel boundaries.
   - It replaces decision 268's "any far texel" and production's 6 × 6 window. It closes decision 268's open item (b), the r15-p25 B window, and the r15-p25 B half of decision 262's open item (b).
   - **The far point** is taken across every seam edge of the own island, without testing which side of the edge q lies on (finding 2). That is exact on the flat atlas items. On the Wand it is +15 texels and within noise.
3. **Rejected, with the counts above:**
   - any covered far texel;
   - the 2-line bracket (decision 262);
   - the 2 × 2 footprint (decision 268);
   - the 3 × 3 around the containing texel floor(f);
   - 4 × 4 and 5 × 5 windows;
   - the window with either axis's offset flipped;
   - gating the far island by "q beyond τ's seam edge" for corner texels.
4. **Still open:**
   - **(a)** The Wand's 632 single-triangle seam texels that no chain over their 4 window taps reproduces, even with nearby codes (finding 4).
   - **(b)** The rounding of f at an exact half-texel. It decides 2 moved-atlas texels and needs the float32 recipe of f. The candidate is decision 273's float32 position arithmetic (texel-centre UVs, V2-based inverse matrix with the GPU reciprocal, box-normalised FMA interpolation), carried through the fold into the far triangle. It was not tested here.
   - **(c)** The 3 `seam-r1-turn90-fold53` texels, and how far from q a seam edge may still feed the window.
   - **(d)** The Wand's 544 Height-exact misses, for decision 274's domain work, and the 25 own-only single-triangle misses.
   - **(e)** The order of tied shares, which stays decision 273's.
5. **No new recording is requested.** The next step is offline: decode the taps of finding 4's 632 residual texels from the Wand's Height without a pool restriction. Owner: `phase1.25_pilot-wand` item 2.7.

## Consequences

- **The tap selection is settled for seams in flat or hinged geometry.** What the measure path still misses on the Wand is in the domains (544 texels) or in values that no chain over the window's taps gives (632 texels), not in a choice among the window's taps.
- **The integration gets a smaller pool.** Production's 6 × 6 far window becomes a 3 × 3 at the half-texel-offset centre, and corner ring texels search the far island too.
- **These need no retesting** as the seam far window:
  - windows centred on f or on floor(f);
  - brackets, 2 × 2 footprints, 4 × 4 and 5 × 5 windows;
  - other half-texel conventions.
