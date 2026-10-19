# 291. The bevelled cube's bevel-seam residue is one class: the side of decision 275's far window when the far point f lies on a window boundary. It is no tie rule and no tap-pool rule. Painter's side is a float32 rounding that neither float64 floor/ceil nor any float32 recipe tried reproduces, so a side-dependent ring texel is refused. Under decisions 282 + 285 + 288, 54 of the Wand's 70 "other" texels are exact; the 16 left are a different class

**Status**: accepted
**Date**: 2026-10-19
**Related Tasks**: phase1.25_pilot-wand, phase1.18_export-engine

## Context

On 2026-10-18 the owner ruled that the Wand must match Painter everywhere, padding included. Exact `infinite` padding on UV islands (item 2.7 of `phase1.25_pilot-wand`) is the critical path.

**What was open:**
- **Decision 282, open item (c).** It left two classes among `bevelled-cube-256`'s single-hinge convex bevel-seam texels, all folded 55° to 68°:
  - 94 that needed another choice between exactly tied mirror far taps at rows r ± 1, where Painter "keeps the lower one in the image";
  - 123 that matched no subset of the kept candidates (a tap-pool question).
- **Decision 285, open item (a).** 70 of the Wand's single-triangle far-tap texels ("other"), 54 of them BaseColor-only, with no common decoded tap set.

**The data**, all read from the private store:
- the r1 `infinite` exports (24 channels) of decision 266's kernel probes, decision 272's sweeps and decision 278's concave probes;
- decision 270's decoded taps of `bevelled-cube-256` (`decm-bevelled-cube-256`);
- the Wand v1's r1 PNG 16 maps, scored as in decision 280.

**How it ran.**
- **The model** is `tests/export/padding_reference.py` at main (decisions 278 to 281), subclassed in private scratch (`pad291/hring2.py`, from `pad282`). It adds, as switches:
  - decision 282's (a) to (c): the hinge gate, the gated development and the q_E-folded far comparator in a 10⁻⁵ tie band;
  - decision 285's (b) own taps through K across a UV edge, and (c) D = 1.78;
  - decision 288's (d) weld by value and (e) no self-fold window.

  Decision 288's (c), same-island taps at their 3D distance, is not added. Decision 282 found that its gate covers the sphere's case.
- **"Stack S"** is all of these together.
- **Scoring.** A probe ring texel counts when all 24 channels are bit-exact. A Wand texel counts when all four maps are exact.
- **The window side.** At a ring texel where some seam edge's f has f_u − ½ or f_v − ½ within 10⁻⁴ of an integer (float64), each near-boundary axis was tried on both sides of the boundary. Each side choice was scored against Painter's channels.
- On the CPU with numpy, in about two hours. No Painter, no GPU, no `src/` change. The scripts stay in private scratch (`E:/tmp/uzp-scratch/pad291/`), because they read oracle values. Clean room: black-box fits of our own recordings only.

## Findings

### 1. The three rule sets compose without loss

Ring texels exact:

| Probe | Decision 282 | **Stack S** (282 + 285 + 288) |
|---|---|---|
| Ramps (5), `tie-512` | all exact | all exact |
| `atlas-512` / `-1024` / `-2048` | 3,038 / 3,036 / 3,037 | 3,038 / 3,036 / 3,037 |
| `atlas-1024-moved` | 3,008 | 3,007 (decision 288 (e): −1) |
| `tie-sweep-seams-centred` / `-offcentre` / `-box320` | 7,663 / 7,666 / 7,591 | the same |
| `concave-fold` / `-shape` / `-fine` | 7,759 / 15,487 / 12,236 | the same |
| `sphere-256` | 1,593 | **1,978** (decision 288 (d), (e)) |
| `bevelled-cube-256` | 1,996 | **1,998** (decision 285 (b)) |

**The Wand** (6,334 ring texels):

| | BaseColor | Roughness | Metallic | Height | All four | Height LP-consistent |
|---|---|---|---|---|---|---|
| Decision 285 alone (main + 285) | 6,117 | 6,278 | 6,311 | 6,016 | 5,811 | 6,316 |
| Decision 282 alone | 6,133 | 6,260 | 6,295 | 5,996 | 5,827 | 6,305 |
| **Stack S** | **6,181** | **6,289** | **6,311** | **6,014** | **5,877** | **6,316** |

