# 129. `infinite` padding propagates the island ring by a jump flood without wrap; the ring itself is still not identified, so it stays refused

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase1.25_pilot-wand, phase1.18_export-engine, phase1.16_export-processing-encoders

## Context

Item 2.7 of `phase1.25_pilot-wand` asks for an exact fit of `infinite` padding on UV-islanded sets. Decision 127 left three unknowns:
- the rule for the across-seam position, and its quantisation;
- the order of the passes;
- the sphere's pole wedges.

It named the seam goldens at 1024 as the next input. This work was time-boxed to about 2 hours, under the speed rules of 2026-10-12. It used only admitted goldens, compared the recorded blobs per channel with exact float equality, and did not use Painter.

**Artifacts.** All are under `tier0/semantics/`.

- **Seam goldens.** `export-padding-seam-256` and `-1024`: User0 and User1 (RGB16) and Height (L16F), steps 29-32. `export-padding-seam-field-256` and `-1024`: User0 and Height, steps 15-18.
  - For each map: r1 equals r2, and both PNG 16 steps are identical, as are both OpenEXR 32f steps.
  - Control: the seam goldens' User1 (field A) steps 29-32 equal the field goldens' User0 steps 15-18 bit for bit, at both resolutions and in both recordings.
- **Other meshes.** The `infinite` maps at 256 of `export-padding-bevelled-cube`, `-sphere` and `export-padding` (islands), on r1 OpenEXR 32f, every channel.
- **Seed set.** The covered texels (a texel whose centre is inside or on a UV triangle), plus the 8-neighbour ring around them. The ring is taken with x wrap: an island on the tile's left border gets ring texels in column N-1, and that is the only wrap.

**Two scopes, reported apart.**

1. **Ring construction: not identified.**
   - Seam field: A's ring texel equals a lerp between B's ring row and B's last row. The weight is the same as in the constant fixture (row 135: 0.50798 per channel), so the weights depend on geometry, not on data.
   - B's ring holds A's field resampled (alternating 0.3714/0.3720), not A's last-column value (0.37255).
   - The affine unfold with bilinear sampling at mip 0 is rejected at both resolutions, using the observed endpoints A = (0.2000000030, 0.4000000060, 0.6000000238) and B = (0.8999923468, 0.4999923706, 0.0999923721):
     - At 256, A's ring (0.5 A texels beyond the edge) maps to B row 102.067, which predicts a weight of 0.4333 on B's last row. Observed: 0.50798, 0.32404 and 0.31085, period 3.
     - At 1024 it maps to B row 409.267, between rows 408.5 and 409.5, which are both covered B texels, so it predicts B exactly (weight 1). Observed: 0.67092 at the end, then 0.76117, 0.78657 and 0.80756, period 3.
   - Mip 1 predicts a constant 0.867 at 1024 and is also rejected.
   - A two-parameter bilinear solve on the field puts the sample rows at 101.99/102.17/102.19 (256) and 409.69-409.74 (1024). Its x is ill-conditioned because the field varies slowly along the edge.
   - The 1024 "eighths" (0.375 and 0.125) are not padding. They are the 256 side mask magnified bilinearly across the wrap onto covered columns 0-1 of island A.

2. **Seed propagation from the recorded ring: almost fitted.** This proves propagation only, because the ring values come from the golden.

   | Model, seeded from the recorded ring | Texels missed (seam-256 User0 step31 r1) |
   |---|---|
   | Decision 090's 8-neighbour copy BFS with x wrap | 2346 |
   | Exact Euclidean nearest seed, ring without wrap, no wrap | 8833 |
   | Same, the seed copied at x+N ("right wrap") | 165 |
   | Same, with the wrapped ring | 57 (all exact ties) |
   | Separable EDT, both pass orders and tie rules | 37 to 57 |
   | Jump flood (steps N/2..1, 9 neighbours), row-major neighbour order | 86 to 93 |
   | Jump flood, column-major orders, wrapped ring, no wrap in propagation | **0** (10 orderings) |

   The 10 zero-residual orderings were then validated on maps they were not fitted on:
   - bevelled cube: 0 on every channel;
   - sphere: 3 per map, at (4,2), (8,1) and (9,1). These are the pole wedge, down from decision 090's 32-44. Painter's values there exist among the seeds, so the gap is the choice of seed.
   - islands: 6 per map, every one an exact distance tie;
   - seam-1024 and seam-field-1024, r1 and r2: 7 each. At (0..3, 48..50) Painter picks a seed that is slightly farther away (squared distance 288369 against 287912). That is the signature of Painter's own jump-flood path, not of an exact transform. Other step sequences (an extra 1024 pass at the front) leave the same 7 texels.

## Decision

1. `infinite` padding on islanded sets stays refused before writing (`padding.h`, `NotYetSupported` naming R-090). Item 2.7 stays unchecked. Nothing here is claimed exact, and no code is changed.
2. **Recorded as measured.**
   - Propagation of the seeds is a jump flood:
     - no wrap in propagation;
     - seeded by the covered texels and an 8-neighbour ring taken with x wrap;
     - texel-centre Euclidean distance;
     - a column-major neighbour order.
   - It is exact on the bevelled cube and on the seam at 256, and leaves 3, 6 and 7 texels on the sphere, the islands and the seam at 1024.
   - This replaces decision 090's copy-dilation model.
3. **Still unknown.**
   - **(a) The ring.** The across-seam sample position and its quantisation. This is the main blocker: without it no islanded map can be written.
   - **(b) Painter's jump-flood path:** its neighbour order, tie rule and step sequence, which decide the 16 remaining texels.
   - **(c) Pass order:** whether B's ring is written before A's ring reads it. The field result, where A's ring reads B's ring holding A's resampled values, says B's ring exists when A's ring samples.
4. **What settles it.** This is a recording for the owner's Painter session; owner: `phase1.25_pilot-wand` item 2.7.
   - **(a) A ramp probe on the seam mesh.** At 1024 and 2048, with a document-resolution bitmap on each island:
     - R is a linear ramp in u and G a linear ramp in v (RGB32F, so there is no magnification and no UNORM step).
     - The bilinear sample of a linear ramp is linear, so each ring texel's R and G give its sample coordinate directly, with quantisation visible to float precision.
     - Add decision 127's scale-ratio-1 and scale-ratio-2 seam meshes with the same ramps.
   - **(b) A tie probe.** Two or three single-quad islands with distinct constants, placed so that many gutter texels are exactly equidistant, plus one far corner at 2048. These decide the tie rule and the jump-flood step sequence.

## Consequences

- The wand's five-map export and G1's P1-WAND gate (items 3.1 and 4.1) stay blocked on 2.7 until recording (a) is made and fitted.
- When the ring is fitted, propagation needs only the remaining tie and step rule.
- The analysis scripts and logs stay in private scratch. Only numbers are recorded here.
