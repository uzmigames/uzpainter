# 197. `infinite` padding on UV islands stays refused: the gutter is identified as a jump flood, but the ring offset's sign is not

**Status**: accepted
**Date**: 2026-10-13
**Related Tasks**: phase1.25_pilot-wand, phase1.18_export-engine, phase1.16_export-processing-encoders

## Context

Item 2.7 of `phase1.25_pilot-wand` asks for a bit-exact fit of `infinite` padding on UV-islanded sets. Decisions 176 and 184 left two open items:
- **(a) The propagation.** The gutter is flat-Euclidean nearest-ring except for clusters that touch the tile border.
- **(b) The ring offset.** Every straight-edge ring texel carries an offset of exactly ±25·2⁻¹⁵ (512) or ±24·2⁻¹⁵ (1024, 2048) of a texel along the edge. Its sign rule was unknown.

This pass used the same data: the P-ramp probes `export-padding-ramp-{r1,r2,r15}-{p0,p25,p75}-v2` (1024) and the P-tie probes `export-padding-tie-512` and `export-padding-tie-2048-v2`. Each is User0 RGB32F at r1 step 10, where R = (x + 0.5)/N and G = (y + 0.5)/N.

Everything ran on the CPU from the private store, without Painter, within a 2-hour time box. Comparison is on float32 bit patterns, with no tolerance. Only counts are recorded here. The scripts stay in private scratch (`pad197/`).

Terms, as in decision 184:
- **covered**: a texel whose value equals its own position;
- **ring**: uncovered and 8-adjacent to a covered texel;
- **gutter**: every other uncovered texel.

"Seeded with Painter's ring" means the propagation starts from Painter's own ring values. This isolates (a) from (b).

## Findings

### 1. The gutter is a jump flood: bit-exact on all 11 probes

**Rule.** Every texel holds a seed position.
- **Seeds.** The seeds are every covered texel and every ring texel. Each starts holding its own position.
- **Steps.** k = N/2, N/4, …, 1, with ping-pong updates: each step reads only the previous step's state.
- **Candidates.** At each step a texel compares its own seed with the seeds held at the 8 offsets (±k, 0, ±k). An offset outside the image is skipped.
- **Metric.** The squared Euclidean distance between texel centres, compared exactly as integers.
- **Ties.** A tie between axis neighbours goes to (dy, dx) = (0, +k), then (0, −k), then (−k, 0), then (+k, 0). Here dy is the row offset and row 0 is the top of the exported image.
  - On these probes the result does not depend on the order among the diagonals, on axis against diagonal, or on the texel's own seed against a neighbour.
  - Twenty-four such orderings were checked and all give the same zero.
- **Value.** A gutter texel copies the value of the texel its seed names.

**Result.** Seeded with Painter's ring, the rule misses **0 of 12,384,416 gutter texels**. That covers every probe, phase and resolution.

| Probe | Gutter | This rule | Ring-only seeds | Default 3×3 order (rows −k, 0, +k, columns −k, 0, +k, first wins) | Extra pass k = 1 at the end | Axis ties reversed |
|---|---|---|---|---|---|---|
| tie-512 | 249,076 | **0** | 80 | 52 | 30 | 0 |
| tie-2048-v2 | 3,994,612 | **0** | 1,323 | 1,199 | 126 | 0 |
| r1-p0 / p25 / p75 | 915,448 | **0 / 0 / 0** | 5,436 / 5,436 / 6,911 | 6,855 / 6,855 / 6,732 | 182 each | 8,578 / 8,578 / 8,523 |
| r2-p0 / p25 / p75 | 965,112 | **0 / 0 / 0** | 1,370 / 1,370 / 6,029 | 1,752 / 1,752 / 1,698 | 204 / 204 / 179 | 6,543 / 6,543 / 6,417 |
| r15-p0 / p25 / p75 | 833,016 | **0 / 0 / 0** | 477 / 474 / 448 | 514 / 514 / 508 | 41 / 40 / 39 | 516 / 516 / 510 |

**What the table shows.**
- The covered seeds and the axis tie order are both needed.
- Any extra pass, before or after the schedule, breaks equality.
- Starting at k = N gives the same zero, because that step only reads outside the image.
- Running the flood on a larger canvas breaks equality: tie-512 misses 56 at N+2 and 86 at 2N, and r2-p0 misses 5,090 and 1,566.

**Why the border clusters appeared.** Decision 184's clusters (170 texels on tie-512, 8,212 on r1-p0, 516 on r15-p0, 6,641 on r2-p0) are artefacts of the jump flood, not a separate border stage. Two things decide them:
- **Exact distance ties at intermediate steps.** The tie probe places islands at equal distances, for example d² = 40,960 at step 64 between island 1's and island 3's covered seeds. The tie rule decides which island's seed travels on.
- **The covered seeds** that carry a seed across the gutter in the large steps.

The covered texel (353, 415) that tie-512's right cluster copies is such a carried seed. The bisector between it and island 1's ring (y, 288) reproduces that cluster with 0 texels of difference. Decision 184 recorded that the jump flood "does not err where Painter does"; that holds only for the default tie order.

### 2. The four border probes the brief asked for

Every residual below is a count of gutter texels missed, seeded with Painter's ring.

1. **Clamped or mirrored seed addressing in the search.** These runs use the jump flood with the default order and covered-plus-ring seeds:
   - tie-512: border 52, clamp 52, wrap 52, wrap-x with clamp-y 52, wrap-x with border-y 52, mirror 97, mirror-101 92;
   - r1-p0: 6,855, 6,855, 8,587, 6,855, 6,855, 6,867 and 6,868.

   Addressing alone does not explain the clusters.
