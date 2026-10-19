# 270. Pole and cube-corner ring texels take decision 268's quantised 1/d shares over unfolded distances from the own-triangle extrapolation, bit-exact on every single-triangle texel; the V-gap position and the tap set stay open

**Status**: accepted
**Date**: 2026-10-19
**Related Tasks**: phase1.25_pilot-wand, phase1.18_export-engine, phase1.16_export-processing-encoders

## Context

On 2026-10-18 the owner ruled that the Wand must match Painter everywhere, padding included. Exact `infinite` padding on UV islands (item 2.7 of `phase1.25_pilot-wand`) is the critical path.

**What was known:**
- **Decision 268:** a ring texel is an FMA lerp chain over at most 4 taps. Its fractions are the taps' exact 1/d shares, sorted and quantised to 10, 8 and 6 bits. It is bit-exact on every decoded seam-ring texel.
- **Decision 269:** isotropic corners are bit-exact, but poles and cube corners take taps by 3D proximity. It left open (b) the L-side lead, (c) 2 sides + 2 diagonals on `seam-r1-turn30`, (d) the ring position at a fan's V-gap, (e) `sphere-256` and (f) cube corners across a seam.
- **Decision 267:** the straight edge is the same chain. Its tie order is fixed by extrapolating the ring texel through each diagonal's own triangle.

**This pass covers:**
- the six pole and cube-corner items of the kernel atlas: `corner-r1`, `corner-r1-r1.5-r2`, `pole-4`, `pole-8`, `pole-8-pyramid` and `pole-12`;
- `sphere-256` and `bevelled-cube-256`.

The straight edge and the order of tied shares belong to decision 267, so this pass leaves the tie order free, as decision 268 did.

**The data** are decision 266's probes (commit c1f30c3): the r1 `infinite` (step 45) and `passthrough` (step 47) exports, all 8 User channels, for `export-padding-kernel-atlas-{512,1024,2048,1024-moved}`, `-sphere-256` and `-bevelled-cube-256`. They were read from the private store.

**Method:**
- **Coverage.** A covered texel is one where `infinite` equals `passthrough` on all 24 channels.
- **3D maps.** Atlas texels are mapped to 3D through `request_fixtures.atlas_faces`, and the two meshes through `sphere.obj` and `bevelled-cube.obj`. The moved atlas uses the unmoved geometry: its scale and offset leave exact shares unchanged.
- **Tap decode.** The candidates are the item's (or mesh's) covered texels, sorted by 3D distance from the ring texel's extrapolations. The decoder takes the fewest taps (at most 6) whose positive weights reproduce the 9 one-hot slots and the 6 code scalars to 3·10⁻⁷, with weights summing to 1.
- **Bit-exactness.** All 24 output channels must equal Painter's float32 bits after decision 206's output rounding.
- **How it ran.** On the CPU, with no Painter and no GPU, within the 2-hour box. The scripts stay in private scratch (`pad270/`), because they read oracle values.

## Findings

### 1. Never more than 4 taps

Decision 269's NNLS decode reported up to 12 taps next to a fan's apex. The fewest-tap decode finds at most 4 taps on every decoded texel:

| Probe | Ring texels | Decoded | Taps 1 / 2 / 3 / 4 |
|---|---|---|---|
| `atlas-512`, six items | 951 | 949 | 29 / 138 / 200 / 582 |
| `atlas-1024`, `-2048`, `-1024-moved` | 951 each | 949 each | the same, within ±4 per class |
| `sphere-256` | 2,176 | 2,120 | 0 / 94 / 64 / 1,962 |
| `bevelled-cube-256` | 2,344 | 2,344 | 3 / 0 / 15 / 2,326 |

- **The extra taps were spurious.** NNLS spread small weights, from 10⁻⁷ up to 5·10⁻³, over taps that a 4-tap exact solution does not need.
- **The 2 undecoded atlas texels** are in `corner-r1-r1.5-r2` and need more than 18 candidates or 6 taps.
- **The 56 undecoded sphere texels** hit the same limits.

### 2. The ring point: extrapolated through the own triangle, with far taps unfolded about the shared edge

**The rule.** Let τ be the triangle of the ring texel's covered 8-neighbours. When they all lie in one triangle (or in one planar face), τ is that triangle.
1. **The ring point.** q is the ring texel's centre, extrapolated through τ's UV-to-3D affine map.
2. **The tap points.** A tap in τ, or in a face coplanar with τ, is used as it is. A tap in a face that shares a 3D edge with τ's face is rotated about that edge into τ's plane, onto the far side. A tap in a face that shares only a vertex with τ is used at its 3D position.
3. **The weights.** d is |q − tap point|, then decision 268's generator: sort the taps by 1/d share, then take the 10-, 8- and 6-bit UNORM codes.

On each atlas probe, the quantised weights this rule predicts equal the decoded weights (to 2·10⁻⁶) on every multi-tap texel whose own neighbours lie in one triangle or one planar face. With the 1-tap copies, that is 816 texels per probe.

