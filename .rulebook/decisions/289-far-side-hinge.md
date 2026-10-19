# 289. Three far-side hinge probes test how the infinite ring measures a far tap beyond a hinge of the far island (rigid rotation, development, or decision 282's per-hinge gate), and a fourth isolates decision 291's window side; designed, recording pending (the Painter lock stayed held)

**Status**: accepted
**Date**: 2026-10-19
**Related Tasks**: phase1.25_pilot-wand, phase1.18_export-engine, phase1.16_export-processing-encoders

## Context

On 2026-10-18 the owner ruled that the Wand must match Painter everywhere, padding included. Exact `infinite` padding (item 2.7 of `phase1.25_pilot-wand`) is the critical path.

**Decision 284, open item (a).** A *multi-facet* far tap lies in a face K of the far island that shares no edge with the face of τ, the ring texel's triangle. Two meshes disagreed on the hinges between the far triangle J's face and K's face:
- on `bevelled-cube-256` the rigid rotation about the seam edge E is right across far-side hinges of 7.7° to 16°;
- on the Wand, ring texel (752, 1454) needs the development across a 14.6° far-side hinge. It seeds a flood cell of 421,846 gutter texels.

**The Wand seed,** read off decision 279's pickled geometry (no oracle values):
- τ is triangle 1238, at a corner ring texel with one own neighbour, (751, 1455). E is τ's own edge, so E lies in τ's face.
- J is triangle 1205, a sliver about 25 texels long, folded 6.5° convex from τ.
- The tap (249, 1994) lies in K, triangle 1204, across a 14.6° concave hinge from J, next to the vertex that J, K and τ share. J and K are in one UV island.

**Decision 282** landed while this pass ran, from the existing recordings. Its rule: a hinge is unfolded only when the float32 dot of its faces' unit normals is at most 0.985, which is decision 278's gate. Otherwise the tap keeps its 3D position. This holds hinge by hinge along decision 281's development path. It reconciles the cube (bevel hinges below the gate, so rigid) and the Wand (14.6°, above it, so developed).

**Decision 291** then found that the cube's remaining bevel-seam misses, and 20 to 49 atlas texels, depend on which side of decision 275's 3 × 3 window boundary the far point f falls when f lies exactly on a boundary in real arithmetic. Painter's side is a float32 rounding that no recipe tried reproduces; its open item (a) asks for an exact-arithmetic probe. The coordinator asked for that probe in the same batch.

This decision designs probes that test decision 282's rule independently. Each family varies one property of decision 284's question at a time, and a third request sweeps far-side hinges on both sides of the gate. The model panel was not consulted: the coordinator fixed the goal, the budget and the dimensions, so the choices left are parameters.

## Decision

### 1. The probes: copies of one seam pair bent along hinges

**The unit** is decision 278's seam pair. The generator is `request_fixtures.HingeCopy`, `hinge_copies`, `hinge_layout` and `hinge_probe`.
- **A** is a 4 × 4 cm square at 1 texel per cm. **B** lies beyond A's seam edge in its own UV island, turned 90°.
- **Bands.** Each island is a list of bands from the seam outward: (UV depth, signed hinge angle to the band before, UV gap, UV stretch). Positive angles are concave: the band rises on the side of the previous band's normal.
- **The seam fold.** B's first band is folded about the seam by `fold`: 6° convex unless a row says otherwise. That is below decision 278's gate, so no ring texel loses its far taps.
- **How positions are computed.** Each island is built in its own unfolded frame, and the hinges are applied from the farthest in. So every hinge's near face still lies in the frame's plane, and hinge vertices are kept bit for bit (shared in the mesh).
- **Where the taps fall.** B's first texel row is 0.625 texel deep, and a straight-edge ring texel's point q is 0.25 texel beyond the seam. A J band 0.4375 deep therefore puts the far point f in J and every first-row tap in K, one hinge beyond J.

**The layout is decision 278's** (`_pack`, now shared by `fold_layout`; the three `concave-fold` meshes are byte-identical).
- Copies lie in UV shelves at least 7 texels apart, and their 3D boxes are disjoint.
- Positions are written as exact float32 decimals.
- Two anchors fix the box at exactly [−256, 256] cm in x and z and [−64, 64] in y.

**Three hinge requests**, `export-padding-hinge-{far,vary,single}`, use decision 266's `kernel_probe` sequence at 512 px with the existing 512 px kernel bitmaps. Each sweep is the far-side hinge at ±2° to ±30° in 2° steps, plus 0° (31 copies), unless the row says otherwise.

