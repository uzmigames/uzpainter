# 184. `infinite` padding on UV islands stays refused: push-pull, averaging dilation and edge extrusion are rejected, and the gutter residuals all touch the tile border

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase1.25_pilot-wand, phase1.18_export-engine, phase1.16_export-processing-encoders

## Context

Item 2.7 of `phase1.25_pilot-wand` asks for a bit-exact fit of `infinite` padding on UV-islanded sets. Decision 176 identified the border ring (the 8-neighbour mean weighted 1 and 1/√2) up to a ±k·2⁻¹⁵-step offset along the edge. It also identified the ratio-1 seam copy and the ratio-2 phase-0 B ring. It left open the offset, the general seam blend and the propagation into the far gutter.

This pass tested hypotheses that decision 176 did not test:
1. a mip-pyramid push-pull fill;
2. an iterative 1-texel averaging dilation, synchronous or in place;
3. GPU edge extrusion of the UV islands.

It also checked whether the offset is a bilinear sampling-position bias.

The data is the same as decision 176's: the P-ramp probes `export-padding-ramp-{r1,r2,r15}-{p0,p25,p75}-v2` (1024) and the P-tie probes `export-padding-tie-512` and `export-padding-tie-2048-v2`. Each is User0 RGB32F at r1 step 10, where R = (x + 0.5)/N and G = (y + 0.5)/N. Everything ran on the CPU from the private store, without Painter, within a 2-hour time box. Comparison is on float32 bit patterns, with no tolerance. Only counts are recorded here, and the scripts stay in private scratch (`pad184/`).

Every residual below counts the uncovered texels whose RGB bits differ from Painter's export:
- **ring**: uncovered and 8-adjacent to a covered texel;
- **gutter**: every other uncovered texel.

The totals are:

| Probe | Ring | Gutter |
|---|---|---|
| tie-512 | 780 | 249,076 |
| tie-2048 | 3,084 | 3,994,612 |
| r1 | 2,056 | 915,448 |
| r2 | 1,544 | 965,112 |
| r15 | 2,568 | 833,016 |

Every hypothesis was run in two seedings. "From coverage" builds the ring itself. "From Painter's ring" is seeded with Painter's own ring, so it isolates the propagation.

## Findings

### 1. Mip-pyramid push-pull: rejected

**Model.** A masked 2×2 box downsample with a texel known if any child is known. Holes are then filled coarse to fine. Upsampling is box (parent copy) or bilinear (0.75/0.25), accumulated in fp32 or fp64.

**Results.**
- From coverage, every probe misses 99.8–100 % of the ring and 99.6–100 % of the gutter. For example: tie-512 780/249,076, r1-p0 2,056/915,448, tie-2048 3,084/3,994,612.
- From Painter's ring, it still misses most of the gutter:
  - box upsampling: tie-512 236,800; r1-p0 833,920; r1-p75 915,448; r2-p0 883,584; r15-p0 833,004; tie-2048 3,798,016;
  - bilinear upsampling: 100 % of the gutter on every probe.

**Why it fails.** Painter's far gutter is not a blend. 99.93 % of gutter texels (248,906 of 249,076 on tie-512) are bit-exact copies of one ring texel's value, constant along rays.

The values that decision 176 found in no ring texel are not a pyramid average either. On tie-512 every one is the value of the single covered texel at (y 353, x 415). A point-sampled level-1 texel would give that value, because it is the bottom-right of its 2×2 block. Even so, no push-pull variant reproduces the surrounding per-row ring copies.

### 2. Iterative averaging dilation: rejected

**Model.** Each pass gives every unfilled texel that has a filled 8-neighbour the mean of its filled neighbours, weighted 1 and 1/√2. Three schedules were run: synchronous (Jacobi), in place row-major, and in place serpentine. The neighbours wrap in x.

| Seeding | Synchronous | In place, row-major | In place, serpentine |
|---|---|---|---|
| From coverage | ring 763/780, gutter 232,582 | gutter 249,076 | gutter 249,076 |
| From Painter's ring | gutter 232,339 | gutter 249,075 | gutter 249,075 |

These counts are for tie-512. The other probes behave the same, for example:
- r1-p0, synchronous: 904,011 of 915,448 gutter texels missed;
- tie-2048: 3,814,869 missed.

**Why it fails.** The second ring is a straight copy of the first ring in Painter, not a mean of it. Averaging mixes the ±offset ring texels and breaks bit equality from the second ring outward.

### 3. Edge extrusion: rejected

**Model.** Each gutter texel takes the UV of the closest point on the nearest island. Two variants were run:
- **geometric edge:** the island's texel-boundary rectangle;
- **covered centres:** the rectangle of covered texel centres.

The second variant is what a rasterised extrusion with clamped UVs would produce.

**Results.**
- The geometric edge misses 100 % of the ring and the gutter on every probe.
- The covered-centres variant misses:
  - tie-512: 768/780 ring and 93,672 gutter;
  - r1-p0: 738,921 gutter;
  - r2-p0: 651,022 gutter;
  - r15-p0: 683,508 gutter;
  - tie-2048: 1,507,240 gutter.

**Why it fails.**
- Painter's gutter rays copy the ring value with its ±k·2⁻¹⁵ offset. They do not copy the clamped centre.
- The far values sit at texel centres (287, not 287.5). They do not sit on the geometric edge.

### 4. The ring offset is not a sampling-position bias of a bilinear fetch

