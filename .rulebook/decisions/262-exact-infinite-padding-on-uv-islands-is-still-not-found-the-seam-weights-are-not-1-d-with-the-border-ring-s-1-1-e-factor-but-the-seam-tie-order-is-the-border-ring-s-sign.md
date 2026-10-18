# 262. Exact `infinite` padding on UV islands is still not found: the seam weights are not 1/d with the border ring's 1/(1+e) factor, but the seam's tie order is the border ring's sign

**Status**: accepted
**Date**: 2026-10-18
**Related Tasks**: phase1.25_pilot-wand, phase1.18_export-engine, phase1.16_export-processing-encoders

## Context

On 2026-10-18 the owner ruled that the Wand must match Painter everywhere, padding included. That makes exact `infinite` padding on UV islands (item 2.7 of `phase1.25_pilot-wand`) the critical path. This pass took one piece of it: the seam ring.

What decisions 211 and 217 left:
- each seam-ring value is a mean of at most four covered texels from both islands, weighted about 1/d, with d measured in the unfolded plane;
- the 1/d weights are off by about 10⁻³, and this survives exact geometry;
- the tap choice is wrong on 208 r15 texels;
- the seam corners have no rule.

**The hypothesis.** The brief proposed that the seam ring and the border ring are one mechanism. Decision 217 found that the border ring's along-edge shift equals one tied diagonal's weight divided by 1 + e, with e ≈ 1/384. The test:
- seam weights are w = 1/d for axis taps and 1/(d(1 + e)) for the others, with the same e;
- e is solved exactly from two equations: B's share at r2-p0, 0.3695015, and B's ring at r2-p25, (0.351196, 0.649719);
- the taps are the four nearest in the unfolded plane under that metric, with ties broken in a fixed order;
- the same rule then gives the seam corners.

The data are the ten position-encoded seam probes, r1 `infinite` OpenEXR 32f (User0 RGB32F):
- `export-padding-ramp-{r1,r2,r15}-{p0,p25,p75}-v2`;
- `export-padding-seam-ramp-1024` (decision 216).

Each was read from the private store. Each mesh's `vt` values were read as float32 and mapped to world (x, z) by each island's affine map.

