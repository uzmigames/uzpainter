# 284. Multi-facet tap distances: a far tap with no hinge to the ring face is measured after one rigid rotation about the seam edge, not along a surface path; best on the cube, better on the Wand ring, still not exact

**Status**: accepted
**Date**: 2026-10-19
**Related Tasks**: phase1.25_pilot-wand, phase1.18_export-engine, phase1.16_export-processing-encoders

## Context

On 2026-10-18 the owner ruled that the Wand must match Painter everywhere, padding included. Exact `infinite` padding (item 2.7 of `phase1.25_pilot-wand`) is the critical path.

**Where decision 281 left this.**
- A **multi-facet tap** is a chain tap in a planar face that shares no edge with the face of τ, the ring texel's triangle.
- Decision 281 moved such a tap into τ's plane along the nearer of the fewest-hinge face paths. That lies within 0.03–0.5% of the exact interval, but it is not exact.
- With it, `bevelled-cube-256` has 1,988 of 2,344 ring texels exact (30 of the 133 with a multi-facet tap). The Wand has 5,729 all-four ring texels and 2,996,125 all-four gutter texels, with 281's 1/256 coverage snap.
- Decision 281 named a true surface (geodesic) distance from the ring point as the next candidate.

**This pass:**
1. solves each multi-facet tap's distance from Painter's decoded weights;
2. tests the surface distances and the alternatives;
3. looks for the float32 operation order;
4. checks the result on the Wand.

**How it ran:**
- **The model.** `tests/export/padding_reference.py` at f7bbc0a, on decision 281's cube geometry (welded by position) and decision 279's pickled Wand geometry.
- **The Wand's setting.** It has 281's snapped coverage. Own taps with no hinge use 281's development unless a row says otherwise.
- **Decoded weights.** The cube's taps and weights come from decision 270's fewest-tap decode. Weights in descending order give decision 268's 10-, 8- and 6-bit codes. A distance set is right when it gives the decoded tap order and all three codes. This test agrees with bit-exactness on every cube texel.
- **Scoring.** The cube needs all 24 channels bit-exact. The Wand is scored as in decision 281: all four maps, and BaseColor, Roughness and Metallic (BRM) with Height LP-consistent.
- **Setting.** CPU only (numpy): no Painter and no GPU. The scripts read oracle values, so they stay in private scratch (`pad284/`).
- **Out of scope.** The single-hinge concave distance (decision 282) was not touched.

## Findings

### 1. Surface distances do not fit; the far point's straight distance does

**Definitions.**
- q is the ring point: the ring texel's centre extrapolated through τ.
- E is the seam edge whose decision-275 window holds the tap, and J is the far triangle across E.
- q_E is decision 275's far point: q rotated about E into J's plane.
- P is the tap's 3D point.

**What the rule does.** The new candidate is |q_E − P|, a plain 3D distance, with P **not** unfolded about the hinges between its face and J's face. Equivalently, P is rotated rigidly about E into τ's plane together with J, whatever face it lies in.

| Distance for a multi-facet far tap | Cube: multi-facet texels exact (of 133) | Cube total (of 2,344) |
|---|---|---|
| Straight 3D from q (the reference) | 0 | 1,943 |
| Through a vertex shared by the two faces, \|q − V\| + \|V − P\| | 0 | 1,943 |
| Nearer fewest-hinge development (decision 281) | 30 | 1,988 |
| **Exact polyhedral geodesic** from q traced onto the surface (window unfolding, any number of hinges) | 30 | 1,988 |
| q_E, with P unfolded into J's face (decision 281's row) | 31 | 1,990 |
| Hinge-by-hinge greedy (the first fewest-hinge path, decision 281) | 25 | — |
| **\|q_E − P\|, E the window's seam edge nearest the texel in UV** | **52** | **2,017** |
| \|q_E − P\|, the smallest over the windows that hold the tap | 51 | 2,016 |
| \|q_E − P\|, the first window in seam order | 38 | 2,002 |
| \|q_E − P\| for every far tap, single-hinge taps included | 51 | 2,015 |
| \|q_E − P\|, P unfolded only across hinges sharper than decision 278's gate (float32 dot ≤ 0.985) | 46 | 2,010 |

