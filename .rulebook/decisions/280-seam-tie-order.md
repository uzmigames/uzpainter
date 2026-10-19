# 280. The seam tie order: own taps by decision 273's comparator then a fixed neighbour order (sides along u, then sides along v, then diagonals), far taps by their float32 distance from the ring point then a fixed far-window order (the 2 × 2 block at floor(f − ½) first); a ring with no own tap among its kept candidates is not a copy

**Status**: accepted
**Date**: 2026-10-19
**Related Tasks**: phase1.25_pilot-wand, phase1.18_export-engine, phase1.16_export-processing-encoders

## Context

On 2026-10-18 the owner ruled that the Wand must match Painter everywhere, padding included. Exact `infinite` padding on UV islands (item 2.7 of `phase1.25_pilot-wand`) is the critical path.

**What was known:**
- A ring texel is an FMA lerp chain over at most 4 taps, weighted by quantised 1/d shares (decisions 267, 268, 270). Given the order of exactly equal shares, it is bit-exact.
- **Straight edges are solved** (decision 273): own diagonals compare by float32 position arithmetic, and an exact tie goes toward +u on rows and +v on columns.
- **The seam order was open** (decisions 268 (a), 271 (b), 273 (b)). Decision 271 read the seam own-diagonal ties as splitting both ways even on exact r2 geometry.
- **The kernel at commit 22acbc8** (`src/export/padding.cpp`, and its Python twin `tests/export/padding_reference.py`) sorts equal distances as follows: own taps before far taps; own taps by decision 273's comparator, then +u, +v; far taps by +u, then +v.
- The brief listed these probe misses as likely tie order: `ramp-r2-p0` 128 of 1,544 ring texels, `concave-fold` 756 seam texels, `concave-shape` 545 + 508, `concave-fine` about 500, `atlas-512` 3,140 − 2,833.

**The data**, all read from the private store: the r1 `infinite` exports (24 channels) of
- decision 266's kernel probes: `ramp-{r1-p0, r2-p0, r2-p25, r15-p0, r15-p25}`, `tie-512` and `atlas-{512, 1024, 2048, 1024-moved}`;
- decision 272's `tie-sweep-seams-{centred, offcentre, box320}`;
- decision 278's `concave-{fold, shape, fine}`;
- the Wand v1's r1 PNG 16 maps (`wand-v1`).

**How the order was read.**
- Every ring texel of the reference ring (commit 22acbc8) was taken with its candidates in tap order.
- Every permutation of the exactly equal distances among its chain's taps was run through decision 268's chain. The permutations that give Painter's 24 channels bit for bit are Painter's possible orders.
- A tied pair is **visible** when those permutations all put one tap first while some other permutation puts the other first. It is **invisible** when both orders give the same bits.

**How it ran.** On the CPU with numpy and scipy: no Painter, no GPU, no writes to Assets3D. Every comparator is float32, each operation correctly rounded, with the recording GPU's reciprocal and square root (`tools/parity/fit/hwmath.py`). Each probe's mesh is its fixture OBJ. The scripts stay in private scratch (`pad280/`), because they read oracle values. Clean room: black-box fits of our own recordings only.

## Findings

### 1. Most seam ties are invisible, and the brief's probe misses are mostly not the tie order

**Ties per class.** These are all ramps, sweeps, atlases and `concave-shape` together:

| Pair class | Visible | Invisible | The 22acbc8 order right |
|---|---|---|---|
| Own / own, ring texels without far taps | 25,082 | 355 | 24,576 |
| Own / own, seam ring texels | 2,449 | 2,042 | 1,651 |
| Far / far | 4,543 | 3,239 | 775 |
| Own / far | 8 | 0 | 8 |

**The ramps.**
- Every r2-p0 own-diagonal tie (254) is invisible, and so are its 768 four-way far ties.
- The r2-p25 and r15-p25 own-diagonal ties (127 and 255) are invisible too.
- Only one r2-p0 far/far pair is visible, and r2-p25's 128 far/far pairs. The 22acbc8 order already gets those 128 right.
- So decision 271's split of 112 / 142 was read from decoded weights that are in fact equal. The ramps' seam ties never decide a bit.

