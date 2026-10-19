# 282. A hinge is unfolded only when it is folded past decision 278's gate (float32 normal dot ≤ 0.985); a shallower hinge is measured in plain 3D, concave or convex, also along a development path; near-tied taps are ordered by float32 comparators, a far tap's with q_E folded into the far plane

**Status**: accepted
**Date**: 2026-10-19
**Related Tasks**: phase1.25_pilot-wand, phase1.18_export-engine, phase1.16_export-processing-encoders

## Context

On 2026-10-18 the owner ruled that the Wand must match Painter everywhere, padding included. Exact `infinite` padding on UV islands (item 2.7 of `phase1.25_pilot-wand`) is the critical path.

**What was open:**
- **Decision 280, open item (e).** The concave probes' seam misses were a far-distance question, not tie order: `concave-fold` 756 of 1,326 seam texels, `concave-shape` 545 seam and 508 own-only, `concave-fine` 498. Measuring the far taps across a concave hinge in raw 3D from q (no unfolding) was a lead, not a rule.
- **Decision 280, open item (a).** 27 far tie pairs across a folded hinge (`pole-8-pyramid`, the moved atlas's poles, `box320` G2 fold90). Decision 270's unfolding was bit-exact on single-triangle pole and cube-corner texels, so the rule had to reconcile both.
- **Decision 284, open item (a).** Whether a far-side hinge is unfolded: the cube wanted a rigid rotation across 7.7° to 16°, the Wand's (752, 1454) a development across 14.6°.
- **Decision 288.** Its rule (c) measures same-island taps in another face in plain 3D (the sphere), and it left 227 `bevelled-cube` texels with single-hinge convex far taps across a bevel seam.

**The data**, all read from the private store: the r1 `infinite` exports (24 channels) of decision 266's kernel probes (ramps, `tie-512`, `atlas-{512,1024,2048,1024-moved}`, `sphere-256`, `bevelled-cube-256`), decision 272's sweep seams boxes and decision 278's `concave-{fold,shape,fine}`. Each concave copy's fold angle, shape and tilt come from `request_fixtures.fold_layout`. The Wand is its v1 r1 PNG 16 maps, scored as in decision 280.

**How it ran.**
- **The model** is `tests/export/padding_reference.py` at main (decisions 278 to 281 integrated), subclassed in private scratch (`pad282/hring2.py`, `s282.py`, `wand2.py`). The subclass takes `candidates` and `_ordered` from the reference's own source, with hooks for the tap distance and the far comparator. The first pass ran on 4b51eec's reference (`hring.py`) and gave the same probe counts.
- **Scoring.** A ring texel counts when all 24 channels are bit-exact. The Wand counts all four maps exact, as in decision 280.
- **Effective distances.** For one-far-tap texels, the far distance was solved from decision 278's decoded weights through decision 268's code grid (`invert.py`), then compared with the candidate measures.
- On the CPU with numpy: no Painter, no GPU, no writes to Assets3D. The scripts stay in private scratch, because they read oracle values. Clean room: black-box fits of our own recordings only.

## Findings

### 1. Shallow hinges are not unfolded; folded ones are, whichever way they fold

Each concave copy was scored with every far tap measured one way. Seam texels exact:

| Probe, fold class | Seam texels | Unfolded (decision 270) | Raw 3D from q | **Gated** |
|---|---|---|---|---|
| `fold`, concave below 9.94° | 1,008 | 272 | 1,008 | **1,008** |
| `fold`, concave at or above 9.94° (corner texels in front of J) | 230 | 219 | 16 | **230** |
| `fold`, convex −6° | 14 | 5 | 14 | **14** |
| `fold`, convex −10° to −45° | 60 | 60 | 0 | **60** |
| `shape`, concave below 9.94° | 624 | 130 | 616 | **624** |
| `shape`, concave at or above 9.94° | 530 | 479 | 26 | **530** |
| `fine`, concave 9.75° to 9.93° | 266 | 19 | 266 | **266** |
| `fine`, concave 9.94° to 178° | 268 | 268 | 122 | **268** |
| `fine`, convex −9.75° to −9.93° | 266 | 19 | 266 | **266** |
| `fine`, convex −9.94° to −178° | 1,608 | 1,604 | 0 | **1,604** |

**The rule.** For a tap across a hinge (τ's face to the tap's face, or each hinge of decision 281's development path), let d = the float32 dot of the two faces' unit normals (decision 278's `face_normal`).
- **d > 0.985** (folded less than about 9.94°): the hinge is not unfolded. The tap keeps its 3D position.
- **d ≤ 0.985:** the hinge is unfolded as before (decision 270).

**What it does not depend on:**
- **The sign of the fold.** Concave and convex switch together.
- **Decision 278's side test.** In front and behind switch together.
- **The shape.** Apex offset, depth, quad diagonal, scale and tilt do not move it.

The switch lies in decision 278's own bracket. On `fine`, 9.93° is raw and 9.94° is unfolded, in both signs. So the gate and the unfolding are one test: a hinge folded past the gate is a fold, and a shallower one is treated as flat ground.

**The effective distances agree.** On the 1,637 one-far-tap texels, the far distance was solved from the decoded codes as an interval. Below the gate it holds the raw 3D distance on 556 of 556 texels, and the unfolded one on only 325. At or above the gate it holds the unfolded distance on 1,081 of 1,081, and the raw one on only 277. At `concave-fold` (319, 15) (9.25°), the code 473 needs d_far in [0.95410, 0.95701]: raw 3D gives 0.95410 (inside), unfolding gives 0.95197 (outside).

**Rejected,** on the same copies: the geodesic through the infinite hinge line (fold 353, shape 537, fine 306 seam texels), the far tap projected onto τ's plane (193, 77, 38), raw 3D everywhere (1,052, 642, 654), and unfolding everywhere (570, 609, 1,910).

### 2. Along a development path, each hinge is gated too

**What the reference does.** Decision 281 develops a tap with no hinge to τ's face along the fewest-hinge face path, unfolding every hinge.

**Where it fails.** On `concave-fold`'s 37°-oblique copies, B's two triangles round to two faces about 10⁻⁶ apart. So a tap in B's second triangle has no hinge to A. Painter's codes need the rotation about the seam edge alone: (27, 85) needs d in [1.7720, 1.7839]; the seam-edge rotation gives 1.776585, and the raw position 1.768730.

**The rule.** Gating each hinge of the path explains it: the near-0° hinge between B's two faces is not unfolded.

| No-hinge tap | `concave-fold` | `bevelled-cube-256` | Wand all four |
|---|---|---|---|
| Decision 281's development, every hinge unfolded | 7,730 | 1,978 | 5,824 |
| Decision 284's rigid rotation about the seam edge | 7,759 | 1,992 | 5,801 |
| **The development, shallow hinges kept** | **7,759** | **1,996** | **5,827** |

This also reconciles decision 284's open item (a):
- the cube's 7.7° and 8.66° bevel hinges lie below the gate, so the rotation is rigid there;
- the Wand's 14.6° hinge lies above it, so it is developed.

### 3. Near-tied taps are ordered by float32 comparators; a far tap's from q_E folded into J's plane

**Where it bites.** On non-dyadic geometry (`concave-fold`'s oblique tilt, `concave-shape`'s sheared B, the moved atlas), two taps whose float64 distances differ by about 10⁻⁵ relative swap in Painter's order. The own diagonals at (132, 70) are one example. The float64 order was then wrong, while decision 273's float32 comparator was right.

**The rule.** Distances within a relative band of 10⁻⁵ are a tie group, ordered by:
- **own taps:** decision 273's comparator, then decision 280's own order;
- **far taps:** the float32 |fold(q_E) − P|, then decision 280's window order. q_E is decision 273's float32 position through E. It is rotated in float32 about E's seam edge into J's plane when that edge is folded past the gate, and left as is otherwise. P is the tap's float32 position through its own triangle, not unfolded.

The weights still use the float64 distances.

**Decision 280's far comparator is replaced.** It rotated P into E's plane. On decision 280's visible far/far tied pairs:

| Far comparator | Visible far pairs right (of 4,543) |
|---|---|
| Decision 280: P unfolded into E's plane, float32 | 4,516 |
| **q_E folded into J's plane, float32** | **4,536** |

It fixes the 18 `pole-8-pyramid` pairs (6 per unmoved atlas) and the 2 `box320` G2 fold90 pairs. The 7 left are the moved atlas's `pole-8-pyramid` (4) and `pole-8` (3).

**The band.**
- **10⁻⁵ and 10⁻⁴ give the same probe counts.** 10⁻⁶ loses 31 moved-atlas and 95 `concave-shape` texels. 10⁻⁷ (decision 288's tolerance) loses 78 and 483.
- **A full float32 order is worse off the probes.** Ordering every tap by these float32 distances equals the band on every probe, but loses 30 cube and 35 Wand texels, where taps in hinge-less facets enter. The band and full-order comparisons ran on the 4b51eec model.

### 4. Counts

Ring texels bit-exact on all 24 channels. "Main" is the reference at main (decisions 278 to 281); "the rule" is findings 1 to 3.

| Probe | Ring texels | Main | Gate on single hinges only | **The rule** | Gained / lost |
|---|---|---|---|---|---|
| `concave-fold` | 7,760 | 6,835 | 7,575 | **7,759** | 924 / 0 |
| `concave-shape` | 15,494 | 14,441 | 14,927 | **15,487** | 1,053 / 7 |
| `concave-fine` | 12,240 | 11,742 | 12,236 | **12,236** | 494 / 0 |
| `atlas-512` / `-1024` / `-2048` | 3,140 each | 3,030 / 3,028 / 3,029 | the same | **3,038 / 3,036 / 3,037** | 8 / 0 each |
| `atlas-1024-moved` (held out) | 3,140 | 2,929 | 2,929 | **3,008** | 79 / 0 |
| `tie-sweep-seams-centred` | 7,805 | 7,663 | 7,663 | **7,663** | 0 / 0 |
| `tie-sweep-seams-offcentre` | 7,805 | 7,653 | 7,653 | **7,666** | 13 / 0 |
| `tie-sweep-seams-box320` | 7,805 | 7,574 | 7,574 | **7,591** | 17 / 0 |
| Ramps (5), `tie-512` | unchanged, all exact | | | | 0 / 0 |
| `sphere-256` (held out) | 2,176 | 913 | 1,593 | **1,593** | 680 / 0 |
| `bevelled-cube-256` (held out) | 2,344 | 1,947 | 1,947 | **1,996** | 59 / 10 |

**The Wand,** all 6,334 ring texels, through the reference ring in Python (the C++ kernel unchanged):

| | BaseColor | Roughness | Metallic | Height | All four | Height LP-consistent |
|---|---|---|---|---|---|---|
| Main | 6,070 | 6,249 | 6,296 | 5,997 | 5,762 | 6,305 |
| Gate on single hinges only | 6,132 | 6,258 | 6,295 | 5,995 | 5,824 | 6,305 |
| **The rule** | **6,133** | **6,260** | **6,295** | **5,996** | **5,827** (+72 / −7) | 6,305 |

- **The Wand's gain is the gate.** The tie band changes no Wand chain.
- **The probes in the decision 280 / 4b51eec model** (decision 280's own numbers) move the same way: `concave-fold` 6,848 → 7,759, `concave-shape` 14,441 → 15,487, `concave-fine` 11,742 → 12,236. The Wand moves 5,537 → 5,791 there.

### 5. Decision 288's classes

- **The sphere's "same-island taps at 3D distance" (288 rule (c)) is this gate.** On main's reference, gating hinges alone takes `sphere-256` from 913 to 1,593: its pole-fan hinges are shallow. Decision 288 got 913 → 1,563 from rule (c), counted with the golden's Height as well as the probe.
- **The two rules part only on steep same-island hinges.** The gate also measures shallow hinges between islands in 3D, which the concave probes need (A and B are separate islands). On steep same-island hinges, the gate unfolds where rule (c) does not. No probe here holds such a hinge with a decided texel. Combining the gate with decision 288's weld and self-fold rules was not run.
- **The 227 single-hinge convex bevel-seam texels** sit on folds of 55° to 68°, all above the gate, so the unfolding stands there.
  - 10 are fixed by finding 3.
  - **94 need another choice between exactly tied far taps** (0.192685 and 0.209261 in float64). Their window holds mirror pairs at rows r ± 1, and Painter keeps the lower one in the image (v down) on every texel sampled. The float32 comparator breaks those ties by rounding instead.
  - **123 match no subset of the kept candidates.** They are a tap-pool question, not the hinge distance.

### 6. What is not pinned

- **`concave-fine`'s 4 texels** (−9.974°, −9.976°, −10.019°, −172°). Their level-1 code sits at 309.51 against Painter's 309. Every float32 recipe tried (P unfolded, q folded, double) gives 309.50 to 309.51, so it is float32 noise at a code boundary.
- **The losses.** `concave-shape` 7 own texels, `bevelled-cube-256` 10, the Wand 7.
- **`concave-shape` and `-fold` own texels left:** 7 and 1.
- **The exact band.** It lies anywhere in [10⁻⁵, 10⁻⁴] on the probes. Painter's single float32 distance recipe for taps in hinge-less facets is not found.
- **Own taps across a shallow hinge.** They are gated too. No probe texel and no Wand all-four texel turns on it (28 Wand own-only texels change taps and stay misses), so the data do not decide it.

## Decision

1. **Recorded, not implemented.**
   - Item 2.7 stays open, and EXC-007 stays withdrawn (decision 259).
   - No production code, semantics entry, capability, conformance case, exception or test changes. `src/export/padding.cpp` and `tests/export/padding_reference.py` are unchanged; another pass integrates this rule.
2. **Identified, for the integration** (the reference's `frame`, `unfold32` and `_ordered`, and `padding.cpp`'s counterparts):
   - **(a) The hinge gate.** A hinge (τ's face to a tap's face, or any hinge of decision 281's development path) is unfolded only when the float32 dot of its faces' unit normals is at most 0.985. Otherwise the tap is not rotated about it. This is the same test as decision 278's gate, for concave and convex folds alike.
   - **(b) The tie band.** Taps whose float64 distances lie within 10⁻⁵ relative form one tie group.
   - **(c) The far comparator** in a tie group is the float32 |fold(q_E) − P|, about E's seam edge when it is folded past the gate. Decision 280's own comparator and both fixed orders are unchanged.
   - **What to refuse.** Production refuses, as `NotYetSupported` naming decision 282, a hinge whose dot lies in decision 278's bracket (0.98498905, 0.98501915]. Decision 001: nothing unproven is guessed.
   - **Where it is exact:** the counts of finding 4.
   - It closes decision 280's open item (e), most of its open item (a) (20 of 27 pairs), and decision 284's open item (a).
3. **Rejected, with the counts above:**
   - unfolding every hinge;
   - raw 3D for every far tap;
   - a geodesic through the hinge line;
   - projecting the tap onto τ's plane;
   - decision 284's rigid rotation for every no-hinge tap;
   - decision 280's far comparator;
   - the 10⁻⁹, 10⁻⁷ and 10⁻⁶ bands;
   - a full float32 tap order.
4. **Still open:**
   - **(a)** The 4 `concave-fine` code-boundary texels: the float32 unfold recipe.
   - **(b)** The 7 moved-atlas far pairs.
   - **(c)** The cube's 94 mirror-tied far choices and its 123 tap-pool misses.
   - **(d)** Whether decision 288's rule (c) and this gate differ on a steep same-island hinge. The probe to settle it: one island folded on itself at 10° to 30°, with ring texels reading across the fold.
   - **(e)** The band's exact width.
5. **No new recording is requested.** Owner: `phase1.25_pilot-wand` item 2.7.

## Consequences

- **One test decides both gating and unfolding.** Below about 9.94° a hinge is flat ground for the ring: no gate, no unfolding. Above it, it is a fold: decision 278's side test, decision 270's unfolding, and decision 281's development hinge by hinge.
- **The concave probes are exact** but for 4 + 7 + 1 texels. The Wand gains 65 all-four texels on main's reference, and the sphere gains 680.
- **These need no retesting** as the hinge distance:
  - convex against concave rules;
  - the gate side as a distance switch;
  - geodesics through the hinge line;
  - projected tap positions;
  - raw 3D for every far tap.