What the table shows:
- **The geodesic is not the answer.** On decision 281's 55 interval texels, the geodesic equals, to 4 decimals, one of the face-path developments (up to 2 hinges more than the fewest). It has the same total as 281's rule, and the two differ on only 2 texels, one each way. So it carries 281's 0.03–0.5% miss.
- **The new rule loses nothing.** Every cube texel exact under the reference, 281's development or the geodesic is also exact under the new rule.
- **Single-hinge taps keep decision 270's unfold.** Moving them to the new rule loses (4, 234) and (80, 235).

### 2. What still misses on the cube is mostly not the multi-facet distance

The new rule leaves 81 of the 133 multi-facet texels missing. They were classified with the code test:

| Class | Texels |
|---|---|
| Painter's tap set differs from ours | 16 |
| 3 or 4 of the 4 taps are multi-facet, so the test cannot isolate their distances | 21 |
| **Not a distance miss.** No distance for the multi-facet taps fits, so an own or single-hinge tap is wrong (q or τ, at the chart corners) | 37 |
| A multi-facet distance would fit, needing 0.85 to 1.002 times the rule's | 7 |

- **The 37 are the curved and corner class of decisions 279 and 281.** Their nearest single-hinge tap is off by 2–18% against the own taps. A tap distance cannot fix that.
- **Every determinable texel but 7 is explained.** That covers every cube texel whose only open quantity is the multi-facet distance.

### 3. The float32 operation order is not observable

- **The margins are too wide.** On the 101 multi-facet taps of exact cube texels, the smallest relative change of the distance that alters a code is 6.3·10⁻⁵. That is about 500 float32 ulps.
- **So any float32 evaluation gives the same result.** Every float32 evaluation of q_E and the distance, in any operation order consistent with decision 273, gives the same codes as double precision.
- **The order is left open.** It cannot be identified from these recordings, so the integration may take decision 273's per-operation float32 order.

### 4. The Wand: a better ring, one gutter seed lost, and a conflict