**What the brief's misses are:**

| Probe | The brief's misses | What they are |
|---|---|---|
| `ramp-r2-p0` | 128 seam texels | 127 are finding 4's tap-count bug; 1 is a far/far order |
| `ramp-r2-p25` (not in the brief) | 127 | finding 4's tap-count bug |
| `concave-fold`, `-shape`, `-fine` | 756, 545 + 508, 498 | **not the order**, see below |
| `atlas-512` | 307 | 197 are fixed by this decision (7 of them by finding 4). Of the other 110, 103 have no order of the kept candidates that fits: the pole tap set (decision 270, finding 5) |

**The concave probes are not the order:**
- They have no visible seam tie.
- No subset of up to 4 kept candidates, in distance order with ties free, reproduces their misses.
- Their decoded weights are off 1/d. For example, a far share of 0.5968 against 0.5977 at `concave-fold` (319, 15). So the far distance across a concave hinge differs from the unfolded one.
- **A pointer only.** Measuring those far taps in raw 3D from q (no unfolding) lifts the seam-exact texels of `concave-fold` from 570 to 1,103 of 1,326, of `-fine` from 1,910 to 2,011 of 2,408, and of `-shape` from 609 to 642 of 1,154. That is not a rule (open item (e)).

### 2. Own taps: decision 273's comparator, then a fixed neighbour order

**The order.** Within a group of exactly equal distances, own taps come first. They are ordered by decision 273's comparator distance (the ring texel extrapolated through the tap's own triangle). An exact float32 tie then follows a fixed order of the 8-neighbour offsets.

In v-up offsets (du, dv) from the ring texel:
- **sides along u** (±1, 0) come before **sides along v** (0, ±1);
- **sides come before diagonals:**
  - (0, +1) before (+1, +1) and (−1, +1);
  - (0, −1) before (+1, −1);
- **among diagonals,** +u comes first within a row and +v first within a column. So (+1, +1) is first, (−1, −1) is last, and the straight edge keeps decision 273's +u / +v.

A total order consistent with every visible pair is (+1, 0), (−1, 0), (0, −1), (0, +1), (+1, +1), (+1, −1), (−1, +1), (−1, −1).

**What the data leave open:**
- (+1, 0) against (−1, 0);
- (0, +1) against (0, −1);
- (+1, −1) against (−1, +1).

These pairs never tie visibly.

**Where the 22acbc8 order goes wrong.** It breaks ties by +u then +v. At a corner ring texel, where two sides tie, Painter takes the side along u first whichever way it points. Examples are the sweep V-gap copies and the atlas's `diamond-4`. On sheared UVs (`pole-8`), a side can tie a diagonal in 3D, and Painter takes the side.

**Counts.** Over the 8! fixed orders, the best explain 15,919 of 15,921 float-tied own pairs. The two exceptions are one (+1, +1) / (+1, −1) pair and one (−1, +1) / (−1, −1) pair.

### 3. Far taps: a float32 distance from the ring point, then a fixed far-window order

**The distance.** A far tap's comparator distance is float32 |q_E − P|, then FMA squared distance and the GPU square root:
- **q_E** is decision 273's position of the ring texel's centre through E: box-normalised vertices, inverse-matrix UV barycentrics with the GPU reciprocal, and fma(l₂, P₂, fma(l₀, P₀, l₁·P₁)). E is the own-island triangle whose seam edge brought the tap into its window (the first such edge).
- **P** is decision 273's position of the far tap's texel centre through its own triangle.
- **Folded faces.** When P's face differs from E's, P is rotated into E's plane about the shared hinge edge, in float32. The recipe used is in finding 5.

