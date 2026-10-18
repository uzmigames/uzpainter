# 263. The virtual normal's island-edge texels read Painter's `infinite`-padded Height in float32, before its half write, so decision 245's refusal waits only on the padding ring

**Status**: accepted
**Date**: 2026-10-18
**Related Tasks**: phase1.25_pilot-wand, phase1.12_compositor-height-normal, phase1.18_export-engine

## Context

Decision 245 refuses a virtual normal on a UV-islanded set. Its island-edge texels differ from Painter's because Painter's height-to-normal stencil reads a Height outside the islands that UzPainter does not reproduce. UzPainter evaluates the Height layers over the whole tile instead. The owner ruled on 2026-10-18 that the Wand must match Painter everywhere, which makes this the second G1 blocker.

This pass looked for the exact Height value Painter's stencil reads outside the islands, with a 2-hour cap. It tested four hypotheses:
- **(a)** Painter pads the Height internally.
- **(b)** The outside Height is a constant.
- **(c)** The stencil clamps or mirrors to the nearest covered texel.
- **(d)** The stencil masks the outside taps.

**Method.**
- Everything ran on the CPU from the private store, without Painter. Only counts are recorded here. The scripts stay in private scratch (`pn/`), because they read oracle pixels.
- The normal model is `tools/parity/fit/normal.py`, decisions 064 and 065: Sharp, v = (h(-1,0) − h, h − h(0,-1), 0.390625), the recording GPU's rsqrt, and the Normal channel's bitmap where the golden has one.
- On the covered texels this model equals `uzp-export-tests files` (same counts below). It needs only the covered Height. That equals Painter's exported Height bit for bit on every golden here: one bitmap fill at opacity 1, so the read-out is the stored half.
- **Interior** means covered texels whose 8 neighbours are all covered. **Edge** means covered texels with an uncovered 8-neighbour (decision 245).

## Findings

### 1. Only the left and upper taps matter, and both are ring texels

