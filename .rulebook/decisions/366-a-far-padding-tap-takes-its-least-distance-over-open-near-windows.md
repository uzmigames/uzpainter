# 366. A far padding tap takes its least distance over open near windows

**Status**: accepted
**Date**: 2026-10-27
**Related Tasks**: phase1.25_pilot-wand

## Context

After decision 365, the Wand's first diagnostic measure (`test_wand_measure.py`, decision 286) differs from Painter only around the islands. Counts per map, on the ring:

| Map | Ring texels differing (of 6,334) |
| --- | ---: |
| BaseColor | 99 |
| Roughness | 22 |
| Height | 21 |
| Metallic | 17 |
| Normal | 60 |

The Normal also differs on 45 covered edge texels. The interior of the other four maps is exact, and their gutter differences are copies of the ring.

Almost all of those ring texels are 4-tap far chains flagged multi-facet, the bevelled-cube family; only one is a window-side case. On kernel-bevelled-cube-256, ring texels whose far taps are held by two open windows show Painter's implied distances taking, tap by tap, the least over the windows' far triangles J. A window whose edge lies 1.182 texels away does not count.

The variants measured on all 29 kernel probes:

| Variant | Fixed | New |
| --- | ---: | ---: |
| Each tap's own triangle as J | — | thousands |
| The window's J for every windowed tap | 1 | 49 |
| The least distance over every seam into the tap's island | 68 | 87 |
| The least over holding windows, without the frame distance | 70 | 25 |
| The least of the frame distance and the open windows within the cap | 69 | 0 |

For the last variant, the cap lies in [1.15943297, 1.18234014) texels; window reaches of 1.15943 must count, and 1.18234 must not.

## Decision

In `tests/export/padding_reference.py` and `src/export/padding.cpp`, identically:

1. **Least distance.** A far tap (in another island than tau, not an own neighbour) takes the least of:
   - its decision 364 frame distance;
   - the distances through the J of each window that holds it (decision 365's effective J), turned by `plane_rotation`.
2. **Which windows count.** Only windows whose edge is open (not gated) and lies within `WINDOW_REACH` = 1.17 texels.
3. **Everything else unchanged.** Ordering, quantization and flags stay as they were.

No tolerance, exception or refusal lift.

## Consequences

On the 29 kernel probes, the ring misses fall from 984 to 915 (cube 309 -> 240) with zero new coordinates. The compiled ring equals the reference on all 168,275 ring texels, taps and values. `test_far_tap_takes_the_least_distance_over_its_open_windows` pins cube texel (71, 4), whose taps equal the ones decoded from Painter's recording.

`tests/parity/tier1/wand_v1/test_wand_measure.py` runs the Wand diagnostic measure on demand (`UZP_WAND_MEASURE=1`); the Wand is re-measured after this decision. Item 2.7 and refusals 245/259 stay open.