**The window order.** An exact float32 tie follows a fixed order of the tap's offset in decision 275's window, in v-up texel space, from b = floor(f − ½):
- the 2 × 2 block at b first, row by row: (0, 0), (+1, 0), (0, +1), (+1, +1);
- then (0, −1) and (+1, −1);
- then the −u column, with (−1, 0) before (−1, +1).

A total order consistent with every visible pair is (0, 0), (+1, 0), (0, +1), (+1, +1), (0, −1), (+1, −1), (−1, 0), (−1, +1), (−1, −1).

**What it means.** The 22acbc8 order (+u, then +v in the image) is the reverse on most far pairs.
- On the exact sweep G1 copies, in every 3D turn, Painter leads with the −u texel of a horizontal pair (120 of 120).
- On r2-p25, it leads with the texel whose row comes first in the window.
- At the poles, the tied far taps sit diagonally across the window. Painter leads with the earlier window position, whatever their image direction.

**Counts.** Over the 9! fixed window orders, the best explain 2,976 of 2,976 float-tied far pairs. Here the comparator is the raw 3D distance, without the fold.

**The distance does real work.** On the k-ulp and scale sweeps (G3, G4, H3, H4), the float32 distance decides the order where the window order alone would not. For example, the window order alone misses 44 of 1,251 `centred` far pairs, and the distance gets them all.

**Rejected,** with the far/far pairs of the three sweeps (3,765) and `atlas-512` (189):

| Comparator for the far tap, then the window order | Sweeps | `atlas-512` | `atlas-1024-moved` (84) |
|---|---|---|---|
| **q_E to P, unfolded in float32 (the rule)** | **3,763** | **183** | **77** |
| q_E to P, raw 3D | 3,709 | 185 | 77 |
| q through τ to P, unfolded in double, then rounded | 3,761 | 184 | 71 |
| q through τ to P, through the far triangle J instead of the tap's own triangle | 3,614 | 185 | 77 |
| The distance in far UV from the far point f | 3,316 | 178 | — |

### 4. A ring whose kept candidates hold no own tap is not a copy

**The bug.** `TapCount` in `padding.cpp` and `tap_count` in the reference make the chain a copy when the nearest tap lies at distance 0 relative to the nearest own candidate. When the 8 kept candidates are all far taps, the nearest own distance is infinite, so the ring texel becomes a 1-tap copy.

**Where it bites.** Ring B of r2-p0 and r2-p25: 4 far texels at 0.0276 and 4 at 0.0618 fill the 8 kept slots there, and Painter takes 4 taps.

**The fix used here.** Such a list is never a copy (the scratch scale is the farthest kept distance). It fixes 127 texels of each of r2-p0 and r2-p25, and 37 Wand texels, of which 28 become exact in all four maps.

### 5. Counts

Ring texels bit-exact on all 24 channels. The Python reference reproduces the C++ kernel's probe counts at 22acbc8 (`ramp-r2-p0` 1,416, `atlas-512` 2,833, `concave-*` 6,848 / 14,441 / 11,742) and its Wand counts.

| Probe | Ring texels | 22acbc8 | + tap-count fix | **+ this order** | Seam texels exact (after) |
|---|---|---|---|---|---|
| `ramp-r1-p0` | 2,056 | 2,056 | 2,056 | **2,056** | 520 / 520 |
| `ramp-r2-p0` | 1,544 | 1,416 | 1,543 | **1,544** | 390 / 390 |
| `ramp-r2-p25` | 1,544 | 1,417 | 1,544 | **1,544** | 390 / 390 |
| `ramp-r15-p0` / `-p25` | 2,568 each | 2,568 | 2,568 | **2,568** | 646 / 646, 643 / 643 |
| `tie-512` | 780 | 780 | 780 | **780** | — |
| `atlas-512` | 3,140 | 2,833 | 2,840 | **3,030** | 724 / 815 |
| `atlas-1024` | 3,140 | 2,831 | 2,838 | **3,028** | 722 / 815 |
| `atlas-2048` | 3,140 | 2,832 | 2,839 | **3,029** | 722 / 815 |
| `atlas-1024-moved` (held out) | 3,140 | 2,823 | 2,831 | **2,929** | 644 / 818 |
| `tie-sweep-seams-centred` | 7,805 | 6,279 | 6,301 | **7,663** | 2,981 / 2,981 |
| `tie-sweep-seams-offcentre` | 7,805 | 6,264 | 6,286 | **7,653** | 2,972 / 2,984 |
| `tie-sweep-seams-box320` | 7,805 | 6,571 | 6,611 | **7,574** | 2,893 / 2,938 |
| `concave-fold` / `-shape` / `-fine` | 7,760 / 15,494 / 12,240 | 6,848 / 14,441 / 11,742 | unchanged | unchanged | 570 / 609 / 1,910 |

