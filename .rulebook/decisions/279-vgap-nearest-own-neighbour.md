# 279. The V-gap ring point comes from the triangle of the nearest own neighbour under decision 273's comparator, ties toward +u; an own neighbour in another island takes the nearer of two distances; seam edges feed the far window only within about 1.8 texels of the ring texel

**Status**: accepted
**Date**: 2026-10-19
**Related Tasks**: phase1.25_pilot-wand, phase1.18_export-engine, phase1.16_export-processing-encoders

## Context

On 2026-10-18 the owner ruled that the Wand must match Painter everywhere, padding included. Exact `infinite` padding on UV islands (item 2.7 of `phase1.25_pilot-wand`) is the critical path.

**What was open:**
- **Decision 270, open item (a): the V-gap position.** A ring texel whose own neighbours lie in two triangles that meet only at a UV vertex uses one of three positions: the higher-index triangle's extrapolation (104 texels per atlas probe), the lower-index one (1), or each tap through its own triangle (20). Together they cover 125 of 133 texels. No UV rule chose between them, and the moved atlas switched 4 of them.
- **Decision 270, open item (b):** the 8 `pole-8-pyramid` V-gaps at corner spokes.
- **Decision 277, open items (b) and (c):** the Wand's 34 single-triangle convex seam texels whose Height is inconsistent (22 on the end cap), and its 57 inconsistent multi-triangle texels.
- **Decision 275, open item (c):** how far from the ring texel a seam edge may lie and still feed the far window. On the Wand, the seam edges of the own neighbours' triangles alone gave 4,505 all-four texels, against 4,133 for every seam edge of the own island (production C++ path). The probes slightly favoured the whole island.

**The data**, all read from the private store:
- decision 272's sweep seams probes (`export-padding-tie-sweep-seams-{centred,offcentre,box320}`, r1 `infinite`, 8 User channels). They hold 69 V-gap copies per box, 3 V-gap ring texels each, so 207 per box;
- decision 266's kernel atlas probes (512, 1024, 2048, 1024-moved), with decision 270's tap decodes (`pad270/`, read only);
- the Wand v1's r1 PNG 16 maps (`wand-v1`).

**How it ran:**
- **The model.** `tests/export/padding_reference.py` (commit 887aea7) was subclassed in private scratch (`pad279/`), with variants for the triangle choice, the distance of an own neighbour in another island, and the seam-edge reach.
  - Its geometry matches the C++ path: on the Wand, the own-triangle seam reach gives 4,505 all-four texels and the whole-island reach 4,133, the same counts as the production runs.
- **Scoring.**
  - Probes: all 24 channels bit-exact.
  - Wand: BaseColor, Roughness and Metallic (BRM) exact. Height is scored as decision 277's LP consistency (the L16F operand cannot be recovered from PNG 16) and, for comparison, as exact codes.
  - Exactly tied shares may take any order, as in decisions 275 and 277.
- **The concave gate.** Decision 277's 10° is used only as a placeholder for diagnosis. θ₀ belongs to decision 278.
- On the CPU with numpy and scipy: no Painter, no GPU and no writes to Assets3D. The scripts stay in private scratch, because they read oracle values.

## Findings

### 1. The V-gap position is the triangle of the nearest own neighbour under decision 273's comparator

**The rule.**
1. For every covered 8-neighbour n of the ring texel, compute decision 273's comparator distance: the ring texel extrapolated through n's own triangle (box-normalised positions, inverse-matrix UV barycentrics with the GPU reciprocal, the FMA interpolation, the FMA squared distance and the GPU sqrt).
2. τ is the triangle of the nearest n.
3. An exact tie goes to the neighbour with the larger column (+u), then the one higher in v (+v).

This replaces the reference's "highest-index own triangle".

**Sweep seams, weight level.** Each V-gap texel's decoded weights were classified as left triangle, right triangle or per-tap:

| Box | Comparator picks left → Painter left / per-tap | Comparator picks right → Painter right | Contradictions |
|---|---|---|---|
| `centred` | 4 / 4 | 199 | 0 |
| `offcentre` | 0 / 1 | 206 | 0 |
| `box320` | 46 / 47 | 114 | 0 |

621 of 621 texels agree.
- The higher-index rule fails wherever the comparator's left neighbour is nearer. That happens on 9 texels in the exact boxes and 93 in `box320`.
- Face-order reversal (H2) flips the index but not the side. The tie goes to +u in both orders, so the order of the faces does not enter.

**Atlas, with decision 270's decoded taps.** The comparator picks the position that fits on every V-gap texel where one fits:
- 125 of 125 on `atlas-512`, `-1024` and `-2048`;
- 124 of 124 on `atlas-1024-moved`.

The 4 moved-atlas switches of decision 270 are all predicted: on pole-4, 7 → 6 on the higher triangle and 1 → 2 per-tap; on pole-12, 35 → 32 higher and 0 → 2 lower. `pole-4` (387, 165), the one lower-index texel, is predicted too. The per-tap class is finding 2's rule.

### 2. An own neighbour in another island: the nearer of its own triangle's extrapolation and q

