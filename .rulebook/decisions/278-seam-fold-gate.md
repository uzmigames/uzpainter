# 278. Three fold probes pin the seam gate: a ring texel takes no far taps across a seam edge when its point lies behind the far triangle's plane and the two faces' normals meet at a float32 dot product of at most about 0.985 (9.93° to 9.94°)

**Status**: accepted
**Date**: 2026-10-19
**Related Tasks**: phase1.25_pilot-wand, phase1.18_export-engine, phase1.16_export-processing-encoders

## Context

On 2026-10-18 the owner ruled that the Wand must match Painter everywhere, padding included. Exact `infinite` padding on UV islands (item 2.7 of `phase1.25_pilot-wand`) is the critical path.

**Decision 277** found that a seam edge folded concave by about 15° or more gives the padding ring no far taps. Its open item (a) was the threshold and its form:
- on the Wand the threshold lies between 7.23° and 14.84° of dihedral angle, or between 6.00° and 14.53° of the far triangle's apex elevation above the own plane;
- the Wand cannot tell these forms apart, nor a per-tap or per-texel test, because each edge's deciding texels are all of one kind.

Decision 277 requested a concave-fold sweep of decision 266's seam item, with a second set whose apex is offset along the edge. This decision designs it, records it and fits the gate.

## Decision

### 1. The probes: copies of one seam pair, folded by swept angles