| Probe | Family | What varies |
|---|---|---|
| `far` (148) | `strip` | The base: J 0.4375 deep, then K hinged by the swept angle |
| | `strip-fk` | J 0.125 deep, so f lies beyond the hinge, in K |
| | `two` | J 0.3125, then 0.1875 and K both hinged by the angle: the tap two hinges beyond J |
| | `sliver` | J is the sliver (0, 0), (1, 4), (0, 4) and K touches the seam's end vertex, as at the Wand seed |
| | `jsweep` | J 0.0625 to 0.5625 deep at ±12° and ±24° (24 copies) |
| `vary` (186) | `seam` | K is its own UV island, 1/16 texel from J in UV, with shared 3D vertices: the hinge across a UV seam |
| | `stretch` | K's UV stretched 1.5×, so J's UV extrapolation and the 3D development differ |
| | `econc`, `eflat` | The seam folded 6° concave, or flat |
| | `ecurve` | A bent 6° convex 0.1875 texel from the seam, so E does not lie in τ's face |
| | `own` | A bent twice by the angle around a thin band with no texel centre, so own taps lie two faces from τ |
| `single` (216) | `single-*` | Decision 278's pair concave from 0.5° to 9.5° with both quad diagonals, and convex: single-hinge folds below the gate, for decision 282 |
| | `strip-s0`, `strip-oblique` | The base sweep with the other diagonal, and tilted 37° about (1, 2, 3) |
| | `gate-e6`, `gate-e20` | The far-side hinge at ±9°, 9.5°, 9.75°, 9.9°, 9.92°, 9.935°, 9.95°, 10°, 10.25°, 10.5° and 11°, behind a 6° and a 20° convex seam (22 copies each). 9.935° lies inside decision 278's bracket. 9.92° and 9.95° lie on either side of it in the written float32 dot (0.98505 and 0.98496) |
| | `strip-e20` | The full sweep behind the 20° seam |
| | `gate-two-e20` | The `two` family behind the 20° seam, at the gate angles |