The fan's triangles are separate UV islands. Their shared spoke is a seam edge.

**The rule for an own 8-neighbour that lies outside τ's island:**
- If a far window reaches it, it is a far tap. Its distance is |q − tap| in τ's frame, as before.
- Otherwise its distance is min(|q_k − P|, |q − P|). Here q_k is the ring texel extrapolated through the neighbour's own triangle k, P is the tap's position and q is τ's ring point.

**Where each form shows:**
- **Below a shared base vertex** (the sweeps' row 4, the atlas's 20 per-tap texels), the own-extrapolation term is the smaller one. With the nearest-neighbour τ of finding 1, it reproduces every per-tap texel.
- **The 8 pyramid corner-spoke misses** (decision 270, open item (b)) need the other term. On each, the one own neighbour outside the windows matches only at its raw 3D distance from q, while the window taps take the unfolded distance. A brute force over the per-tap forms finds exactly that assignment.

**Far windows across every own island.** The windows come from the seam edges of every island that owns an own neighbour, not only τ's island. q is folded into the far triangle as in decision 275. This is how a V-gap reads texels of τ's own island two columns out, for example (−2, 0) and (−2, −1).

### 3. Bit-exact counts on the probes

**Sweep seams.** Rule = findings 1 and 2. "Boundary free" means the exact-half-texel rounding of f is left open (the next paragraph explains it).

| Box | V-gap texels: reference (highest index) | Comparator τ only | **Rule, boundary free** | Single-triangle ring texels (reference = rule) |
|---|---|---|---|---|
| `centred` | 181 / 207 | 203 | **207 / 207** | 6,581 / 6,966 |
| `offcentre` | 188 / 207 | 206 | **207 / 207** | 6,574 / 6,966 |
| `box320` | 91 / 207 | 132 | **195 / 207** | 6,573 / 6,966 |

- **The boundary rounding.** On a V-gap, the fold of q into the other island lands exactly on a texel centre. So floor(f_u − ½) and ceil(f_v − ½) are decided by rounding.
  - Below the base vertex, Painter always takes the lower side on both axes (52 of 52).
  - In the V, it takes either side depending on the copy.
  - This is decision 275's open item (b), the float32 recipe of f, now with 60 more sweep texels to fit. It was not fitted here.
- **The 12 remaining `box320` texels** take q from the right triangle, but they also take a texel of the left island at (−2, −1). That texel would lie in a window around the ring texel in the left island. No fold of the right triangle's q gives that window. This is open.
- The single-triangle misses are the seam own-diagonal tie order (decision 273, open item (b)). The rule does not change them.

**Kernel atlas,** every ring texel. The tap set is the reference's, and decision 270's finding 5 (the pole tap set) still limits it:

| Probe | Multi-triangle: reference | **Rule** | Single-triangle: reference | Rule |
|---|---|---|---|---|
| `atlas-512` | 232 / 280 | **262 / 280** | 2,746 / 2,860 | 2,757 |
| `atlas-1024` | 232 / 280 | **262 / 280** | 2,744 / 2,860 | 2,757 |

By item, on `atlas-512` (multi-triangle):
- `pole-12`: 33 → 44 of 44;
- `pole-4`: 7 → 9 of 9;
- `pole-8`: 22 → 25 of 28;
- `pole-8-pyramid`: 10 → 21 of 28.

### 4. Seam-edge reach: a distance cap, not the concave gate

These are the Wand's 6,334 ring texels, with the comparator τ throughout. "All four" is Height exact plus BRM exact.

| Reach | Gate | All four | BRM + Height consistent | Height inconsistent |
|---|---|---|---|---|
| Every seam edge of τ's island (production, decision 275) | none | 4,133 | 4,283 | 880 |
| The same | concave ≥ 10° (placeholder) | 4,290 | 4,463 | 441 |
| Seam edges of the own neighbours' triangles | none | 4,505 | 4,663 | 852 |
| The same | 10° | 5,464 | 5,724 | 89 |
| **Every own island's seam edges within D texels of the ring texel (UV segment distance), D = 2** | 10° | **5,500** | **5,765** | 88 |
| The same, D = 1.5 | 10° | 5,512 | 5,777 | 84 |
| The same, D = 2 | none / convex only (0°) / 20° | 4,540 / 5,121 / 5,437 | — | — |

Decision 277's rule gives, on its own pools, 5,465 all four and 6,242 Height consistent. The own-triangle row with the gate reproduces it in this model: 5,464 and 6,245.

**The concave gate does not explain the island deficit.** Gating the whole island recovers only 157 of the 1,331 texels it loses against the gated own-triangle reach (4,133 → 4,290, against 5,464). The rest come from **distant seam edges**:
- they are convex or shallow;
- their fold maps q next to far texels;
- they add far taps that Painter does not take.

Capping the reach by distance recovers them. The gate is still needed on top of the cap (4,540 without it).

**The probes bound the cap from below.** The whole island, or the cap, is needed at seam corners:

| Cap D | Sweep `centred`, single-triangle | `atlas-512`, single / multi |
|---|---|---|
| 1.5 to 1.7 | 6,512 | 2,753 / 262 |
| 1.8, 1.9, 2, 3 or the whole island | **6,581** | **2,757 / 262** |
| Own-triangle seam edges only | 6,439 | 2,734 / 262 |