**The test set** is every seam-ring texel inside a run (each run's first and last texel left out). That is 3,684 texels outside the ratio-1 probes. The ratio-1 probes are 1,524 copies, all bit-exact, as decision 176 found.

**The fit measure** is the one decision 211 used. A texel fits when the smallest per-tap relative change of the weights that reproduces Painter's value exactly (a least-norm solve) is at most 0.6 %.

Everything ran on the CPU, without Painter, without a GPU and without writing to Assets3D, within the 2-hour time box. Only numbers are recorded here. The scripts stay in private scratch (`pad262/`), because the earlier `pad211/`, `pad217/` and `pad220/` folders were not on this machine.

Terms:
- **Axis tap.** A tap whose offset from the ring point has one zero component in world axes: x across the seam, z along it.
- **Own diagonal.** A diagonal 8-neighbour from the ring texel's own island.
- **Strip.** The far island's covered texels whose along-seam coordinate lies in one of the two far-grid lines that bracket the ring point.

## Findings

### 1. No single e exists, and r2-p25 alone rules the hypothesis out

**r2-p0, A ring.** It gives one usable equation per texel. B's share there is 0.36950147 ± 4·10⁻⁸ over 254 texels. Each way of applying 1/(1 + e) needs its own e to reproduce it:

| Taps divided by 1 + e | e that reproduces B's share at r2-p0 | Compared with 1/384 = 2.604·10⁻³ |
|---|---|---|
| Own diagonals | +7.582·10⁻⁴ (1/1319) | 3.4 times smaller |
| Every non-axis tap (own diagonals and the far tap) | −1.071·10⁻³ (−1/933) | opposite sign |
| Far taps only | −4.438·10⁻⁴ (−1/2253) | opposite sign |

**r2-p25 and r2-p75, B ring.** The hypothesis cannot fit these for any e:
- all four taps are far, non-axis and not own diagonals, so every variant scales all four by the same factor and leaves the value unchanged;
- the residual stays at 1/d's 8.2·10⁻⁴ A texel on all 126 texels of each probe.

The cause is a symmetry. At r2-p25 two of the four taps are tied (both at d = 0.3953 B texel), and they mirror each other across the line through q:
- any kernel that depends only on d gives a mean whose two fractions sum to exactly 1;
- Painter's fractions sum to 0.351196 + 0.649719 = 1.000915.

So Painter weights the two tied far taps unequally (solved multipliers 1.0038 and 1.0084 against 1/d). Any rule that gives equal weights to equal distances is rejected on these 252 texels.

**Per-texel e on the other probes.** Solving e per texel (two equations, one unknown) scatters it, with interquartile ranges of 10⁻³ to 10⁻²:
- own diagonals: −1/165 to +1/226 by probe;
- non-axis taps: −1/161 to +1/116;
- far taps: −1/390 to +1/140.

**Global counts at a fixed e = ±1/384,** out of 3,684 texels:

| Kernel | e | Fit at 0.6 % | Fit at 10⁻⁴ |
|---|---|---|---|
| Plain 1/d | none | 3,099 | 126 (only the equidistant r2-p0 B ring) |
| Own diagonals ÷ (1 + e) | +1/384 | 3,099 | 126 |
| Own diagonals ÷ (1 + e) | −1/384 | 3,099 | 126 |
| Non-axis ÷ (1 + e) | +1/384 | 2,972 | 126 |
| Non-axis ÷ (1 + e) | −1/384 | 3,071 | 126 |
| Far ÷ (1 + e) | +1/384 | 2,972 | 126 |
| Far ÷ (1 + e) | −1/384 | 3,071 | 126 |

No variant makes a single further texel bit-exact.

### 2. The sample-point reading is confirmed, and it has no common frame

The displacement s of q that makes plain 1/d exact was solved per texel, in world axes and own-island texels. It reproduces Painter to float precision on every texel. It is constant within a probe class but differs between classes:

| Class | s, across and along the seam |
|---|---|
| r2-p25 B | (+0.00094, −0.00049) |
| r2-p75 B | (+0.00055, −0.00096) |
| r2-p0 A | (+0.00026, 0.00000) |
| r15-p0 B and seam-ramp B, alternating | (−0.00228, −0.00132) and (+0.00146, −0.00121) |
| r15-p25 A | (−0.00222, −0.00008) |
| r15-p75 A | (−0.00253, −0.00071) |

This repeats decision 217 finding 3. No fixed world, own-UV or far-UV displacement covers them.

A fifth tap with a free weight also fits the residual. But the weights it needs are negative (about −10⁻³), so that reading is rejected.

### 3. The tap choice is identified, except on 127 texels

**The best subsets are well separated.** For each texel, every 3- to 5-subset of its 9 nearest candidates was scored. The best one fits on all 3,684 texels. The second-best is typically 20 times worse (median ratio 12 to 124 by class), so each texel's tap set is identified.

**The rule that reproduces them:**
1. **Candidates.**
   - The ring texel's own covered 8-neighbours.
   - The far island's covered texels in the strip. Decision 211's two rows *along* the seam are replaced by two lines *across* it. For example, at r15-p75 B the 4th-nearest far texel lies outside the strip and is skipped, which is Painter's choice.
2. **Taps.** The four nearest candidates by unfolded distance.

**How far it goes:**
- With that alone (stable order on ties), 3,226 of 3,684 texels fit.
- With Painter's choice where two own diagonals tie for the 4th slot, 3,557 fit.
- **The 127 texels left** are r15-p25 B's alternate rows. Painter keeps a far texel one line outside the strip, at d = 0.888, ahead of B's own side neighbour at d = 1.000. In the other rows it drops a strip-outside texel at d = 0.919 in favour of that side neighbour and a texel at d = 1.033. No distance threshold or strip width separates the two.

**The tie order is the border ring's sign.** The fixed-order part of the brief's rule fails, and what replaces it is the useful result of this pass.
- On A's seam ring at r2-p25, r15-p25 and r15-p75, two own diagonals tie for the 4th slot on 381 texels.
- Painter keeps the −row diagonal (+v) on 361 of them, and the +row diagonal on 20: 10 at r15-p25 and 10 at r15-p75, every third row.
- Those 20 rows are exactly the rows where A's left straight edge, a non-seam edge of the same island, has decision 206's along shift in the +row direction: 20 of 20.
- Of the 361 regular rows, 1 has a +row left-edge shift.

So the seam tie and the straight-edge sign are one per-row ordering of two tied taps. It comes from the same object-space quantity, still unidentified (decision 210 4(a), decision 217 4(a)).

### 4. The seam corners do not follow from the rule

The two corner ring texels per island and probe were scored the same way (best 2- to 5-subset of the 10 nearest, at 1/d):
- **r1, all three phases.** 12 of 12 fit with three taps: the far side neighbour (d = 1), the own diagonal (√2) and the far diagonal (√2), with a perturbation of 1.3 to 1.4·10⁻³. The four nearest miss by 0.18 to 0.87.
- **r2, r15 and seam-ramp: 28 corners.**
  - 10 fit at 0.6 %, with a perturbation of 10⁻⁵ to 6·10⁻³. Their tap sets are mixed: 2 to 4 taps, own diagonals at √2, and far taps up to d = 2.7.
  - 4 fit at 0.66 to 0.89 %. All are B's far-end corners: r2-p25 (704, 384), r15-p0 (819, 410), r15-p75 (820, 409) and seam-ramp (819, 410).
  - 5 fit only loosely, at 2 to 11 %, with taps at d = 2 to 3.2. All are A corners, at r2 (all three phases) and r15-p25 (both).
  - 9 fit no 1/d subset of the 10 nearest: the best perturbation is about 1.0. They are B's seam-start corner on every probe, for example r2-p0 (575, 384) and r15-p0 (562, 410), and A's bottom corner at r2-p25 and r2-p75.

Those 9 corner values must come from other taps or another mechanism. This matches decision 220's attribution of most of the gutter error to seam corners.

## Decision

1. **Nothing in production changes.** `src/export/padding.h` keeps the coverage-only rule of decision 223, as it stands on main.
   - The exact rule is still not found, and item 2.7 stays unchecked.
   - No production code, semantics entry, capability, conformance case, exception or test changes.
   - The brief asked for no production implementation in this pass; an integration pass combines the padding pieces.
2. **Rejected, with the numbers above:**
   - the seam weights as 1/d with the border ring's 1/(1 + e) on own diagonals, on non-axis taps or on far taps, for any single e. The e needed at r2-p0 is 1/1319, −1/933 or −1/2253, never 1/384, and r2-p25 and r2-p75 B cannot be fitted by any e;
   - any rule that weights equal distances equally (finding 1);
   - ties broken in a fixed order (finding 3);
   - a fifth tap with a small weight (finding 2).
3. **Identified, recorded for the integration:**
   - **Seam candidates:** own 8-neighbours, plus the far island's strip (the two lines across the seam that bracket q). The four nearest by unfolded distance fit 3,557 of 3,684 interior seam-ring texels once Painter's tie choice is used.
   - **Seam tie order:** the same per-row order as the straight-edge sign of decisions 206 and 210, on 20 of 20 exceptions.
   - **r1 seam corners:** three taps, the far side neighbour, the own diagonal and the far diagonal.
4. **Still open:**
   - **(a)** The weights. Painter treats two equidistant taps unequally on the seam as on the straight edge. One object-space ordering or offset mechanism probably sets both the weight asymmetry and the tie order. It is the decision-210 4(a) quantity.
   - **(b)** The 127 r15-p25 B texels of finding 3.
   - **(c)** 18 of the 28 r2, r15 and seam-ramp seam corners (finding 4), 9 of them with no 1/d fit at all.
   - **(d)** The sphere poles.
5. **No new recording is requested.** The next measurement is offline: identify the per-row ordering quantity of 4(a) from the 20 r15 exceptions and decision 206's tie sequences, then test whether it also orders the r2-p25 tied far taps.

## Consequences

- The owner's 2026-10-18 ruling (the Wand identical to Painter everywhere, padding included) stays unmet. Its blocker is still item 2.7.
- The seam tap choice and the border-ring sign can now be solved as one problem. A sign rule found for straight edges also chooses the seam ties.
- These need no retesting:
  - the shared 1/(1 + e) seam kernel;
  - radial-only kernels;
  - fixed tie orders;
  - small fifth taps.