**What is left on each probe:**
- **The sweeps.** Their misses are 142 (`centred`), 152 (`offcentre`) and 231 (`box320`) ring texels, and on all but 2 of them no order of the kept candidates fits:
  - the V-gap copies (H1 to H4): 142, 142 and 213. These are decision 279's open items (a) and (b), the far point's rounding at V-gaps;
  - the folded G2 copies: 10 on `offcentre` and 15 on `box320`, a fold distance question;
  - one G4 texel on `box320`;
  - the 2 left are `box320` G2 fold90 far orders (finding 6).
- **The atlases.** The misses are the pole tap set (decision 270, finding 5), the fold recipe (finding 6) and a few own exceptions.

**Tied pairs under the rule** (all ramps, sweeps, atlases and `concave-shape`):

| Class | The rule | The 22acbc8 order |
|---|---|---|
| Own / own, no far taps | 25,078 / 25,082 | 24,576 |
| Own / own, seam | 2,448 / 2,449 | 1,651 |
| Far / far | 4,516 / 4,543 | 775 |
| Own / far (own first) | 8 / 8 | 8 |

**Held-out check.** The order relations were fitted on the three sweep boxes, and their transitive closure was then tested on the other probes:

| Pairs | Held-out float-tied pairs | Predicted | Contradicted | Not covered by the sweeps |
|---|---|---|---|---|
| Own | 10,929 | 10,500 | 2 | 427 |
| Far | 665 | 269 | 0 | 396 |

The uncovered pairs are relations the sweeps never tie: side against diagonal, the r2-p25 pairs and the pole pairs. They are fitted on those probes and contradict nothing.

**The Wand,** all 6,334 ring texels, through the reference ring in Python with the C++ kernel unchanged. The 22acbc8 column reproduces `wand_counts.py` on the C++ kernel (BaseColor 5,794, Height 5,941, all four 5,509) and `lp_gate.py` (6,248).

| | BaseColor | Roughness | Metallic | Height | All four | Height LP-consistent |
|---|---|---|---|---|---|---|
| 22acbc8 | 5,794 | 6,195 | 6,247 | 5,941 | 5,509 | 6,248 |
| + tap-count fix | 5,824 | 6,203 | 6,254 | 5,949 | **5,537** | 6,250 |
| + this order | 5,824 | 6,203 | 6,254 | 5,949 | **5,537** | 6,250 |

The new order changes no Wand chain. Its UVs give no exactly equal distances.

### 6. What is not pinned

- **Folded far taps** (27 of 4,543 far pairs):
  - `pole-8-pyramid` (6 per atlas), `corner-r1-r1.5-r2` and the moved atlas's cube corners (7);
  - `tie-sweep-seams-box320` G2 fold90 (2).
  - Finding 3's float32 rotation is the best of those tried, which were:
    - the reference's hinge formula in float32 (unit vectors by GPU sqrt and division, or by GPU rsqrt);
    - the double unfold, rounded;
    - no unfold.
- **Own exceptions** (5 pairs):
  - `diamond-4` (439, 28), a multi-triangle texel, at each of 512, 1024 and 2048. There Painter takes the side along u although decision 273's comparator puts the other side 1 ulp nearer.
  - The moved-atlas texel (326, 162), decision 273's open item (a), and its seam neighbour (321, 162). On both, the two diagonals' d² differ by 1 ulp, the GPU square root merges them, and Painter takes the d² order.

