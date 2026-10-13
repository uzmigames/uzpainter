# 211. `infinite` padding on UV islands stays refused: the seam ring is a four-tap inverse-distance mean across the unfolded seam, but its tap choice and weights are not exact

**Status**: accepted
**Date**: 2026-10-13
**Related Tasks**: phase1.25_pilot-wand, phase1.18_export-engine, phase1.16_export-processing-encoders

## Context

Item 2.7 of `phase1.25_pilot-wand` asks for a bit-exact fit of `infinite` padding on UV-islanded sets. Decision 206 fixed the border ring (non-seam edges) up to the sign of its along-edge offset. Decision 197 fixed the gutter as a jump flood. Decision 176 fixed two seam cases:
- at ratio 1, the seam ring is an exact copy of the texel across the seam;
- at ratio 2, phase 0, B's ring is the plain 2×2 mean of A.

Decision 176 left open ratio 2 at p25 and p75, ratio 1.5 at every phase, the seam corners and the sphere poles. This pass took the seam ring and the poles. A parallel agent (padding-sign) holds the decision-206 sign, and this pass did not touch it.

The data is the P-ramp probes `export-padding-ramp-{r1,r2,r15}-{p0,p25,p75}-v2` (1024, User0 RGB32F, r1 step 10). R = (x + 0.5)/N and G = (y + 0.5)/N, so a ring value is a point: the weighted mean of the texel centres it was made from. The meshes are `parity/fixtures/tier0-semantics/meshes/seam-ramp-*.obj`, read with their `vt` rounded to float32.

The test set is every interior seam-ring texel: A's ring column and B's ring row, without each run's first and last texel.

| Ratio | Ring texels per phase | Phases |
|---|---|---|
| 1 | 508 (254 per side) | 3 |
| 2 | 380 (A 254, B 126) | 3 |
| 1.5 | 636 (A 382, B 254) | 3 |

Everything ran on the CPU from the private store, without Painter, within a 2-hour time box. Only counts are recorded here, and the scripts stay in private scratch (`pad211/`).

Terms:
- **Unfolded plane.** Both quads lie in one 3D plane. The world (x, z) of a texel centre is therefore one common frame for both islands, and a ring texel's world position is its own island's UV map extended past the edge.
- **Taps.** The covered texels a ring value is a mean of.
- **Weight perturbation.** The smallest per-tap relative change of the 1/d weights that reproduces the observed value exactly (a least-norm solve). A value of zero means plain 1/d.

## Findings

### 1. Every seam-ring value is a mean of at most four taps from both islands, weighted about 1/d in the unfolded plane

**The rule.** For a ring texel at world point q:
1. **Candidates.** Two sets:
   - its own island's covered 8-neighbours;
   - the far island's covered texels in the two rows, along the seam, that bracket q's position on the far island's grid.
2. **Taps.** The four candidates nearest q, by world distance.
3. **Value.** Their mean, weighted by 1/d.

A tap at distance 0 is a copy, which gives decision 176's ratio-1 rule. Taps equidistant from q give a plain mean, which gives the ratio-2 phase-0 B ring.

The one rule covers both sides:
- At ratio 2, phase 0, B's own row lies 2 A texels away. The four nearest taps are therefore A's 2×2.
- A's taps there are its own three neighbours (d = 1, √2, √2) and the B texel at d = 1/√2. The next B texel, at d = 1.58, is the fifth-nearest and is left out.
- At r15-p25 B's own axis neighbour (d = 1.5) enters, as the 16 % share the values show.

**Counts.** The table counts ring texels reproduced with a weight perturbation of at most 0.6 %, and how many of those are bit-exact.

| Probe | A ring | B ring | Bit-exact |
|---|---|---|---|
| r1-p0, p25, p75 | 254 / 254 each | 254 / 254 each | all 1,524 (copies) |
| r2-p0 | 254 / 254 | 126 / 126 | B 126 / 126 (2×2 mean in float32) |
| r2-p25 | 254 / 254 | 126 / 126 | 0 |
| r2-p75 | 254 / 254 | 126 / 126 | 0 |
| r15-p0 | 382 / 382 | 254 / 254 | 0 |
| r15-p25 | 343 / 382 | 127 / 254 | 0 |
| r15-p75 | 339 / 382 | 254 / 254 | 0 |

- **Overall.** Outside the ratio-1 copies, the rule fits 2,839 of 3,048 texels.
- **Plain four-nearest, without the two-row bracket.** It fits 2,619. It also fits the other 127 r15-p25 B texels, which alternate with the 127 the bracket rule fits.
- **Neither rule.** Together they leave 81 A texels, 39 at r15-p25 and 42 at r15-p75.