- The model reproduces decision 285's Wand count (5,811) and decision 282's (5,827).
- On the Wand, decision 288's (d) and (e) change nothing.

### 2. The cube's bevel-seam residue is the window side at a boundary far point

**Where it happens.** The cube's UV seams run along texel centres. So along a seam, f_v lands on a row centre (f_v − ½ an integer) in real arithmetic.

**Why the float64 window flips.** The UVs are non-dyadic float32 values (93.44000244 / 256, …). So the float64 f sits 10⁻¹⁴ to 4·10⁻⁵ to one side of the boundary, and decision 275's ceil(f_v − ½) flips with that noise.

**Two cases at f_v = row + ½:**
- **Painter's window is the upper side** (rows r − 1 … r + 1, with r = f's row). Both mirror taps, at rows r ± 1 (float64-equal distances, e.g. 0.192685), are in the pool, and the chain takes both. This is decision 282's "no subset of the kept candidates". Example: (4, 210). Our window was rows r … r + 2, so (164, 81) was missing. Painter's decode holds (164, 81) and (164, 83) at equal weights 0.17576.
- **Painter's window is the lower side.** The upper mirror tap is not in the pool, and the chain takes a farther tap (0.209261) instead. This is decision 282's "keeps the lower one". Example: (4, 151). Painter leaves out (164, 22) at 0.192685 and takes (165, 24) at 0.209261.

So it is neither a tie rule nor a tap-pool rule. **The window base itself moves.**

**Counts, stack S.**
- Of the cube's 2,344 ring texels, 816 have an f within 10⁻⁴ of a boundary.
- The float64 floor/ceil is exact on 584 of them.
- **Some side is exact on 783.**
- Painter's side would gain **199** texels (cube 1,998 → 2,197), all single-hinge.

**Decision 282's two classes** (in this pass's reclassification, on 282's model):

| Decision 282's class | Texels | Exact with Painter's window side |
|---|---|---|
| A subset of the kept candidates fits (the "94") | 115 | 100 |
| No subset fits (the "123") | 127 | 99 |

**14 more** single-hinge texels are exact with Painter's side plus another order of an exactly tied mirror pair. The order is neither "upper first" nor "lower first": (80, 162) leads with row 33, (80, 208) with row 81. So it is decision 282's float32 far comparator (q_E folded) getting these rounding-level ties wrong, not a fixed order.

**What is left on the cube:** 241 single-hinge misses → 28, of which 23 have no boundary far point. The 105 multi-facet misses are unchanged; they are decision 284's class.

### 3. Painter's side is not float64 floor/ceil, nor any float32 recipe tried

**Within a seam, Painter's side varies by row with no geometric pattern.** For the edge 97 → 622, rows 21 to 32 at float64-exact f_v, it reads hi, lo, hi, hi, lo, hi, hi, hi, hi, lo, lo, lo. It is a rounding signature.

**The 659 cube axes whose side is decided** (exactly one side fits):

| Side rule | Right |
|---|---|
| float64 f, floor/ceil (the reference) | 463 |
| float64 f rounded to float32 | 508 |
| UV similarity across the seam edge, float32 (texel or UV space) | 504 |
| Decision 273's float32 q_E, folded in float32, J's barycentrics (rcp or division; box-normalised or world coordinates) | 493–504 |
| The exact E → J affine map, float32 coefficients, 4 evaluation orders × 3 spaces | 492–500 |
| "Floor/ceil at an exact boundary" (the convention alone) | about 478 |

Each recipe is within a few points of the convention alone. Each tried recipe keeps f exactly on the boundary, while Painter's f lands on either side.

**The same class on the atlases.** The window side would gain 20, 22 and 22 texels on `atlas-512`, `-1024` and `-2048`, and 49 on `atlas-1024-moved`:
- on the unmoved atlases: `pole-8` (3), `pole-12` (9), `pole-8-pyramid` (3) and `seam-r1-turn90-fold53` (5);
- this explains decision 275's open item (c): the `fold53` texels (236, 161) and (252, 166);
- it is part of decision 270 finding 5's pole tap set;
- on the moved atlas, decision 275's open item (b).

**Not even exact arithmetic decides it.** On coplanar seams where the rational f (from the float inputs) is exactly on the boundary, floor/ceil is right on 213 of 223 axes (`atlas-512`) and 178 of 207 (moved). The ramps (17 of 17) and the axis-aligned flat atlas items (16 of 16 unmoved) follow floor/ceil. The oblique pole seams and the moved atlas do not.

