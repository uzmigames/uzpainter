# 127. `infinite` padding on UV islands stays refused: the seam ring blends the far island's last row with that island's own ring, by weights not yet identified

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase1.25_pilot-wand, phase1.18_export-engine, phase1.16_export-processing-encoders

## Context

Item 2.7 of `phase1.25_pilot-wand` (decision 103) asks for an exact fit of `infinite` padding on UV-islanded sets. That means two things:
- the one-texel ring that blends across the UV seam;
- decision 090's 8-neighbour copy dilation, which misses 32 to 44 texels per sphere normal map at the poles.

The time box was about 2 hours; this item had the time left over after item 2.6 (decision 126). The work used the R-090 P9 seam probe `export-padding-seam-256`. It has two quads sharing one 3D edge:
- island A at scale 0.375 on the tile's left border;
- island B at scale 0.25, turned 90 degrees;
- Height 0.25 on A and 0.75 on B, the second value placed by a side mask of columns 128 and up.

Only numbers are given here.

- **B's ring.** B's ring (row 102, below B's bottom edge, the seam) holds A's interior value exactly: 0.25 on columns 142 to 204. The gutter below it is that value copied. This holds even though the side mask gives 0.75 at those UVs. So the ring takes the value from across the seam, not the stack evaluated at its own UV.
- **A's ring.** A's ring (column 96, beside A's right edge, the seam) blends B's last row (0.75) with B's ring (0.25).
  - The weight on 0.75 is periodic along the edge with period 3 A texels, which is 2 B texels (the scale ratio 1.5). In OpenEXR 32f, User0 RGB16 gives about 0.4821, 0.5080, 0.3240 and 0.3109.
  - Height, stored as L16F, gives the same weights rounded to 2^-11.
  - Past A's corners the weights are 0.5762 above and 0.4966 below.
- **Rejected models.** None of these reproduces the varying weights:
  - an affine unfold of the adjacent triangle with bilinear sampling, which gives a constant weight of about 0.43 along the edge;
  - 2x2 supersampling of the ring texel;
  - the side mask sampled at the across-seam UV.

  Decision 090's six rejected models stand as well. The sample position the weights imply moves by about 0.19 B texels with the fractional B column of the A row (offsets 0.07, 0.40, 0.73). That suggests snapped or quantised seam coordinates, but this is not identified.
- **The poles.** The sphere poles were not revisited.

## Decision

1. `infinite` padding on islanded sets stays refused before writing (`padding.h`, `NotYetSupported` naming R-090). Item 2.7 stays unchecked: nothing here is claimed exact.
2. Still unknown, to be measured next:
   - **The seam-coordinate rule.** The across-seam position, and its quantisation, behind A's periodic ring weights.
   - **The order of the passes.** Which island's ring is written first: B's ring is pure A, and A's ring reads B's ring.
   - **The pole wedges.** The sphere's pole-wedge texels under the copy dilation (32 to 44 per normal map).
3. What would settle the seam rule:
   - **Recorded data first.** The seam goldens at 1024 (`export-padding-seam-1024`, `-field-256/-1024`, already recorded) are the first input: the same geometry at four times the density shows whether the weights follow texel or UV positions.
   - **A new probe, if those are not enough.** A probe whose islands have a scale ratio of 1 (no periodicity) and one with a ratio of 2. This is a new recording for the owner's Painter session.
4. Owner: `phase1.25_pilot-wand` item 2.7. Wand v1's five-map export (`painter_export.py`: PNG 16, `infinite`, on a real UV layout) stays refused until then. `tests/adapters/assets3d/test_pipeline_adapter.py` waits on `padding-islands` as well as on `srgb8-material-channels`.

## Consequences

- G1's P1-WAND gate (items 3.1 and 4.1) cannot pass until 2.7 is exact.
- The exact BaseColor encode (decision 126) is ready for the wand once the padding is exact.
