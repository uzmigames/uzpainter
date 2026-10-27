# 364. Far padding taps turn from the seam triangle's plane, and far windows take every island

**Status**: accepted
**Date**: 2026-10-27
**Related Tasks**: phase1.25_pilot-wand

## Context

Wand item 2.7 stays open under production refusals 245 and 259. Decision 358 measured a generic
J/tau rotation as a diagnostic: the far chart turned rigidly from the plane of J, the far-side
triangle of the crossed seam, into the plane of tau, the ring texel's triangle. On 27 probes it
left 1,438 residuals with one new coordinate, against the per-hinge baseline's 2,941. It found J
through a unique shortest face path with one chart crossing, so most far taps never qualified.

`tools/parity/fit/padding_corpus.py` now scores policies on all 29 kernel probes (the 27, plus
`plane-control` and `tau-prism`) and decodes Painter's actual taps from the kernel maps. On
hinge-vary's gapped-seam copies, Painter takes far taps from the island hinged behind J, a thin
strip that covers no texel of the window. Decision 356's window filter, which keeps only J's and
tau's islands, drops those taps.

## Decision

In `tests/export/padding_reference.py` and `src/export/padding.cpp`, identically:

1. **Window.** A far window takes every covered texel of its 3 x 3 block, of any island.
2. **Far frame.** A far tap, in another island than tau, is turned rigidly from the plane of a far
   triangle J into tau's plane:
   - J is the far triangle of the seam edge of tau's island, into the tap's island, whose 3D
     segment is nearest the ring point q. On a tie, the first in mesh order.
   - With no such seam, J is the far triangle of the window that first puts the tap.
   - The rotation (`plane_rotation`, `PlaneRotation`) uses Rodrigues' formula about the planes'
     intersection line. The line's point comes from Cramer's rule, in double precision, in one
     operation order on both sides.
   - Parallel planes keep the point. So do unit normals meeting at a dot product above decision
     282's gate.
3. **Everything else unchanged.** Own taps, a far tap with no J, candidate ordering, quantization
   (decision 268) and every flag stay as they were.

No tolerance, exception, per-coordinate table or refusal lift.

## Consequences

| Measure | Previous reference (`7c4d804f`) | This reference |
| --- | ---: | ---: |
| Differing ring coordinates, 29 kernel probes | 3,248 | 1,103 |
| Fixed | — | 2,145 |
| New | — | 1 |

The new coordinate is decision 358's hinge-far slender-triangle texel. It already differs under
every J/tau-family policy, and its support and order are Painter's; the remaining difference is one
quantization bin.

Per probe (previous -> now):

| Probe | Previous | Now |
| --- | ---: | ---: |
| hinge-vary | 961 | 202 |
| hinge-single | 677 | 6 |
| hinge-far | 395 | 7 |
| kernel-bevelled-cube-256 | 336 | 309 |
| tau-prism | 227 | 39 |
| corner-reach | 137 | 105 |
| plane-control | 80 | 0 |

The other probes are unchanged: window-side 132, sphere 103, the four atlases 30/32/31/65, the
tie-sweep seams 35/2/1, concave-fine 4, and zero on the remaining 13.

Rejected, with counts in `parity/reports/phase1/padding-window-frame-diagnostic.md`:

| Variant | Result |
| --- | --- |
| J from the nearest seam of any island | 404 new |
| The window's J for every far tap | 49 new on the cube |
| Window-boundary snapping | 22 new |
| A UV-similarity far point | 541 new on five probes |

The window-boundary side needs Painter's GPU float32 strip interpolation, which is not modelled.

The compiled `uzp-export-tests ring` equals the reference on every ring texel of every kernel
probe: taps, then values bit for bit. `test_far_window_takes_every_island_and_turns_j_into_taus_plane`
pins hinge-vary texel (20, 17), whose four taps equal the ones decoded from Painter's recording.

The frozen CPU diagnostics that pin the previous reference by hash, `padding_plane_control.py` and
`plane_transform_diagnostic.py`, refuse this reference by design. Their recorded results stand.

The Wand is not re-scored here. Item 2.7 and refusals 245/259 stay open, with 1,103 kernel
residuals.
