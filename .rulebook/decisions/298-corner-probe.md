# 298. One corner-reach probe tests decision 294's corner reach independently of the Wand: 432 copies of one island corner whose two seam edges meet at a bent UV corner on different planar faces, the ring texel beyond the corner at 0.90 to 1.30 texel from it, the meeting edge gated, open or no seam, collinear and same-face controls; designed, recording pending

**Status**: accepted
**Date**: 2026-10-19
**Related Tasks**: phase1.25_pilot-wand, phase1.18_export-engine, phase1.26_gate-g1

## Context

Decision 294 (a) found a corner reach on the Wand. Take a seam edge (E, J) whose triangle E lies outside the planar face of τ, the ring texel's triangle. When its nearest point to the ring texel is its end V, a UV corner of the island, it reaches the texel only within:
- **D_g = 1.0 texel** when another reaching seam edge ending at V is gated for the texel (bracket [0.974615, 1.020004));
- **D_o = 1.15 texels** otherwise (bracket [1.075926, 1.208074)).

An edge collinear with another seam edge ending at V (|sin| ≤ 10⁻³ in UV) is exempt and keeps decision 285's 1.78.

The rule was fitted on the Wand alone, and no probe confirms it. Its open item (c) asked for a probe. The coordinator asked for one Tier 0 kernel probe at 512 px, under a minute of Painter time:
- seam pairs with a bent UV corner;
- the target's distance to V swept across 0.9 to 1.3 texels;
- the meeting edge gated and not gated;
- collinear controls and several corner angles.

The model panel was not consulted: the coordinator fixed the goal, the budget and the dimensions, so the choices left are parameters.

## Decision

### 1. The probe: copies of one island corner

**The unit.** The generator is `request_fixtures.CornerCopy`, `corner_copy`, `corner_copies`, `corner_layout` and `corner_reach`.
- **Island A** is two triangles at 1 texel per cm: F1 = (V, W1, C) and F2 = (V, C, W2), 4 cm arms, hinged along V C.
- **Its two seam edges** are e1 = V W1 (F1's) and e2 = V W2 (F2's). They meet at the UV corner V, where A's boundary bends by the copy's angle; at 0° e2 continues e1 straight.
- **F2 is folded 6° concave about V C.** That is below decision 278's gate, so e2 lies on another planar face than F1, and no candidate distance rule unfolds anything.
- **B2** lies across e2 in F2's plane, 2 cm deep. Its own UV island.
- **B1** lies across e1, its own UV island, folded about e1 by the gate variant's angle.
- **The target ring texel T** lies beside e1, `across` texels from it (1/2, else the nearest thirty-second that keeps the margin below) and `reach` texels from V.
  - e2's nearest point to T is its end V, and T's τ is F1. So e2 is decision 294's capped edge, and e1 the edge meeting it at V.
  - T has two or three own neighbours, and its chain holds up to four taps. So when B2 reaches T, at least one B2 tap is in its chain, whatever the far distances. The observable is whether T's decoded taps include a B2 texel.

**The gate variants of e1:**

