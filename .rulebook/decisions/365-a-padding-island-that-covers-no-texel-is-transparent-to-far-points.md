# 365. A padding island that covers no texel is transparent to far points

**Status**: accepted
**Date**: 2026-10-27
**Related Tasks**: phase1.25_pilot-wand

## Context

After decision 364, hinge-vary keeps 202 ring residuals. Tap decoding shows a two-seam pattern on
its gapped-seam copies. The seam strip J, 0.4375 texel deep, lies between the hinged island K and
the island A on J's other side, and covers no texel centre. From K's ring, Painter's far taps are
A's texels: the far point crosses J entirely. The reference folds q into J and opens the window
there, around texels that are not covered.

Variants measured on six probes, in counts of `padding_corpus.py`:

| Variant | Fixed | New |
| --- | ---: | ---: |
| Always walk on to the last stage | 0 | 161 |
| Walk on when J's window is empty | 119 | 39 (corner 22, atlas 14, cube 3) |
| Walk on when J's island covers no texel centre | 119 | 0 |

The broken corner texels share hinge-vary's walk pattern, but their J islands cover 9 or 10
texels.

## Decision

In `tests/export/padding_reference.py` (`Ring.hop`, `Ring.covered_charts`) and
`src/export/padding.cpp` (`RingGeometry::Hop`, `coveredCharts`), identically:

1. **The walk.** After q is folded about the seam edge into J, while the point lies outside its
   triangle it is folded about that triangle's edge into the edge's next triangle:
   - the exiting edge is the one opposite the least 3D barycentric, the first on a tie;
   - the next triangle is the first other one listed for the edge;
   - at most four times, never back across the edge just crossed.
2. **The far point.** When J's island covers no texel centre, the far point is the first stage in
   a covered island. That stage gives f in its triangle's texel space, and its triangle is the
   window's J for decision 364's frame. Otherwise f stays at J.
3. **Everything else unchanged.** The gate, reach, window base, window-side flags and records keep
   the seam's own J.

No tolerance, exception or refusal lift.

## Consequences

On the 29 kernel probes, the ring misses fall from 1,103 to 984: hinge-vary 202 -> 83, with zero
new coordinates. The compiled `uzp-export-tests ring` equals the reference on all 168,275 ring
texels, taps and values. `test_far_point_crosses_an_island_that_covers_no_texel` pins hinge-vary
texel (29, 20), whose taps equal the ones decoded from Painter's recording.

The diagnostic patches `hop`, `hopempty`, `hopzero` and `uvwin` no longer apply to the reference,
and their results are recorded here and in decision 364. Item 2.7 and refusals 245/259 stay open.