**Rejected tap sets, with numbers.**
- **A far-island 2×2 alone** (masked, bilinear or 1/d). It misses every A ring at ratio 2: the observed far-island part is one B texel, the one containing the unfolded point.
- **A fixed radius**, in any island's units. The A ring at r2-p0 needs A's diagonals at d = √2. B's ring at r2-p25 must leave out an A texel at d = 1.275 A texels.
- **Equal 3×3 or radius-1.5 windows.** They are off by 0.1 to 0.3 texel at r15.
- **Kernels other than 1/d.** Each was fitted with one free parameter: d⁻ᵖ (best p = 0.9999), 1/(d + ε), 1/√(d² + ε), 1/d − 1/R, exponential, Gaussian, and 1/d with fp16 rounding in five variants. None lowers the residual below plain 1/d's 1·10⁻³ texel. The Gaussian and exponential reach 3 to 7·10⁻² texel.

### 2. The weights are not exactly 1/d, so no seam blend is bit-exact

The cleanest case is r2-p0, A ring. Its value is (1 − β) times A's own 3-tap mean plus β times the B texel containing the unfolded point.
- On all 252 rows, β = 0.3695015 ± 1·10⁻⁷.
- Plain 1/d gives 0.3693981, so the B weight is 1.000455 times √2.

On B's ring at r2-p25 the unfolded point has fraction (0.25, 0.75) in A's 2×2:
- Painter's value is (0.351196, 0.649719);
- four-tap 1/d gives (0.350373, 0.649627).

The residuals are 1 to 2·10⁻³ texel, of either sign. They are the same order as decision 206's offset reading in 1/d terms, where E·2⁻¹⁵ along corresponds to a sample point moved about 2.6·10⁻³ texel. That points to the same unexplained quantity, but this is not shown.

### 3. Not reached in the time box

- **Seam corners.** Examples: r1-p0 A ring (639, 384) holds (700.114, 458.578), a blend of both islands' corner texels.
- **The 81 texels of finding 1.**
- **The sphere poles.** `export-padding-sphere` is not position-encoded (BaseColor PNG 16), so a pole texel's taps cannot be read from its value. This needs the solved ring weights first.

## Decision

1. `infinite` padding on islanded sets stays refused before writing (`padding.h`, `NotYetSupported` naming R-090).
   - Item 2.7 stays unchecked.
   - No production code, semantics entry, capability, conformance case or golden-comparison test changes.
   - **Why.** No seam blend is bit-exact (finding 2), and the border ring still lacks its sign (decision 206). So the whole padding is exact on no recorded golden.
2. **Identified, recorded for the implementation:**
   - the seam-ring structure: four nearest taps over own 8-neighbours and the far island's two-row bracket, weighted 1/d in the unfolded plane;
   - the cases it reproduces bit-exactly: the ratio-1 copy (1,524 of 1,524) and the equidistant 2×2 mean (126 of 126).
3. **Rejected, with the numbers above:**
   - the far-island 2×2 alone;
   - fixed radii;
   - equal windows;
   - eight one-parameter kernels in place of 1/d.
4. **Still open:**
   - **(a)** The exact weights. The 1/d deviation is 1 to 2·10⁻³ texel, and is probably the decision-206 offset mechanism.
   - **(b)** The tap choice on the 81 r15-p25 and r15-p75 A texels, and on the 127 r15-p25 B texels that only plain four-nearest fits.
   - **(c)** The seam corners.
   - **(d)** The sphere poles (decision 129 (c)).
   - **(e)** The border-ring sign (decision 206, 4(a)).
5. **No new recording is requested.**
   - The next measurement is offline: solve (a) together with decision 206's sign, since both are sub-texel perturbations of a 1/d mean.
   - `export-padding-seam-field-1024` shares r15-p0's B-ring geometry with a non-ramp field. Once its source field is decoded, it gives a second equation per texel for (a) and (b).
   - Owner: `phase1.25_pilot-wand` item 2.7.

## Consequences

- G1's P1-WAND gate and the wand's five-map export stay blocked on 2.7, as decisions 127, 129, 176, 184, 197 and 206 recorded.
- An implementation can reproduce the ratio-1 seam and equidistant seam blends exactly now. Every other seam blend is within about 2·10⁻³ texel, which is not exact.
- The rejected tap sets and kernels in finding 1 need no retesting.