**The unit** is decision 266's `seam-r1-turn90` at side 4. The generator is `request_fixtures.FoldCopy`, `fold_copies` and `concave_fold`.
- **A** is a flat 4 × 4 cm square at 1 texel per cm. **B** lies beyond A's seam edge, in its own UV island at ratio 1, turned 90°.
- **The fold.** B is turned about the seam by a signed angle: positive is concave (B rises on the side of A's normal), negative is convex.
- **B's shape.** B is a parallelogram `depth` texels across the seam, whose far edge is sheared by `shear` · depth along it. So the apex of B's seam triangle sits off the seam's midpoint by a chosen offset ρ, in units of its height across the seam. Its elevation above A's plane is then asin(sin θ / √(1 + ρ²)), not θ.
- **The layout is decision 272's.** Each copy is its own 3D piece and its own pair of UV islands. Copies lie in UV shelves at least 7 texels apart and their 3D boxes are disjoint. Positions are written as exact float32 decimals. Two anchors fix the mesh box at exactly [−256, 256] cm in x and z and [−64, 64] in y.
- **A test checks the meshes.** A covers 16 texel centres and B 4 per texel of depth, with none on an edge. The copies are apart in UV and in 3D. A and B share the two seam vertices. The written positions fold B by the copy's angle, on A's normal side exactly when the angle is positive.

**Three requests**, `export-padding-concave-{fold,shape,fine}`, use decision 266's `kernel_probe` sequence at 512 px with the existing 512 px kernel bitmaps:

| Probe | Copies | What varies |
|---|---|---|
| `fold` | 194 | The base pair (ρ = 0.5) concave from 6° to 16° in 0.25° steps, with both quad diagonals (82). Flat and convex controls at 0°, −6°, −10°, −12.5°, −15°, −20° and −45°. Copies tilted 90° about x and 37° about (1, 2, 3), and copies scaled by 0.5, 2 and 4, each concave from 6° to 16° in 0.5° steps |
| `shape` | 366 | Six B shapes: depth 4 sheared by 0.5 with each diagonal (ρ = 0 and 1); depth 4 sheared by 1.5 with each diagonal (ρ = 1 and 2); depth 2 (ρ = 1) and depth 1 (ρ = 2). Each is folded concave from 6° to 36° in 0.5° steps |
| `fine` | 306 | The base pair at ±9.75° to ±10.25° in 0.01° steps, ±9.951° to ±10.05° in 0.001° steps, and ±20° to ±178° |

**Why there is a third request.** `fold` and `shape` were recorded first. They bracketed the switch at (9.75°, 10.00°] and showed that convex folds drop other texels. `fine` was then designed to pin the angle and to test folds up to 178°.

**The model panel was not consulted.** The coordinator fixed the goal, the budget and the sweep dimensions. The choices left (angles, shapes, scales) are parameters, not forks.

### 2. Recording

**The sessions.** Both were Legacy sessions under the Assets3D Painter lock (owner Claude) on 2026-10-19, and the lock was released after each.
- **Session 1** (`fold`, `shape`): Painter was open from 12:41:51 to 12:42:33, about 42 s, and closed normally. The two recordings took 12 s.
- **Session 2** (`fine`): Painter was open from 12:51:57 to 12:52:20, about 23 s, and closed normally. The recording took 6 s.

**Admission.** Each run was admitted with `python -m tools.parity.store record`, 66 private records each. The goldens joined `recording_requests.ADMITTED`, and the requests were deleted. `python -m tools.parity.store verify` passes on tier0.

| Golden | golden-record SHA-256 |
|---|---|
| `export-padding-concave-fold` | `c1ffb88b6e9663d7eb3108dd74d8fdcfaec1b356432bfe654085099a91cc22e9` |
| `export-padding-concave-shape` | `9e361df2ea39fd50c9181022e2418cce9a98099c5509a704dc5e8abddaff4011` |
| `export-padding-concave-fine` | `c43fe6893a39fd8ea075647eddb03ba1fa157ccd2aea9f07a2183ea97de05af3` |

**None is void:**
- every template capture (r1 and r2) shows User0 to User7 as RGB32F;
- every r1 `passthrough` equals its source bitmaps on every non-zero texel;
- the covered texels (`infinite` equal to the sources on all 24 channels) are exactly the designed 6,208, 10,492 and 9,792.

**Stability.**
- Every `infinite` export is byte-identical across both steps of r1 and of r2, and between r1 and r2.
- Both r1 `passthrough` steps are identical.
- As on every earlier kernel probe, r2's `passthrough` equals its `infinite`, so each probe counts as unstable only on its `passthrough` steps after reopen. The stability report, regenerated without fits, now covers 243 goldens: 137 stable, 106 unstable.

### 3. The fit

**How it ran.** On the CPU with numpy and scipy, from the private store: no GPU and no writes to Assets3D. The scripts stay in private scratch (`pad278/`), because they read oracle values.
- **Decoding.** For every ring texel of every copy, the one-hot and code scalars of r1 `infinite` (User0 to User5) were solved by non-negative least squares. The candidates were the own covered 8-neighbours, then the far island's covered texels. A texel is own-only when the own neighbours alone reproduce all 18 scalars to 10⁻⁵. All 35,494 ring texels resolved.
- **The reference.** Unfolded distances do not depend on the fold, so a copy's ungated tap choice is that of the same shape at |θ| < 9.9°.

**Finding 1: the gate.** A ring texel q takes no far candidates across a seam edge (τ, J) when both of these hold:
1. **The faces are folded enough.** n_τ · n_J ≤ c₀, the float32 dot product of the two triangles' unit face normals from the written float32 positions. c₀ lies in (0.98498905, 0.98501915]: the fold angle lies in (9.930°, 9.940°]. The round constant 0.985 (9.936°) lies inside.
2. **q lies behind J.** n_J · (q − p) < 0, with q the ring point extrapolated in τ's plane and p a vertex of the seam edge.

For planar faces the second condition reads:
- **concave fold:** the ring texels beyond the seam line lose their far taps;
- **convex fold:** the ring texels on the own side of the seam line lose them. These are decision 275 finding 2's corner texels, which lie beyond the island's other edges and still read the far island.

Otherwise decision 275's window, and decisions 268, 270 and 273's weights, chain and order, apply unchanged.

| Probe | Ring texels | Far taps, ungated | Gated (would take far taps, take none) | Own-only by distance | Matching the gate |
|---|---|---|---|---|---|
| `fold` | 7,760 | 1,326 | 1,390 | 5,044 | **7,760** |
| `shape` | 15,494 | 1,154 | 3,604 | 10,736 | **15,494** |
| `fine` | 12,240 | 2,408 | 1,876 | 7,956 | **12,240** |

**Finding 2: the dihedral angle decides, not the apex.**
- **Every copy family switches in the same bin:** between 9.75° and 10.00° for `fold`'s base pairs, and between 9.5° and 10.0° for its tilted and scaled copies and for every `shape` family. This holds for ρ = 0, 0.5, 1 and 2, for both diagonals, for depths 1, 2 and 4, for scales 0.5 to 4, and for both tilts.
- **No elevation threshold fits.** At the switch, the apex elevation runs from 4.45° (ρ = 2, gated) to 9.5° (ρ = 0, kept), so no elevation threshold separates kept from gated.
- **No size-dependent form fits.** The switch does not move with scale or depth, so it is not an absolute height, volume or determinant against an epsilon.
- **No world-axis form fits.** The switch does not move with the tilts.
- **One condition per texel and edge.** At the switch every far tap of a ring texel goes at once, at seam distances from 0.25 to 0.625 texel. So it is not a per-tap distance-normalised form.

**Finding 3: the side test is a separate sign, not one sine test.**
- **Small folds.** In `fine`, from −9.93° to +9.93° every reference far tap stays. From +9.94° up, the texels beyond the seam drop theirs (12 per copy). From −9.94° down, the corner texels drop theirs (2 per copy).
- **Large folds.** Both drops hold up to ±178°. A single test sin θ ≥ s₀ on the signed elevation would release folds beyond 170.07°, and it does not.

**Finding 4: what was rejected.**
- **Decision 277's edge-level form** (concave edges only, every ring texel) misses 1,306 probe texels: 1,028 that it gates and should not, and 278 that it keeps and should not.
- **Earlier data agrees.** On `atlas-512`'s `seam-r1-turn90-fold90` (convex 90°), the two B corner texels that take far taps on the flat twin `seam-r1-turn90` take none. Decision 275 scored only texels with far taps, so it did not see this.

**Finding 5: the Wand.** These are decision 277's 6,334 ring texels, with its scoring.
- **Under production's side-tested far point** (the far island only across τ's edges that q lies beyond), the counts are identical to decision 277's: Height 5,938, BaseColor 5,746, Roughness 6,165, Metallic 6,227, all four 5,465. Every window far candidate there lies beyond its seam, so concave means behind and convex means in front. No Wand seam edge lies near the bracket: of its 87 seam edges, the folds nearest 9.94° are 8.19° and 11.10°.
- **Under decision 275's far point across every own-triangle seam edge:**