| Variant | B1 | e1 for T | Decision 294 cap on e2 |
|---|---|---|---|
| `g` | 2 cm deep, folded 20° concave | gated (past the gate, T behind B1's plane) | D_g = 1.0 |
| `ge` | the same, 0.375 cm deep between two texel columns: no covered texel | gated | D_g |
| `ve` | empty, folded 20° convex | open: past the gate's dot product, but T in front of B1's plane | D_o = 1.15 |
| `oe` | empty, folded 6° convex | open, below the gate | D_o |
| `n` | none: e1 is no seam | — | D_o |

The empty B1s keep e1 a seam edge that never feeds T a tap, so that only the gate state differs between `ge`, `ve` and `oe`. A full open B1 would crowd e2's taps out of T's chain.

**The families** (432 copies):

| Family | Copies | What varies |
|---|---|---|
| `g`, `n` | 180 | bent 90°, 30°, 10°, 2° and 0°, each at the 18 reaches |
| `ge`, `oe` | 108 | bent 90°, 10° and 0°, each at the 18 reaches |
| `ve` | 36 | bent 90° and 10°, each at the 18 reaches |
| near-straight `g`, `n` | 36 | bent 0.05°, 0.25° and 1° (\|sin\| 8.7·10⁻⁴, 4.4·10⁻³, 0.017, around the exemption's 10⁻³), at the 6 coarse reaches |
| facet `g`, `n` | 72 | F2 folded 0° (one planar face), 2° and 20° about V C, bent 90° and 10°, at the 6 coarse reaches |

- **The 18 reaches:** 0.90, 0.95, 0.975, 0.985, 0.995, 1.005, 1.015, 1.03, 1.06, 1.08, 1.10, 1.12, 1.14, 1.16, 1.18, 1.20, 1.25 and 1.30 texels. Five lie in D_g's bracket and seven in D_o's.
- **The 6 coarse reaches:** 0.95, 0.99, 1.03, 1.10, 1.18 and 1.25.

**The layout is decision 278's** (`_pack`, `_packed_obj_lines`).
- Copies lie in UV shelves at least 7 texels apart, and their 3D boxes are disjoint.
- Within a copy, the islands are 4 texels apart and are translated by whole texels plus a sub-texel shift.
- Each copy takes the first `across`, quad diagonal and shift that keeps every texel centre 1/64 texel from every edge (decision 289's `side_margin`).
- Positions are written as exact float32 decimals, and two anchors fix the box at exactly [−256, 256] cm in x and z and [−64, 64] in y.

**The request** is `export-padding-corner-reach`. It uses decision 266's `kernel_probe` sequence at 512 px with the existing 512 px kernel bitmaps, and the mesh `corner-reach.obj`:

| Mesh | Copies | Covered texels | SHA-256 |
|---|---|---|---|
| `corner-reach.obj` | 432 | 10,767 | `5fccb0404c3fe3f9ddd63497f0b6cefe37ec409f157e5ceeaa2f78c18e1b2fd0` |

**A test checks the meshes** (`test_corner_copies_bend_at_v_and_put_the_target_past_the_far_edge`):
- the triangles cover disjoint texel centres, none on an edge; F1, F2 and B2 cover some, an empty B1 none, 10,767 in all;
- the copies lie at least 7 texels apart in UV and apart in 3D;
- T is uncovered with its left neighbour in F1, `across` from e1 and `reach` from V, past e2's end;
- e1 and e2 meet at V bent by the copy's angle, exactly straight in the written UVs at 0°;
- across every designed hinge, the two pieces share exactly two mesh vertices and bend by the hinge's angle (within 10⁻³°), on the near piece's normal side exactly when it is positive;
- the box is exact.

### 2. The design check on our own model

**How it ran.** No oracle values are read. The model is `tests/export/padding_reference.py` at main 2173221, with decision 294's own candidate patches (`pad294/rules294.py`: `end2`, its `co` and `coll` options). The check scripts are in private scratch, `E:/tmp/uzp-scratch/pad298/` (`sep.py`, `fam.py`, `tcands.py`). It runs in about 20 s per rule on the CPU, with no Painter and no GPU.

**Each rule ran over the probe's 19,354 ring texels:**
- **1.78** is decision 285's reach for every edge (main);
- **1.0** and **1.15** are one corner cap for every such edge;
- **294** is decision 294 (a);
- and three alternatives to 294:
  - **no exemption**, with no collinear exemption;
  - **any face**, which caps every E ≠ τ edge, in τ's planar face too;
  - **dot-only gate**, where the meeting edge counts as gated when its float32 normal dot is at most 0.985, on either side.

**Separation.** These are the ring texels whose chain (taps and fractions) differs between two rules. In brackets, how many of them are the designed targets T:

| Pair | Texels | Targets |
|---|---|---|
| **1.0 / 1.15** | **150** | 146 |
| **1.0 / 1.78** | **309** | 247 |
| **1.15 / 1.78** | **159** | 101 |
| 294 / 1.78 | 219 | 161 |
| 294 / 1.0 | 90 | 86 |
| 294 / 1.15 | 60 | 60 |
| 294 / no exemption | 35 | 35 |
| 294 / any face | 393 | 12 |
| 294 / dot-only gate | 16 | 16 |

**Per family, on the targets, as designed:**
- **`g` and `ge`** (gated meeting edge). B2 reaches T up to 0.995 and not from 1.005 on, at every bend from 90° to 0.25°, and at facets 2°, 6° and 20°.
- **`n`, `oe` and `ve`** (no gated meeting edge). B2 reaches T up to 1.14 and not from 1.16 on.
- **Collinear (bent 0°).**
  - `g`, `ge` and `oe` are exempt: B2 reaches T at every reach.
  - `n` is not exempt (e1 is no seam): it is capped at 1.15.
- **Near-straight.**
  - 0.05° is exempt (|sin| below 10⁻³); 0.25° and 1° are capped.
  - `n` is capped at every small bend.
- **Facet 0°** (E in τ's planar face): no cap at any reach.

**What the recording reads.** For each target, whether its decoded taps include a B2 texel. That settles:
- D_g and D_o to within one sweep step (0.01 texel in D_g's bracket, 0.02 in D_o's);
- whether the meeting edge's state is the full gate (`ve` against `ge`);
- whether an open seam differs from no seam (`oe` and `n`);
- the collinear exemption and its threshold to [8.7·10⁻⁴, 4.4·10⁻³) of |sin|;
- the facet condition.

**What our model flags, and why it does not decide the read:**
- **`mixed-gates`** (the 144 `g` targets under 1.78) is the configuration decision 294 resolved: e1 gated, e2 open, both reaching.
- **`multi-facet`** (76 targets) arises where float32 world positions put B2 off F2's plane by more than the reference's 10⁻⁶ coplanarity tolerance. At a 6° facet no candidate rule unfolds a hinge, and by the chain argument of §1 tap presence does not depend on the far distances.

### 3. Recording: pending

Another agent (`wt/rec-batch`) holds the next Painter session and records this request. No Painter process was started here.

**Estimated Painter time:** under 1 minute. That is one 512 px kernel export pair; decision 278's 512 px probes recorded in 6 s each, with Painter open 23 to 42 s.

**How to record it.** One Legacy session under the Assets3D lock, as in `parity/RECORDER.md` §11.1 step 3, from the repository root:

```powershell
$req = "parity/envelopes/painter-12.1.5_js-api.1.1.20/requests"
$man = "parity/envelopes/painter-12.1.5_js-api.1.1.20/manifests"
python -m tools.parity.recorder record "$req/tier0/semantics/export-padding-corner-reach.json"
python -m tools.parity.store record "$man/tier0/semantics/export-padding-corner-reach.json" --run <run directory>
```

Then:
1. Add the name to `recording_requests.ADMITTED` and delete the request.
2. Apply the decision-129 void rules per channel. The covered texels must be exactly 10,767.

## Consequences

- **The repository gains:**
  - the generator in `request_fixtures.py` (`CornerCopy`, `corner_copy`, `corner_copies`, `corner_layout`, `corner_reach`; `side_margin` now also takes a `CornerCopy`);
  - the request entry in `recording_requests.py`;
  - the mesh and the request;
  - one test in `tests/parity/test_recording_requests.py`;
  - a §11.4 paragraph in `parity/RECORDER.md`.
- **Nothing in production changes.** Item 2.7 stays open, and EXC-007 stays withdrawn (decision 259). There is no `src/` change, and no semantics entry, capability, conformance case or exception.
- **What the recording will settle:** decision 294's open item (c).
  - If Painter follows the per-family pattern of §2, decision 294 (a) is confirmed, with narrower brackets.
  - Any other pattern refutes the part it contradicts: the two caps, the gate dependence, the exemption, its threshold or the facet condition.
- **The fit:** decode each target's taps as in decision 278 (non-negative least squares over the kernel codes), then mark B2 present or absent per copy. Owner of the recording: `phase1.25_pilot-wand` item 2.7.