- Every differing edge texel has its left or upper neighbour uncovered: 592 of 592 on the sphere and 1,154 of 1,154 on the cube. No edge texel whose two Sharp taps are covered differs.
- Every uncovered tap the stencil reads is a padding-ring texel, one with a covered 8-neighbour: 928 of 928 on the sphere and 1,160 of 1,160 on the cube.
- So the gutter (decision 197's jump flood) never reaches a covered normal. Only the ring does.
- Decision 245 saw edge texels differ even where the evaluated 3 × 3 Height is constant. The stencil is not wider than recorded. Painter's ring value at those taps differs from the whole-tile value, often because it comes from across a seam (decisions 127, 211). On the cube one ring tap holds 0.106 next to covered values near −0.92.

### 2. Rule: the stencil reads Painter's own `infinite` padding of the Height, in float32, before the L16F write

At each uncovered tap, Painter reads a float32 Height. Rounded toward zero to binary16, that value is exactly the Height Painter exports with `infinite` padding.

**Test 1 (PNG 16).** Painter's `Normal_OpenGL` PNG 16 file is reproduced on every edge texel, r1 and r2, by some float32 tap value in the half interval of Painter's exported OpenEXR 32f Height:

| Golden | Edge texels consistent | Control: Painter's value moved one half ulp away from zero |
|---|---|---|
| `export-padding` (Normal channel bitmap) | 1,452 / 1,452 | 859 |
| `export-padding-sphere` | 2,176 / 2,176 | 1,304 |
| `export-padding-bevelled-cube` | 2,296 / 2,296 | 1,305 |
| `height-normal-sphere` | 2,176 / 2,176 | 1,307 |
| `height-normal-bevelled-cube` | 2,296 / 2,296 | 1,318 |

- The control shows the test discriminates. With the value moved one half ulp toward zero, it also fails (1,561 of 2,176 on the sphere). With the whole-tile evaluated Height, it fails too: 1,599 on the sphere, 1,142 on the cube.
- The three `export-padding*` goldens use Painter's infinite step: step 34 or 23 for the PNG 16 Normal, step 86 or 45 for the OpenEXR 32f Height.

**Test 2 (float32).** The three `export-padding*` goldens also export `Normal_OpenGL` as OpenEXR 32f (step 86 or 45). This is a much tighter test:
- Every float32 in each tap's half interval was enumerated (8,192 per tap).
- Every edge texel with one uncovered tap is reproduced bit for bit, in all three float components, by some value: 647 of 647, 704 of 704 and 1,148 of 1,148. The interior is exact: 26,870, 59,264 and 51,040.
- Where two edge texels read the same tap, their value sets always intersect: no tap is left empty.
- The tap's float32 value is pinned to a single value at 439 of 647 taps, 451 of 672 and 110 of 1,148.
- Texels with both taps uncovered (44, 224 and 6) were tested only by Test 1.

This also explains decision 245's padding independence. Every export padding (`passthrough`, `color`, `transparent`, `diffusion`, any dilation) leaves the covered Normal texels unchanged. The normal always reads Painter's internal `infinite` padding of the Height, whatever padding the export applies afterwards.

### 3. The other hypotheses are rejected

The table gives covered edge texels differing from Painter's PNG 16 file (r1); the interior is 0 in every row.

| Hypothesis | export-padding | ep-sphere | ep-cube | hn-sphere | hn-cube |
|---|---|---|---|---|---|
| Edge texels | 1,452 | 2,176 | 2,296 | 2,176 | 2,296 |
| UzPainter today (whole-tile Height) | 445 | refused¹ | refused¹ | 592 | 1,154 |
| (b) constant 0 | 691 | 928 | 1,154 | 928 | 1,142 |
| (b) constant −1 | 583 | 928 | 1,154 | 773 | 1,092 |
| (b) constant +1 | 691 | 928 | 1,154 | 928 | 1,154 |
| (b) mean of the covered Height | 691 | 928 | 1,154 | 928 | 1,154 |
| (c) clamp: tap = the centre texel (difference 0) | 444 | 928 | 1,154 | 581 | 1,154 |
| (c) mirror: forward difference where the backward tap is uncovered | 542 | 928 | 1,154 | 594 | 1,154 |
| (a/c) decision 223's ring and jump flood, of the read-out | 334 | 926 | 1,154 | 652 | 1,154 |
| (a) Painter's exported half Height read as it is | 427 | 879 | 962 | 563 | 877 |
| **(a) float32 Height rounding toward zero to it** | **0 (consistent)** | **0** | **0** | **0** | **0** |

¹ UzPainter refuses `field-a` on Height (`unsupported_source`, decision 218).

Hypothesis (d), dropping the outside taps, is the clamp row: Sharp has one tap per axis, so dropping a tap and setting its difference to 0 are the same.

### 4. What remains open

- **Painter's float32 ring values.** Their formula is item 2.7's open ring rule, with a straight-edge sign (decisions 206, 210, 217) and a seam ring (decisions 127, 211).
  - Decision 223's best ring misses them: 334 to 1,154 edge texels above.
  - On `export-padding`, at straight-edge taps with an along-edge gradient above 10⁻³, the shift implied by the pinned values has a median of +25.07 × 2⁻¹⁵ texel (301 taps). That matches decision 206's E. The spread is wide, 5–95 % from −1,044 to +1,321, so nothing is fitted here.
- **Smooth (Sobel).** Not tested. It reads all 8 ring neighbours, so the same rule predicts its edges. The `height-normal-sobel-*` goldens are the check.
- **The Wand R9 (1,071 texels).** Not tested. Painter's Wand exports Height only as PNG 16, and UzPainter's covered Wand Height needs a Tier 1 (GPU) evaluation. That is a coordinator batch, not this CPU pass.

## Decision

1. **Recorded rule.**
   - Painter's `Normal_OpenGL` and `Normal_DirectX` on a UV-islanded set evaluate the height-to-normal stencil on the Height read-out padded by Painter's own `infinite` padding.
   - Only the ring is read: the ring texels in the stencil's taps, including the seam ring.
   - The ring is read in float32, before the L16F write rule. Painter's exported `infinite` Height is the half toward zero of that ring.
   - This padding does not depend on the export's padding choice.
   - Covered taps read the covered read-out unchanged, as now.
2. **Not implemented yet**, as the brief required. Decision 245's refusal stays: `CheckIslandNormal`, the diagnostics refusal, and `test_virtual_normal_on_islands` unchanged. No production code, semantics entry, capability or test changes. The reason: the float32 ring values are not reproducible until item 2.7 identifies the ring exactly.
3. **One blocker, not two.** Decision 245's edge normal reduces to item 2.7's exact ring. When the ring is exact, apply it in float32 to the Height read-out before the stencil, then the half write to the Height export. That lifts decision 245 and closes the covered padding of every map at once.
   - Item 2.7 owns it, in `phase1.25_pilot-wand`.
   - The test to turn around is `test_island_edge_normals_differ_from_painter`, as decision 245 §6 says.
4. **New evidence for item 2.7.** The float32 normals of `export-padding`, `export-padding-sphere` and `export-padding-bevelled-cube` pin Painter's float32 ring Height on content that is not a UV ramp: 1,000 taps uniquely, and the rest to a few values.
   - This gives an offline target for the ring sign and the seam ring, finer than the half-rounded Height export.
   - The reconstruction (`recover.py`) stays in private scratch, because it is derived from oracle pixels.
5. **No new recording is requested.**

## Alternatives Considered

- **Implement now with decision 223's ring.** Rejected: it misses 334 to 1,154 edge texels per golden (§3), and decision 001 admits only exact results.
- **Read the exported half Height as the ring.** Rejected: it misses 427 to 962 edge texels per golden (§3). The stencil reads the value before the half write.
- **A wider stencil at the edges.** Rejected: §1 shows only the left and upper taps decide, and every differing texel has one of them uncovered.

## Consequences

- G1's Normal blocker and the `infinite` padding blocker are the same open item: item 2.7's exact float32 ring, including the seam ring.
- When item 2.7 is fitted, the island-edge normal needs no rule of its own beyond applying the ring before the stencil.
- The brief's hint that "constant 3 × 3 texels differ, so the stencil is wider" is answered: the ring values come from across seams.
