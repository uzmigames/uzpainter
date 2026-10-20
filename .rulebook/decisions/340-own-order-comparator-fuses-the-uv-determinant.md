# 340. The own-order comparator fuses the UV determinant; tau keeps it split

**Status**: accepted
**Date**: 2026-10-20
**Related Tasks**: phase1.25_pilot-wand

## Context

phase1.25 item 2.7 remains open. Decision 294 orders adjacent own taps whose distances lie within OWN_BAND by decision 273's comparator. The same comparator picks tau, the ring point's triangle (decision 279). On the corner and window recordings, part of the remaining own-order misses come from that comparator's float32 arithmetic.

## Decision

Two changes, both scoped to the comparator.
- **The own-order comparator.** `compare_distance` and `CompareDistance` compute each position's UV determinant fused, as fma(e0u, e1v, -f32(e0v e1u)), for the ring texel and the tap. The squared length is fma(dz, dz, fma(dx, dx, f32(dy dy))), y first, then the existing hardware square root.
- **Tau.** Tau selection keeps the split determinant, f32(e0u e1v) - f32(e0v e1u), for both positions. It uses the same y-first squared length.

`Position32` defaults to the split determinant. Everything else is unchanged: the far comparator, weight distances, chain fractions, windows, gates, tie bands and the production refusals.

## Alternatives Considered

- **The consolidated far comparator** (physical far distance, plane-projection weights, reciprocal fractions). Applied over the native weights, it changes corner-reach from 217 to 155 misses but adds (266, 104). It was validated with other weight groups, not with the native ones.
- **Fusing the determinant for tau as well.** Not adopted: the review validated only the own-order correction, so tau keeps decision 279's arithmetic. `test_own_comparator_keeps_tau_and_far_roles_separate` pins the three roles on corner-reach: the corrected own order at (34, 38), tau 148 at (185, 37), and the far order at (266, 104).

## Consequences

The compiled build has this decision and decision 339 as amended. `uzp-export-tests.exe` SHA-256 is 1000e6a6f1504ffe3dbd6da91ba9e04395d53eff265961c5c51d050d301a2810 (`tmp/scratch/padding-port/prefix`).

All 27 kernel probes were run (`tmp/scratch/padding-port/native_all.py` and `compare.py`). On each probe, the union over its four infinite exports and 24 components equals the CPU reference coordinate for coordinate.
- The total falls from 4,691 to 4,615 differing ring coordinates, with zero new coordinates against decision 339's rule alone and against pre-strip.
- Probes that change: corner-reach 217 -> 174, window-side 152 -> 132, hinge-single 1105 -> 1104, hinge-vary 1153 -> 1151, concave-fold 1 -> 0, concave-shape 7 -> 0, kernel-atlas-1024-moved 79 -> 77.
- Every other probe is unchanged. The full table is in decision 339's amendment.

An earlier compiled run of this patch over the strip as first written agrees: 8 probes, zero new coordinates (`tmp/scratch/padding-own/compare-validation.json`, runner 49cfcee6...).

**The Wand.** This is the CPU reference and not a compiled check (`tmp/scratch/padding-port/wand_reference.py`).
- EXR goes from 88 to 86 misses: (433, 54) and (434, 53) are fixed.
- PNG stays at 49, with an identical coordinate set.
- No coordinate is new.

The refusals of decisions 245 and 259 remain, and item 2.7 stays open.