| Variant (281's coverage snap) | Ring all four | Ring BRM + Height consistent | Gutter all four | Multi-facet texels all four (of 647) |
|---|---|---|---|---|
| Decision 281 (nearer development) | 5,729 | 6,013 | 2,996,125 | 470 |
| \|q_E − P\|, nearest seam edge | 5,738 | 6,023 | 3,000,470 | 478 |
| \|q_E − P\|, smallest | 5,745 | 6,027 | **3,007,789** | 486 |
| **Rigid about E into E's plane, then E's face to τ's face along the nearer fewest-hinge development, nearest seam edge** | 5,754 | 6,038 | 2,583,849 | 494 |
| The same, smallest | 5,758 | 6,039 | 2,584,166 | 499 |
| The same for every far tap, nearest seam edge | **5,761** | **6,044** | 2,585,670 | — |
| The same, far-side hinges sharper than the gate unfolded | 5,729 | 6,013 | 2,995,500 | — |
| The ring point re-extrapolated through E (q_E from E's own UV map) | 5,736 | 6,019 | 2,668,393 | — |

**What is new on the Wand.** Its islands are curved, so E is often not in τ's face. q_E then folds q about an edge outside q's plane. Moving the rigidly rotated tap on from E's face to τ's face fixes that. On the cube it is the same as |q_E − P|, because E lies in τ's face there.

**The conflict: one gutter seed.**
- **The seed.** Ring texel (752, 1454) seeds a flood cell of 421,846 gutter texels. It is BaseColor-exact under decision 281's development and not under the rigid rotation.
- **Why.** Its tap (249, 1994) lies across a 14.6° hinge (float32 dot 0.9676) beyond J's face. Painter's distance there is the development across that hinge (5.52·10⁻⁵ against the rigid 6.12·10⁻⁵).
- **The cube says the opposite.** There the rigid rotation is right across far-side hinges of 7.7° to 16°. Unfolding the hinges sharper than the gate loses 7 cube texels and all the Wand's ring gains.
- **No gate separates the two.** No hinge-angle gate fits both meshes.

**The per-texel search on the Wand's 647 multi-facet texels.** These options were tried for each multi-facet tap: decision 281's development, straight 3D, |q_E − P| for each window, and the rigid-then-develop distance for each window.
- 578 texels are BRM-exact under some combination, and 69 under none.
- How many of the 578 each rule picks:

| Rule | Texels |
|---|---|
| Decision 281 | 497 |
| \|q_E − P\|, smallest | 515 |
| Rigid then develop, nearest seam edge | 521 |
| Rigid then develop, smallest | 525 |

- 20 texels need a combination that no rule picks.
- **Which seam edge to measure from is open.** When a tap lies in two windows, the cube favours the nearest seam edge (1 texel) and the Wand favours the smallest distance (4 texels). Per texel, 16 favour one and 19 the other.

## Decision

1. **Recorded, not implemented.**
   - Item 2.7 stays open, and EXC-007 stays withdrawn (decision 259).
   - No production code, semantics entry, capability, conformance case, exception or test changes. `src/export/` and `tests/export/padding_reference.py` are unchanged.
2. **Identified: the best construction so far for a far tap whose face has no edge to τ's face.**
   - **The construction.** Rotate the tap point rigidly with the far triangle about the seam edge E into E's plane, without unfolding the hinges between its face and J's face. Then move it from E's face to τ's face along the nearer fewest-hinge development. On the cube, E lies in τ's face, so this is |q_E − P| with q_E decision 275's far point.
   - **Which seam edge.** The window's seam edge nearest the texel in UV (or the smallest distance; finding 4).
   - **The other taps are unchanged.** Single-hinge taps keep decision 270's unfold.
   - **The counts.** The cube goes from 1,988 to 2,017, which explains every determinable multi-facet cube texel but 7. The Wand ring goes from 5,729 to 5,754–5,761 all four.
   - **It is not exact.** On the Wand it loses one gutter seed worth 421,846 BaseColor texels (finding 4), so the integration must not take it on its own.
3. **Rejected, with the counts above, as the multi-facet distance:**
   - the exact polyhedral geodesic from q (it is decision 281's development);
   - straight 3D from q;
   - the path through a shared vertex;
   - decision 281's unfold of the tap into the far face;
   - the first-path greedy development;
   - unfolding only the far-side hinges sharper than decision 278's gate;
   - re-extrapolating q through E.
4. **Still open:**
   - **(a)** Whether a far-side hinge is unfolded. The cube needs the rigid rotation across 7.7° to 16°. The Wand's (752, 1454) needs the development across 14.6°. A probe would settle it: one island whose far chart holds a hinge of a known angle beyond the seam, swept from 2° to 30°.
   - **(b)** Which window's seam edge a tap held by two windows is measured from (nearest in UV against smallest distance).
   - **(c)** The cube's 37 corner texels whose own or single-hinge taps are inconsistent: q or τ at chart corners, the class of decisions 279 and 281. Also its 16 tap-set texels.
   - **(d)** The float32 operation order (finding 3): not observable on these recordings.
5. **No new recording is requested here.** The probe of 4(a) is the owner's call. Owner: `phase1.25_pilot-wand` item 2.7.

## Consequences

- **The geodesic is ruled out.** Polyhedral surface distances (geodesic, fewest-hinge or greedy development, vertex paths) do not need to be retried for multi-facet taps.
- **The construction is one rotation.** The multi-facet distance is measured from the seam edge's far point after a rigid rotation, not over the surface. What remains is whether hinges beyond the far triangle are unfolded, and which seam edge measures a tap held by two windows.
- **The integration keeps decision 281's development for now.** It is the only variant that keeps the 421,846-texel gutter seed. The rule of item 2 replaces it once open item 4(a) is settled.