**A fourth request, `export-padding-window-side`** (144 copies, decision 291's open item (a)). The generator is `request_fixtures.SideCopy`, `side_copies`, `side_layout` and `window_side`.
- **The geometry.** Each copy is a flat seam pair (A and B 4 × 4 cm, separate UV islands, 1 texel per cm). The oblique island's UV map is a proper rotation by a Pythagorean angle (3-4-5, 5-12-13, 8-15-17, 7-24-25, both ways round and both signs of the sine), so its exact cosine and sine are rational.
- **The targets.** B's translation is chosen in exact arithmetic so that, for two of A's ring texels beyond the seam, f_u − ½ and f_v − ½ are integers: f lies exactly on a window boundary.
- **Why Painter's side shows.** The oblique UVs are not dyadic. Their written float32 values put f a few 10⁻⁵ texel to one side, the size of decision 291's observed flip offsets (up to 2.24·10⁻⁵).
- **The sweeps.** B is turned with A's box at two sub-texel offsets, and A is turned with B axis-aligned. Each is in three diagonal and vertex orders: the other quad diagonal, and each triangle's vertex list rotated by one. Each copy's offset is the first, in a fixed search order of odd sixteenths of a texel, that keeps every texel centre at least 1/64 texel from every edge in all three orders. That is beyond decision 281's 1/256 coverage snap.
- **The test** (`test_window_side_copies_put_far_points_on_window_boundaries`) checks:
  - the coverage and that 1/64 margin;
  - the 7-texel UV spacing and the disjoint 3D boxes;
  - that A and B are flat and share their two seam vertices;
  - that each target's f is on a boundary exactly in fractions, and within 10⁻⁴ texel through the written mesh;
  - that every copy has non-dyadic UVs.
- **On our own model,** 222 ring texels give different chains on the two sides of the boundary, 171 of the 288 targets among them (`sidecheck.py`). The kernel codes then read Painter's side directly from the decoded taps.

**Every copy is also read from B's side.** B's ring texels beyond the seam take τ in K. E then lies on J, not on τ's face, and the far taps in A are two hinges away.

**A test checks the meshes** (`test_hinge_copies_share_their_hinges_and_bend_by_their_angles`):
- each copy's A and B cover 16 texel centres each, with none on an edge;
- the copies lie at least 7 texels apart in UV and apart in 3D;
- across every designed hinge, the seam first, the two planar faces share exactly two mesh vertices;
- the written float32 positions bend the far face by the hinge's angle (within 5·10⁻³°; thin bands round), on the near face's normal side exactly when the angle is positive;
- the box is exact.

**The design was checked on our own model** (no oracle values). It used `tests/export/padding_reference.py` at main, with a subclass whose tap distance follows each candidate rule (private scratch `pad289/fit289.py`). Painter's export was simulated under one rule, and every rule was scored against it.
- **The true rule is exact every time.** On every family it is exact on all multi-facet texels.
- **The families separate the rules.** On each 31-copy family, between 92 and 285 multi-facet ring texels are exact under the true rule and not under the other one.
- **At the gate.** On `gate-e20`, 48 texels separate a sub-gate rigid hinge and 40 a past-gate developed one.
- **Small angles show little.** Rigid and developed distances differ only in second order of the angle. Below 4° almost no codes change; from 10° up, about 4 texels per copy do.
- **Three families have no multi-facet tap in our model, by design.**
  - In `seam`, K is outside the far island, so decision 275's window excludes it. Painter taking K's texels would show that this rule is wrong.
  - In `eflat`, A and J are coplanar, so the reference merges them into one face.
  - In `own`, the taps are own taps, which separate only raw 3D from the development.

### 2. Recording: pending

The Painter lock was held by `Claude/horse-bake`, another session, from 15:07 to 16:07 on 2026-10-19. It was checked about every 5 minutes, never freed, and was never touched. No Painter process was started, nothing was recorded, and no lock was acquired or released.

The requests are written:
- requests under `parity/envelopes/painter-12.1.5_js-api.1.1.20/requests/tier0/semantics/`;
- meshes `hinge-{far,vary,single}.obj` and `window-side.obj`:

| Mesh | Copies | Covered texels | SHA-256 |
|---|---|---|---|
| `hinge-far.obj` | 148 | 4,736 | `4e292c94f80a3b9fd1b2e1d088f0e0ddefce69ece53d867014c5f21406f2f7c7` |
| `hinge-vary.obj` | 186 | 5,952 | `2efd492dfbbc3221a095c258e4a92276c538eea3ca27c08a9abb2dff554e1860` |
| `hinge-single.obj` | 216 | 6,912 | `a5bd8026cf100cf0d9609594cc378908abc567bcc119c981833bb3c3a348d0f4` |
| `window-side.obj` | 144 | 4,632 | `c53d3bb0bac2eae818cc58fca670cb63664137c82e16a4d0dd7bda1dd1b8d612` |

**Estimated Painter time:** under 2 minutes for all four, inside the 10-minute cap. Decision 278's three probes of the same size took 42 s and 23 s with Painter open.

**How to record them.** One Legacy session under the Assets3D lock, as in `parity/RECORDER.md` §11.1 step 3.
1. Record each request with `python -m tools.parity.recorder record`.
2. Admit each run with `python -m tools.parity.store record`. Add the names to `recording_requests.ADMITTED` and delete the requests.
3. Apply the decision-129 void rules per channel. The covered texels must be exactly the counts above.

The session driver, void and stability check and fit are ready in private scratch: `pad289/session.py`, `verify289.py`, `fit289.py`. The fit modes are ref, raw, rigid, develop and decision 282's gate. `session.py` lists all four goldens.

## Consequences

- **The repository gains:**
  - the generator in `request_fixtures.py` (`HingeCopy`, `_hinge_turn`, `hinge_copies`, `hinge_layout`, `hinge_probe`; `_pack` and `_packed_obj_lines` shared with decision 278's meshes, unchanged bytes);
  - the window-side generator (`SideCopy`, `side_margin`, `side_copies`, `side_layout`, `window_side`);
  - four request entries in `recording_requests.py`, four meshes and four requests;
  - one parametrised test and one window-side test in `tests/parity/test_recording_requests.py`;
  - a §11.4 paragraph in `parity/RECORDER.md`.
- **Nothing in production changes.** Item 2.7 stays open, and EXC-007 stays withdrawn (decision 259). No `src/` change, no semantics entry, capability, conformance case or exception.
- **What the recording will settle:**
  - **(a)** Whether decision 282's per-hinge gate holds on far-side hinges built for the purpose: both signs, one and two hinges beyond J, f in J or in K, a sliver J, and 9° to 11° around the gate behind a sub-gate and a past-gate seam.
  - **(b)** Whether a far-side hinge across a UV seam ever feeds the window (`seam`).
  - **(c)** Whether the development follows the 3D geometry or J's UV map (`stretch`).
  - **(d)** E outside τ's face (`ecurve` and every B side).
  - **(e)** Own taps two faces away (`own`).
  - **(f)** Decision 282's single-hinge folds below the gate, from 0.5°.
  - **(g)** Decision 291's open item (a): Painter's side of the far window at an exact boundary, across angles, offsets and vertex orders, for the float32 recipe of f.
- **The fit is decided now:** per copy and family, which of rigid, develop and decision 282's gate is bit-exact on the multi-facet ring texels. The Wand is then re-scored with decision 284's scripts. Owner of the recording: `phase1.25_pilot-wand` item 2.7.