| Gate | All four | Height |
|---|---|---|
| None | 4,532 | 5,273 |
| Decision 277 | 5,491 | 5,943 |
| This gate | **5,492** | **5,946** |

  The 16 texels that differ between decision 277 and this gate gain 6 and lose 5 all-four texels, all of them corner-type texels.

### 4. Decision

1. **Recorded, not implemented.**
   - Item 2.7 stays open, and EXC-007 stays withdrawn (decision 259).
   - `src/export/` belongs to decision 274's integration this round. This decision changes no production code, semantics entry, capability, conformance case, exception or test of the export path.
2. **Identified, for the integration:**
   - **The gate** is finding 1. It applies per ring texel and per seam edge across which a far candidate is reached, on the triangles' stored float32 positions.
   - **Where it is exact:** all 35,494 ring texels of the three probes.
   - It replaces decision 277's concave-edge gate and closes decision 277's open item (a).
   - **The bracket.** Production must refuse, as `NotYetSupported` naming decision 278, any seam edge whose float32 normal dot product lies in (0.98498905, 0.98501915]. It must also refuse a ring point exactly on J's plane (n_J · (q − p) = 0), which was not tested. Decision 001: nothing unproven is guessed.
3. **Rejected, with the counts above:**
   - the apex elevation, from the edge's midpoint or otherwise;
   - absolute heights, volumes or determinants against an epsilon;
   - world-axis tests;
   - per-tap distance-normalised forms;
   - a single sine test on the signed elevation;
   - decision 277's concave-only, every-texel form.
4. **Still open:**
   - **(a)** The exact constant inside the bracket, and whether the comparison is ≤ or <.
   - **(b)** A ring texel reached across two seam edges with different gates. That case was not built.
   - **(c)** Decision 277's open items (b) to (e) stand. The Wand's +6/−5 under decision 275's every-own-triangle far point are corner-type texels, still to be read with the V-gap and tap-set items.
5. **No new recording is requested.** Owner: `phase1.25_pilot-wand` item 2.7.

## Consequences

- **The repository gains:**
  - the generator in `tools/parity/tier0_semantics/request_fixtures.py`, with decision 272's OBJ writer shared as `_sweep_obj_lines` (the six sweep meshes are byte-identical);
  - the request entries in `recording_requests.py`;
  - three meshes `concave-fold-{fold,shape,fine}.obj` and three admitted manifests;
  - one parametrised test in `tests/parity/test_recording_requests.py`;
  - a §11.4 paragraph in `parity/RECORDER.md`;
  - the regenerated stability report.
- **The seam gate is now a measured rule,** not decision 277's 10° placeholder. Concave edges below about 9.94° keep their far taps, and convex edges at or above it lose the far taps of their corner texels.
- **These need no retesting** as the gate: apex elevation, absolute or epsilon forms, world axes, scale, tilt, quad diagonal, B's depth and shear.