## Decision

1. **Recorded, not implemented.**
   - Item 2.7 stays open, and EXC-007 stays withdrawn (decision 259).
   - No production code, semantics entry, capability, conformance case, exception or test changes. `src/export/padding.cpp` and `tests/export/padding_reference.py` are unchanged; another pass integrates this rule.
2. **Identified, for the integration** (`Ordered` and `TapCount` in `padding.cpp`, `_ordered` and `tap_count` in the reference):
   - **(a) The group.** Within a group of exactly equal distances, own taps come before far taps, as now.
   - **(b) Own taps** are ordered by decision 273's comparator, then finding 2's neighbour order (v-up): (+1, 0), (−1, 0), (0, −1), (0, +1), (+1, +1), (+1, −1), (−1, +1), (−1, −1). This replaces "+u, then +v".
   - **(c) Far taps** are ordered by finding 3's float32 distance from q_E, then finding 3's window order (v-up, from floor(f − ½)): (0, 0), (+1, 0), (0, +1), (+1, +1), (0, −1), (+1, −1), (−1, 0), (−1, +1), (−1, −1). This replaces "+u, then +v".
   - **(d) Copies.** A kept candidate list with no own tap is never a copy (finding 4).
   - **What to refuse.** Production refuses, as `NotYetSupported` naming decision 280, a ring texel whose chain holds an exactly tied pair that the data leave open:
     - own pairs (+1, 0) / (−1, 0), (0, +1) / (0, −1) and (+1, −1) / (−1, +1);
     - a far tie between taps in different hinged faces of a folded seam (finding 6);
     - an own / far tie whose order changes the chain's bits.

     Decision 001: nothing unproven is guessed.
   - **Where it is exact:**
     - every visible seam tie of the ramps and the sweeps' flat copies;
     - 4,516 of 4,543 far pairs and 27,526 of 27,531 own pairs over all probes;
     - the probe ring counts of finding 5.
   - It closes decision 268's open item (a), decision 271's open item (b) and decision 273's open item (b).
3. **Rejected, with the counts above:**
   - +u then +v for far ties (775 of 4,543);
   - +u then +v for own side / side ties at corners;
   - comparing far taps by UV distance from the far point;
   - measuring far taps through the far triangle J instead of their own triangle;
   - reading the ramps' seam ties as visible (decision 271's split was decoding noise);
   - the tie order as the cause of the concave probes' seam misses.
4. **Still open:**
   - **(a)** The float32 recipe of the fold for far taps in another hinged face (finding 6, 27 far pairs).
   - **(b)** The 5 own exceptions of finding 6.
   - **(c)** The undetermined pairs of the two fixed orders.
   - **(d)** Own against far at equal distance, seen on only 8 pairs (own first).
   - **(e)** The concave probes' seam misses (fold 756, shape 545, fine 498) and own-only misses (fold 156, shape 508). They are a far-distance question across concave hinges, not order (finding 1). Raw 3D from q is a lead.
   - **(f)** The rings that no order of the kept candidates fits: the sweeps' V-gap boundary rounding (decision 279's open item (a)) and the atlas pole tap set (decision 270, finding 5).
5. **No new recording is requested.** Owner: `phase1.25_pilot-wand` item 2.7.

## Consequences

- **The seam tie order is now a rule.** It is exact on the flat probes and on all but 27 folded far pairs. The integration changes `Ordered`'s two fallback keys, adds the far tap's float32 distance, and fixes `TapCount`.
- **On the Wand, only the `TapCount` fix moves counts:** all four 5,509 → 5,537. Its remaining classes belong to decision 281's pass.
- **These need no retesting** as the seam tie order:
  - +u / +v fallbacks for far taps;
  - UV-space far distances;
  - far-triangle (J) positions;
  - reading tie orders from NNLS-decoded weights. A tie is read only from the bits of the 24-channel chain.