There are three reasons:
- **Magnitude.** The offset is ±25·2⁻¹⁵ of a texel at 512 and ±24·2⁻¹⁵ at 1024 and 2048. A fetch at (texel ± 2⁻¹⁵·step) would give ±1·2⁻¹⁵.
- **No 8-bit quantisation.** The corner ring value is 352.41422, that is √2 − 1. Hardware bilinear weights are quantised to 1/256 (0.41406), and this value is not.
- **Exactly quantised in texels.**
  - The offset is never zero and always exactly ±25.00·2⁻¹⁵ of a texel, in every value range. Values in [0.125, 0.25) resolve 2⁻¹⁷ of a texel at 512 and still show 25.00. So it is not float rounding of the value.
  - Seen as a UV quantity, it is 25, 12 and 6 ulps of 2⁻²⁴ at 512, 1024 and 2048. That is consistent with an fp32 quantity of about 7.48·10⁻⁴ to 7.63·10⁻⁴ of a texel, computed in UV within [0.5, 1).
  - Its sign has no visible rule. Along each 64-texel edge of tie-512, the signs vary irregularly.

### 5. Propagation: the metric is flat Euclidean, and every residual cluster touches the tile border

Each gutter texel was scored by the gap between two distances: the distance to the nearest known texel holding its value, and the distance to the nearest ring texel.

**The metric.**
- **Flat (no wrap)** leaves only these texels "farther than nearest": tie-512 170, r1-p0 8,212, r15-p0 516, r2-p0 6,641. No golden texel is ever closer than the nearest.
- **Wrapping** in x, or in both x and y, is far worse: tie-512 19,412; r1-p0 170,248–239,454.
- **Value-position seeds** are worse again. This measures the distance to each ring texel's encoded source position instead of its centre. It misses 3,132 on tie-512 and 351,599–421,353 on the ramps.

**Every residual cluster touches the tile border.** The clusters of "farther" texels are:

| Probe | Rows | Columns | Texels | Largest excess (texels) |
|---|---|---|---|---|
| tie-512 | 150–159 | 0–14 | 85 | 8.78 |
| tie-512 | 150–159 | 497–511 | 85 | 2.24 |
| r1-p0 | 76–127 | 0–58 | 1,546 | 47.5 |
| r1-p0 | 896–1003 | 901–1023 | 6,666 | 92.5 |
| r15-p0 | 0–3 | 48–50 | 9 | 2.79 |
| r15-p0 | 922–948 | 987–1023 | 507 | 23.9 |
| r2-p0 | 0–110 | 0–63 | 5,083 | 0.45 |
| r2-p0 | 896–939 | 954–1023 | 1,558 | 35.8 |

Every cluster touches column 0, column N − 1 or row 0. The image interior is exact nearest-ring.

**What tie-512 shows at the two edges.**
- **Left cluster.** In rows 150–159, island 1's side ring always wins. The nearer corner ring of island 2 never does.
- **Right cluster.** In rows 152–159 the winner is the covered texel (353, 415). It does not come from island 3's nearer corner ring.
  - The edge of this cluster fits the exact bisector between island 1's ring (y, 288) and a seed at (353, 415) or (352.5, 414.5). It lands on columns 500 and 511 at rows 159 and 152.
  - From row 160 down, the true corner (value (415, 352)) wins again.

**Jump-flood and coarse-to-fine searches:**

| Search | Variants | tie-512 missed | r1-p0 missed |
|---|---|---|---|
| Jump flood | all 144 neighbour orderings × 4 schedules (standard, 1+, +1, +2), seeded by covered + ring or by covered (tie-512 only) | 52 at best (covered + ring); 93,620 at best (covered) | not run |
| Jump flood | 5 addressing modes (border, clamp, wrap-x, wrap, wrap-x/clamp-y), flat or toroidal, seeded by ring or covered + ring | 52 at best | 6,855 at best |
| Jump flood | starting step N to N/16, with or without +1 / +2 passes, seeded by ring | 52 at best | 7,046 at best |
| Exact coarse-to-fine Voronoi | base level 3, 5 or 7, parent 3×3 neighbourhood | 171 | 8,426 |

None reproduces Painter's border clusters. On tie-512 the jump flood does not err where Painter does (the left cluster), and it errs where Painter is right.

## Decision

1. `infinite` padding on islanded sets stays refused before writing (`padding.h`, `NotYetSupported` naming R-090). Item 2.7 stays unchecked.
   - No production code, semantics entry, capability or conformance case changes.
   - No golden-comparison test is added, because no rule is bit-exact on any probe.
2. **Rejected, with the residual counts above:**
   - mip-pyramid push-pull (box or bilinear, fp32 or fp64, seeded either way);
   - synchronous and in-place averaging dilation (row-major and serpentine);
   - rasterised edge extrusion (geometric or texel-centre clamp);
   - a bilinear sampling-position bias for the ring offset;
   - wrapped and value-position metrics for the propagation;
   - JFA schedule and addressing variants, and exact coarse-to-fine Voronoi.
3. **Narrowed for the next fit:**
   - **(a) The propagation.** It is flat-Euclidean nearest-ring everywhere except clusters that touch the tile border. Next to test: a border-dependent stage, such as a tiled or blocked candidate search, or an image-border clamp in the seed search.
   - **(b) The ring offset.** It is an exact ±(about 7.5·10⁻⁴ texel) term, consistent with an fp32 UV-space quantity of 25, 12 and 6 ulps at 512, 1024 and 2048. Its sign rule is still open.
   - **(c)** The seam blend at non-unit ratios and phases, and the sphere poles, as decision 176 left them.
4. **No new recording is requested.** The probes already hold the data. What is missing is the mechanism. Owner: `phase1.25_pilot-wand` item 2.7.

## Consequences

- G1's P1-WAND gate and the wand's five-map export stay blocked on 2.7, as decisions 127, 129 and 176 recorded.
- The next attempt starts from 3(a) and 3(b). Hypotheses 1 to 3 of this decision need no retesting.