**How far from the boundary Painter flips.** The largest float64 offset at which Painter took the other side is 2.24·10⁻⁵ texel (moved atlas) and 3.8·10⁻⁶ (cube).

**On the Wand the class barely occurs:** 2 ring texels have an f within 10⁻⁴ of a boundary, and 1 is side-dependent.

### 4. The Wand's 70 "other" texels: the hinge gate, not the pool

**Most are now exact.** Decision 285's "other" list holds 96 texels: 26 made exact by decision 280's fix, then the 70. Under decision 282 alone, 80 of the 96 are exact, and under stack S too. So **decision 282's hinge gate closes 54 of the 70.** Their BaseColor-only misses were 1/d shares off by a shallow-hinge unfold.

**The 16 left are not the cube's class:**
- none has an f within 10⁻³ of a window boundary except one (6·10⁻⁴);
- 9 are matched by some subset of the kept candidates (weak evidence in 8-bit maps);
- in nearly all of them, the 4th and 5th candidates sit within about 2% of each other, or own and far taps tie (e.g. (204, 1614): own and far at 0.000171).

They are near-tie distance questions, left open.

## Decision

1. **Recorded, not implemented.**
   - Item 2.7 stays open, and EXC-007 stays withdrawn (decision 259).
   - No production code, semantics entry, capability, conformance case, exception or test changes. `src/export/padding.cpp` and `tests/export/padding_reference.py` are unchanged.
2. **Identified, for the integration:**
   - **(a) Composition.** Decisions 282 (a)–(c), 285 (b)–(c) and 288 (d)–(e) compose. Their counts are finding 1's stack S. The Wand's all-four count is 5,877.
   - **(b) The window-side refusal.** Production refuses, as `NotYetSupported` naming decision 291, a ring texel when both of these hold:
     - for some seam edge, the far point f (decision 275) has f_u − ½ or f_v − ½ within ε = 10⁻⁴ texel of an integer;
     - the two windows on either side give different chains.

     Painter's side there is a float32 rounding that is not reproduced (finding 3). ε is more than four times the largest observed flip offset. Decision 001: nothing unproven is guessed.
     - **What it costs** (near-boundary texels that are side-dependent and exact today): cube 527, `atlas-512` 242, `-1024` 240, `-2048` 240, `atlas-1024-moved` 202, `ramp-r1-p0` 10, Wand at most 1.
     - **What it covers** (texels exact only on the other side): cube 199, atlases 20 / 22 / 22, moved atlas 49.
   - **(c) Decision 282's comparator** stays the far tie key. It is wrong on 14 cube mirror pairs (finding 2), which are refused under (b) anyway.
3. **Rejected:**
   - a fixed mirror-tie order ("lower first" or "upper first", finding 2);
   - a tap-pool change (wider window, extra edges) for decision 282's 127 class: 99 are the window side;
   - as the side rule: float64 floor/ceil, a float32 rounding of the float64 f, the float32 UV similarity, the float32 fold with J's barycentrics, and float32 affine maps (finding 3).
4. **Still open:**
   - **(a)** Painter's float32 recipe for f at a window boundary. It would lift the cube by up to 199 (+14 with the order), the atlases by 20 to 22, the moved atlas by 49, and decide decision 275's (b) and (c). An exact-arithmetic probe could isolate it: a flat island seam at an oblique non-dyadic angle, with ring texels on texel-centre f.
   - **(b)** The cube's 28 single-hinge texels left (23 with no boundary far point) and its 105 multi-facet texels (decision 284).
   - **(c)** The Wand's 16 near-tie "other" texels.
   - **(d)** Decision 288 (e) costs 1 `atlas-1024-moved` texel on top of decision 282.
5. **No new recording is requested.** Owner: `phase1.25_pilot-wand` item 2.7.

## Consequences

- **Decision 282's two cube classes, decision 275's open items (b) and (c), and part of the atlas pole tap set are one open item:** the float32 far point at a window boundary. Until it is found, those texels are refused rather than guessed.
- **The Wand is almost untouched by this class.** Its remaining "other" misses are distance near-ties.
- **These need no retesting** as the bevel-seam residue:
  - mirror-tie fixed orders;
  - windows wider than decision 275's 3 × 3;
  - the float32 recipes of finding 3.