- The own-triangle reach loses 150 seam-corner texels per sweep box. There the seam edge belongs to the quad's other triangle, about 1.77 texels from the ring texel.
- So D lies in (1.7, 1.8] on the probes. On the Wand, D = 1.8 gives 5,504, which is 8 fewer than D = 1.5. Those 8 texels are open.
- The ramp probes were not rescored within the box.

### 5. The Wand's remaining classes

**Multi-triangle texels** (447):

| Rule | BRM + Height consistent | Height inconsistent |
|---|---|---|
| Decision 277's rule in this model | 180 | 50 |
| **This rule (D = 2, 10° placeholder)** | **231** | 43 |

Most of the Wand's multi-triangle texels are not V-gaps. Their two triangles share an island on the curved shaft. 215 still miss in BRM. Their tap set and positions on curved charts are open.

**The single-triangle convex seam texels that are Height-inconsistent** (decision 277, open item (b)): 37 under the own-triangle reach, 45 under D = 2.
- **Where they are.** They sit on three islands:
  - the 12-triangle end cap, at convex folds of 65.2° to 66.2° (15 texels);
  - the 120-triangle tip piece, at about 65° and 29° (12);
  - the 1,104-triangle shaft, at 18.8° to 37.9° (10).
- **Not a gate.** Own taps only (a convex gate) makes 2 of 37 consistent, and the whole island makes none.
- **A pointer.** 17 of the 37 have a far tap in a face with no hinge to τ's face, against 6% of all seam texels. That tap falls back to its raw 3D position, as on `bevelled-cube-256` (decision 270, finding 3). The likely cause is a distance across several facets. It was not built within the time box, and the item stays open.

## Decision

1. **Recorded, not implemented.**
   - Item 2.7 stays open, and EXC-007 stays withdrawn (decision 259).
   - No production code, semantics entry, capability, conformance case, exception or test changes. `tests/export/padding_reference.py` and `src/export/` are unchanged; another pass integrates this rule.
2. **Identified, for the integration:**
   - **(a) The ring triangle τ** is the triangle of the own covered 8-neighbour nearest under decision 273's comparator. An exact tie goes toward +u, then +v. It replaces "the highest-index own triangle".
   - **(b) An own neighbour outside τ's island** that no far window reaches takes min(|q_k − P|, |q − P|). One that a window reaches is a far tap.
   - **(c) The far windows** come from the seam edges of every island that owns an own neighbour. Only edges whose UV segment lies within D of the ring texel's centre count, with D ∈ (1.7, 1.8] texels from the probes. They go through decision 277's concave gate.
   - **Where it is exact:**
     - the sweep V-gaps: 207 + 207 + 195 of 621, with the exact-boundary rounding of f left open;
     - the atlas multi-triangle ring: 262 of 280, against 232;
     - the Wand: 5,500 all four (5,512 at D = 1.5), against 5,464 in this model of decision 277's rule.
   - It closes decision 270's open item (a) and decision 273's open item (c) (the V-gap position). It partly closes decision 270's (b): 8 of 8 pyramid misses are reproduced at the weight level by (b). It answers decision 275's open item (c) with a distance cap.
3. **Rejected, with the counts above:**
   - the highest-index (or lowest-index) own triangle as the V-gap position;
   - the concave gate as the explanation of the island against own-triangle difference (it recovers 157 of 1,331);
   - the own neighbours' triangles alone as the seam reach (−150 seam-corner texels per sweep box);
   - the whole island without a cap (4,336 on the Wand with the rest of this rule, against 5,500 capped).
4. **Still open:**
   - **(a)** The float32 rounding of the far point f at an exact texel centre. It decides the V-gap windows: below a base vertex the lower side always, in the V either side. This extends decision 275's open item (b).
   - **(b)** The 12 `box320` V-gap texels that take a left-island texel no fold explains.
   - **(c)** The exact cap D and its measure. The probes give (1.7, 1.8]; the Wand prefers 1.5 by 8 texels.
   - **(d)** The Wand's 37 to 45 Height-inconsistent single-triangle convex seam texels: likely a distance across several facets, as on `bevelled-cube-256`.
   - **(e)** The Wand's 215 multi-triangle BRM misses on curved shared islands.
   - **(f)** θ₀ (decision 278). Everything here used 10° only as a placeholder.
5. **No new recording is requested.** Owner: `phase1.25_pilot-wand` item 2.7.

## Consequences

- **The V-gap no longer depends on triangle order.** It is decided by the same float32 comparator as the straight-edge tie order (decision 273).
- **The integration changes three things:**
  - τ comes from the comparator;
  - the distance of an own neighbour in another island is the nearer of two;
  - the seam windows of every own island, capped at about 1.8 texels, replace the uncapped τ-island loop of decision 275.
- **These need no retesting:**
  - index-order V-gap rules;
  - the mean or UV-nearest V-gap position (decision 270);
  - the concave gate as the cause of the island against own-triangle gap.
