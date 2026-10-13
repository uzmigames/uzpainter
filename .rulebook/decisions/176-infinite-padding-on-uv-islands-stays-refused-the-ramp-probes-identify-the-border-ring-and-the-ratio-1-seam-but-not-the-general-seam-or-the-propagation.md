# 176. `infinite` padding on UV islands stays refused: the ramp probes identify the border ring and the ratio-1 seam, but not the general seam ring, its micro-offset or the propagation

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase1.25_pilot-wand, phase1.18_export-engine, phase1.16_export-processing-encoders

## Context

Item 2.7 of `phase1.25_pilot-wand` asks for an exact fit of `infinite` padding on UV-islanded sets. Decision 129 left three open items: (a) building the ring, (b) the propagation rule, (c) the sphere poles. Decision 167 admitted the probes decision 129 specified:
- P-ramp: `export-padding-ramp-{r1,r2,r15}-{p0,p25,p75}-v2`, document 1024;
- P-tie: `export-padding-tie-512` (decision 160) and `export-padding-tie-2048-v2`.

User0 is RGB32F and holds R = (x + 0.5)/N, G = (y + 0.5)/N. A padded texel therefore names the source position, or the mixture of positions, it was made from. Infinite exports are equal in r1 and r2 and between the two steps of each recording, so r1 step 10 is used throughout.

The work was time-boxed at 2 hours, on the CPU, from the private store, without Painter. Only numbers are given here. Comparison is on float32 bit patterns, no tolerance. The scripts stay in private scratch (`pad176/`).

## Findings

### 1. Border ring (an island edge with no seam): identified up to a micro-offset

- **Rule.** A ring texel (uncovered, 8-adjacent to a covered texel) is the mean of its covered 8-neighbours weighted 1/distance: 1 for an edge neighbour, 1/√2 for a diagonal. At a corner this gives √2 - 1 = 0.41421 of a texel along the edge, as observed (tie-512, tie-2048).
- **Micro-offset.** Every ring texel with two diagonal sources differs from that mean along the edge by exactly ±k·2⁻¹⁵ of the neighbour step. k = 25 at 512 and 24 at 1024 and 2048, the same in every value range. Perpendicular to the edge the value is exact.
  - Bit-exact ring texels under the rule: 30 of 780 (tie-512) and 26 of 3084 (tie-2048), all of them at corners.
  - The sign is unidentified. On the 256-texel islands at 1024 it is constant (top ring +, left ring −). On tie-512, tie-2048 and the 384-texel island of r15 it varies along the edge. It follows the position along the edge more than the absolute position.
  - A constant field cancels the offset. That is why decision 129's constant-fill seam goldens showed no offset.

### 2. Seam ring: identified only at ratio 1, and for B at ratio 2 phase 0

- **Ratio 1, all three phases.** Each seam ring texel is a bit-exact copy of the texel across the seam under the affine unfold: A's ring takes B's last row, and B's ring takes A's last column. That is 252, 251 and 251 interior texels per side for p0, p25 and p75. The unfold maps the ring centre exactly onto that texel's centre.
- **Ratio 2, phase 0, B's ring.** Each texel is the equal mean of the 2×2 A texels around the unfolded centre, which lies on an A texel corner. This is bit-exact on 124 of 124 interior texels.
- **Ratio 2, phase 0, A's ring.** It is a two-part blend:
  - A's own 8-neighbour mean (value (383, r)) with weight 0.6304985;
  - the B texel nearest the unfolded centre with weight 0.3695015.

  A 1/distance weight on that B texel (d = √0.5) predicts 0.6306019. That is off by 1.0·10⁻⁴, so this is not exact.
- **Not identified.** Ratio 2 at p25 and p75, ratio 1.5 at every phase, and every seam corner.
  - The blend weights vary with phase: A's own weight alternates 0.460410/0.454688 (r2-p25) and 0.718144/0.656158 (r2-p75); r15-p0 cycles 0.2375/0.2121/0.1912.
  - Rejected with numbers: a 1/distance mean over own and unfolded across-seam texel centres, for radii 0.8 to 1.5. It leaves residuals of 0.5 to 200 texels on these probes. An affine unfold with bilinear sampling of the final texture is also rejected, as in decisions 127 and 129: at r2-p0 it predicts 0.25 of B's ring row in A's ring, and the observed blend has no such term.

### 3. Propagation: the decision-129 candidate fails on independent data

Seeded by the recorded ring (8-neighbour, with x wrap), the jump flood of decision 129 and an exact Euclidean nearest-seed transform were scored on every new probe's gutter (r1 step 10). Only the first three of decision 129's twelve orderings were run, and they agree everywhere.

| Probe | Gutter texels | Jump flood, missed | Exact Euclidean, missed | Gutter values found in no ring texel |
|---|---|---|---|---|
| tie-512 | 249076 | 52 | 171 | 52 |
| tie-2048-v2 | 3994612 | 1199 | 2700 | 1199 |
| ramp-r1-p0 / p25 / p75 | 915448 | 5436 / 5436 / 6911 | 8413 / 8413 / 8358 | 0 |
| ramp-r2-p0 / p25 / p75 | 965112 | 1370 / 1370 / 6029 | 6784 / 6784 / 6407 | 0 |
| ramp-r15-p0 / p25 / p75 | 833016 | 477 / 474 / 448 | 776 / 773 / 746 | 0 |

- The jump flood beats the exact Euclidean copy on every probe, but it is exact on none of them.
- On tie-512 the misses are one cluster, rows 152-159 and columns 500-511. On tie-2048 they are one cluster, rows 601-639 and columns 1988-2047. On ramp-r1-p0 they are one cluster, rows 896-958 and columns 902-1023. Each cluster touches the right border of the tile (column N - 1).
- On the tie probes, every missed texel holds one covered texel's own value: (415, 353) at 512 and (1663, 1409) at 2048. That is the second row of the last column of the island at u0 = 0.6875. No ring texel holds that value, so the ring alone is not the seed set.

## Decision

1. `infinite` padding on islanded sets stays refused before writing (`padding.h`, `NotYetSupported` naming R-090). Item 2.7 stays unchecked. No production code, semantics entry, capability or conformance case changes.
2. **Proven, recorded for the next fit:**
   - the border-ring weights (1, 1/√2) up to the micro-offset;
   - the ratio-1 seam copy;
   - the ratio-2 phase-0 B-ring 2×2 mean.
3. **Open.** Each of these blocks exactness on its own:
   - **(a)** The ring micro-offset: its sign rule, and k = 25 against 24. Without it no ring of a varying field, and so no gutter, is bit-exact.
   - **(b)** The seam blend at non-unit ratios and fractional phases, and at the seam corners.
   - **(c)** The seed set and order of the propagation. Covered texels' own values reach far gutter texels that no ring texel holds, and every residual cluster touches the tile's right border.
   - **(d)** The sphere pole texels (decision 129 (c)), not revisited.
4. **No new recording is requested.** The ramp and tie probes hold the data for (a) to (c). What is missing is the mechanism, not observations. (d) needs only the existing sphere golden. Owner: `phase1.25_pilot-wand` item 2.7.

## Consequences

- G1's P1-WAND gate (items 3.1 and 4.1) and the wand's five-map export stay blocked on 2.7, as decisions 127 and 129 recorded.
- The next attempt starts from findings 1 to 3. Decision 129's candidate is rejected on the P-tie and P-ramp gutters.