2. **Tiled or blocked processing.** No tiled search was run, because finding 1 is exact first.
   - A banded stand-in was run: an exact separable transform whose column pass is capped at |dy| ≤ M. It misses 52 on tie-512 at M = 191 and 194 on r1-p0 at M = 511, but 8,440 on r2-p0 and 1,755 on r15-p0.
   - Painter's own picks rule out a fixed per-axis or per-tile reach. r2-p0 copies a seed 601 rows away, and r15-p0 one 537 rows away.
3. **The nearest covered texel where it beats every ring texel.** In exact Euclidean terms a covered texel is never nearer than a ring texel. Covered-plus-ring 8SSEDT (an exact raster distance transform) gives the same 170 on tie-512 and 8,212 on r1-p0 as the ring alone. Covered texels matter only as carriers inside the jump flood (finding 1).
4. **Distance from texel corners instead of centres.** These runs use the jump flood with the default order and the query point shifted by (±0.5, ±0.5) texels:
   - tie-512: from 595 up to 95,361;
   - r1-p0: from 1,732 up to 509,846;
   - centres: 52 and 6,855.

   Corners are rejected.

Precision variants are also rejected. Run with every one of the 144 separable 3×3 orderings, a jump flood on fp16 distances misses 27,953 to 74,456 on tie-512, and one on fp32 UV distances (v flipped or not, with or without FMA, squared or not) misses 52 at best. A wavefront fill, separable sweeps and in-place Gauss-Seidel jump floods were also rejected:
- the wavefront fill misses 5,632 or more on tie-512 and 12,410 or more on r1-p0;
- the separable sweeps miss 5,962 and 16,178;
- the in-place floods reach 0 on tie-512 in 54 configurations, but the five run on the nine ramps miss 49,235 or more there.

### 3. The ring offset's sign: not identified

These are the edge ring texels with three covered sources: 744 on tie-512 and 3,048 on tie-2048. The magnitude is confirmed: exactly 25·2⁻¹⁵ (512) and 24·2⁻¹⁵ (2048), never zero, and exact perpendicular to the edge.

**Not predictive.** None of these predicts the sign:
- **The side of the island.** Each side carries both signs, and the leaning flips between resolutions:

  | Side | 512 (− / +) | 2048 (− / +) |
  |---|---|---|
  | B | 37 / 149 | 280 / 482 |
  | L | 115 / 71 | 482 / 280 |
  | R | 79 / 107 | 505 / 257 |
  | T | 99 / 87 | 328 / 434 |
- **Texel parity along the edge:** 168/204 against 162/210.
- **Which of the two UV triangles owns the edge:** 69 % + and 58 % − at 512, and even at 2048.
- **The float32 rounding direction of the weighted mean:** 12 summation and normalisation orders, with UV or v-flipped coordinates; no order agrees with more than 317 of the 744 signs.
- **The float32 barycentric reconstruction** of the edge texel's UV from the mesh (`parity/fixtures/tier0-semantics/meshes/tie.obj`): exact, so it carries no sign.
- **Float32 accumulation** of the UV step along the edge: exact, because the steps are dyadic.

**Structure seen.**
- The sign depends mostly on the position along the edge, counted from the island's start.
  - The left edges of islands 2 and 3 (same rows, columns 95 and 351) carry the same 62-sign sequence except one texel.
  - Island 1's left edge (rows 97-158) shares the first 17 signs with them, then diverges.
- Runs of periods 2 and 3 alternate, and at 2048 there are runs of 100 or more equal signs.
- The rule therefore depends on the edge-relative position and on the absolute v range. That points to a non-dyadic float32 quantity computed per edge, which no candidate above reproduces.

## Decision

1. `infinite` padding on islanded sets stays refused before writing (`padding.h`, `NotYetSupported` naming R-090).
   - Item 2.7 stays unchecked.
   - No production code, semantics entry, capability or conformance case changes, and no golden-comparison test is added.
   - **Why.** The gutter copies ring values, so without the offset's sign no ring of a varying field is bit-exact, and no gutter is either. The brief gated the seam check and the implementation on both A and B being exact, so the seam rules of decision 176 were not re-run.
2. **Identified, recorded for the implementation.** The gutter propagation of finding 1 is bit-exact on every P-ramp and P-tie probe, seeded with Painter's ring: 0 of 12,384,416 texels. Decision 184's open item 3(a) is closed.
3. **Rejected, with the residuals above:**
   - clamped, wrapped and mirrored search addressing;
   - a fixed vertical reach;
   - corner-based distances;
   - fp16 and fp32-UV distance comparisons;
   - wavefront, separable-sweep and in-place propagation;
   - any extra jump-flood pass, and a larger canvas;
   - ring-only seeds;
   - the default tie order.
4. **Still open.** Each blocks exactness on its own:
   - **(a)** The ring offset's sign rule, and k = 25 against 24 (decision 184, 3(b)).
   - **(b)** The seam blend at non-unit ratios and phases, and at seam corners (decision 176, 3(b)).
   - **(c)** The sphere poles (decision 129 (c)).
   - **(d)** Confirming finding 1 on `export-padding`, `export-padding-bevelled-cube` and `export-padding-sphere`. Those fields are not position-encoded, so the seed of each gutter texel cannot be read from its value, and the check needs the exact ring first.
5. **No new recording is requested.** The probes hold the data for (a) and (b). Owner: `phase1.25_pilot-wand` item 2.7.

## Consequences

- G1's P1-WAND gate and the wand's five-map export stay blocked on 2.7, as decisions 127, 129, 176 and 184 recorded.
- The next attempt starts from the ring offset's sign (4(a)). Once the ring is exact, finding 1 completes the gutter.
- The propagation hypotheses rejected in decisions 184 and 197 need no retesting.