**What the unfolding is needed for.**
- **The pyramid fan.** It needs the unfolding on 68 of its 203 multi-tap texels. Plain 3D distance gets 135 of 203.
- **The cube corners.** They need it on the 4-tap texels whose taps sit on two or three faces. Plain 3D distance gets none of the 55 4-tap cube-corner texels.
- **The flat fans.** Unfolded and 3D distance are the same there.
- **`sphere-256`.** Every decoded multi-tap texel's codes are reproduced with plain 3D distance, as well as with the unfolding. The curvature over a texel is too small to tell the two apart at 10 bits.

The rule closes decision 269's open item (f): cube corners across a seam take decision 268's far taps with unfolded distance, as folded seams do. It also closes decision 269's (a) for the fans: the "fractions that are not 1/d" were the 1/d shares quantised to UNORM, measured from this q.

### 3. Bit-exact counts

The chain is decision 268's: innermost pair m = fma(fl(1 − t), v_b − v_a, v_a), then outward fma(t, v − m, m), then decision 206's rounding. One tap is a copy. Only the order of exactly tied shares is left free.

| Probe | Single-triangle texels (incl. 1-tap) | V-gap texels: q from the higher-index triangle | V-gap: best of the three positions (finding 4) | Total bit-exact |
|---|---|---|---|---|
| `atlas-512` | **816 / 816** | 104 / 133 | 125 / 133 | 941 / 949 |
| `atlas-1024` | **816 / 816** | 104 / 133 | 125 / 133 | 941 / 949 |
| `atlas-2048` | **816 / 816** | 104 / 133 | 125 / 133 | 941 / 949 |
| `atlas-1024-moved` | **816 / 816** | 100 / 133 | 124 / 133 | 940 / 949 |
| `sphere-256` | 1,896 / 1,928 | — | 192 / 192 | 2,088 / 2,120 |
| `bevelled-cube-256` | 3 / 1,912 (the 1-tap copies only) | — | 0 / 432 | 3 / 2,344 |

**Per item on `atlas-512`.**

| Item | Single-triangle | V-gap: higher-index q / lower / per-tap / none |
|---|---|---|
| `corner-r1` | 48 / 48 | 12 / 0 / 0 / 0 |
| `corner-r1-r1.5-r2` | 50 / 50 | 12 / 0 / 0 / 0 (2 undecoded) |
| `pole-4` | 134 / 134 | 7 / 1 / 1 / 0 |
| `pole-8` | 216 / 216 | 25 / 0 / 3 / 0 |
| `pole-8-pyramid` | 216 / 216 | 13 / 0 / 7 / 8 |
| `pole-12` | 152 / 152 | 35 / 0 / 9 / 0 |

**`bevelled-cube-256` is not reproduced.**
- **Where its taps are.** Its ring texels read across seams onto the bevel strips. The taps there lie in faces that share no edge with τ, so finding 2's one-hinge unfolding falls back to 3D distance.
- **What fails.** Neither that distance nor UV distance gives the decoded codes, on any of the 2,341 multi-tap texels.
- **What it needs.** An unfolding across the chain of bevel facets (a geodesic distance). It was not built within the time box.

**The 32 sphere misses.** All are 2-tap texels on row 255, the south pole's row at the tile border, one every 8 columns (one per segment). Painter's level-1 code is reproduced (383.67 rounds to 384), but 1 to 8 ulps differ on several channels. None of fma(1 − t, b − a, a), fma(t, a − b, b) or a multiply-add reproduces them, while the other 62 two-tap sphere texels are exact under the first form, 31 of them on row 255. So the code is right and either the tap values or the arithmetic differ at the tile border. That is open.

### 4. The V-gap: three positions, chosen by a rule not found

A **V-gap texel** has covered 8-neighbours in two triangles that share only a UV vertex: the fan's apex copies, or the shared base vertex. The two extrapolations give two different 3D points. These candidates were scored (on `atlas-512`):

| Where the texel sits | Texels | q from the higher-index triangle | q from the lower | Per-tap: each own-neighbour tap from its own triangle's extrapolation | Neither |
|---|---|---|---|---|---|
| In the V, or beside it (neighbours above and below) | 81 | 72 | 1 (`pole-4` (387, 165)) | 0 | 8 (all on the pyramid) |
| Below a shared base vertex (neighbours above only) | 28 | 8 (2-tap texels at flat 90° corners) | 0 | 20 (every 180° vertex, the 3-tap 90° corners and the pyramid) | 0 |
| Cube-corner texels whose neighbours span two faces | 24 | 24 | — | — | 0 |

- **No UV rule separates the cases.** `pole-4`'s three V-gaps are the same configuration in UV, rotated by 90° in 3D. Two take the higher-index triangle and the third takes the lower.
- **The choice follows rounding.** On the moved atlas, 4 V-gap texels change position class (pole-4: 7 → 6 higher, 1 → 2 per-tap; pole-12: 35 → 32 higher, 0 → 2 lower, 1 none).
- **What it looks like.** A tie between the two equidistant own neighbours, broken in float32 object space, like decision 261's sign and decision 267's own-triangle comparator. This pass did not run that comparator.
- **Rejected as the V-gap position:** the mean of the two extrapolations (3 of 133), the per-tap minimum or maximum, and the triangle nearer in UV (it fails `pole-4` (387, 165)).
- **The 8 pyramid misses** are V-gaps at corner spokes, (24, 40, 56, 72) × (191, 193). No q in τ's plane reproduces their codes with these unfolded tap points: the best free fit leaves 6.6·10⁻⁴ in the shares, and the level-1 code comes out 0.6 to 1.4 codes low. The tap points across a corner spoke are wrong there, not only q.

### 5. Which taps are chosen: not yet predicted

Several rules were scored against the decoded tap sets of the 816 single-triangle atlas texels:

| Rule | Exact sets |
|---|---|
| 4 nearest covered texels of the item by unfolded distance | 291 / 816; it pulls in texels from triangles across the apex |
| Own covered 8-neighbours plus every texel of the triangles that share a 3D edge with τ, 4 nearest by unfolded distance | **613 / 816** |
| Own covered 8-neighbours plus the 2×2 window around the far point unfolded across each crossed seam edge (decision 268's seam window) | 515 / 816 |

**The misses fall into two kinds.**
- **Near a fan's apex.** Painter takes fewer taps than are available. Some texels copy their one own neighbour while far texels lie nearer. Others take the far tap from the triangle across the other spoke, not the one the texel is beyond.
- **Just outside a 3D convex corner of the fan's rim.** Painter takes an own texel two rows in, at UV offset (0, −2), as a fourth tap, although a far texel is nearer. Decision 269 found that a flat straight edge never takes that tap.

So the tap set at poles is not yet a rule. The weights and the value are exact given the taps (findings 2 and 3).

### 6. Decision 269's other open items

- **(b), the L-side lead.** It is the order of two tied 1/d shares (decision 268). It goes to decision 267's tie-order work, and was not tested here.
- **(c), 2 sides + 2 diagonals on `seam-r1-turn30`.** It is a 4-tap texel under decision 268's generator. This pass did not decode it separately. Decision 268 counts `seam-r1-turn30` among its 655 exact flat atlas texels per probe.
- **(d), the fan V-gap.** Partly closed: three candidate positions cover 125 of 133 texels (finding 4). The selector is open.
- **(e), `sphere-256`.** Decoded: 2,088 of 2,120 decoded texels are bit-exact. 32 border-row texels and 56 undecoded texels are open.
- **(f), cube corners across a seam.** Closed (finding 2): 60 of 60 and 62 of 62 decoded texels are exact on each atlas probe.

## Decision

1. **Recorded, not implemented.**
   - Item 2.7 stays open. `src/export/padding.h` keeps decision 223's coverage-only rule, and EXC-007 stays withdrawn (decision 259).
   - No production code, semantics entry, capability, conformance case, exception or test changes.
2. **Identified, for the integration.** These use the same generator and chain as decisions 267 and 268:
   - **The ring point:** the ring texel's centre extrapolated through its own triangle τ.
   - **The tap points:** taps on other faces rotated into τ's plane about the shared edge.
   - **The weights:** decision 268's quantised 1/d shares.
   - **The value:** the FMA lerp chain.
   - **Where it is exact:** on every decoded single-triangle pole and cube-corner texel of the 4 atlas probes (816 of 816 each), and on 1,896 of 1,928 on `sphere-256`.
3. **Rejected:**
   - plain 3D distance on the pyramid and on cube corners;
   - the mean of the V-gap extrapolations;
   - more than 4 taps at an apex (it was an NNLS artefact);
   - the tap-set rules of finding 5.
4. **Still open:**
   - **(a)** The V-gap position selector: which of the higher-index triangle, the lower-index triangle or per-tap applies (finding 4). This is probably a float32 object-space tie-break of the two equidistant own neighbours, as in decision 267.
   - **(b)** The 8 pyramid corner-spoke V-gaps: the tap points across a corner spoke.
   - **(c)** The tap set at poles and cube corners (finding 5): the cap below 4 near an apex, which far triangle, and the (0, −2) own tap at rim corners.
   - **(d)** `sphere-256`: the 32 row-255 texels and the 56 undecoded texels. `bevelled-cube-256`: all 2,341 multi-tap texels, which need an unfolding across several bevel facets (finding 3).
   - **(e)** The order of tied shares, which goes to decision 267.
5. **No new recording is requested.** The next step is offline: run decision 267's own-triangle comparator in float32 on the V-gap neighbour pairs, then fit the tap-set rule on the decoded sets. Owner: `phase1.25_pilot-wand` item 2.7.

## Consequences

- **Weights and arithmetic are done.** At poles and cube corners, the weights and the arithmetic are known everywhere a single triangle owns the ring texel. Decisions 267, 268 and 270 now share one weight generator, so no kernel-shape fitting remains.
- **Item 2.7 still waits** on three selectors: the tie order (decision 267), the V-gap position and the pole tap set.
- **These need no retesting** as a pole or cube-corner kernel: smooth kernels, more than 4 taps, and plain 3D distance on folded geometry.
