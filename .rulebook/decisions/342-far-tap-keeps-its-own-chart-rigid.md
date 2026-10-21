# 342. A far tap keeps its own chart rigid

**Status**: accepted
**Date**: 2026-10-21
**Related Tasks**: phase1.25_pilot-wand

## Context

phase1.25 item 2.7 remains open. A far tap is a tap in another chart (UV island) than tau, the ring point's triangle. When the tap's planar face shares no 3D edge with tau's face, decision 281 brings it into tau's frame along the fewest-hinge face paths, and decision 282 rotates about each hinge of the path that is folded past the gate. On the hinge probes of decision 289, most of the remaining misses are such multi-facet far taps, which reach across a seam into a far chart that is itself folded past the gate.

The CPU research of the wand-png task (`tmp/scratch/wand-png/variants.py`, `cmp.py`, miss sets in `variants/<variant>/`) scored thirteen variants of that path development on the five probes with multi-facet misses (hinge-far, hinge-single, hinge-vary, corner-reach, kernel-bevelled-cube-256), and `farchart` on all 27.

## Decision

In the path branch of `Ring.frame` (`tests/export/padding_reference.py`) and of `RingGeometry::Frame` (`src/export/padding.cpp`), a far tap skips every hinge whose two triangles are both in the tap's chart. The far island stays rigid.
- The hinges in tau's chart and the seam hinge (whose triangles lie in two charts) keep decision 282's per-hinge gate.
- Own taps (in tau's chart) are unchanged.
- A tap whose face shares an edge with tau's face is unchanged (decision 282's single hinge).

`test_far_tap_keeps_its_own_chart_rigid` pins the rule on the hinge-far fixture. At ring texels (20, 27) and (20, 60), each of the two far taps lies one and two folded in-chart hinges beyond a flat seam hinge. Its distance is |q - P| with P as it is, which differs from the development that unfolds every gated hinge. The case fails on the build before this decision (exe 1000e6a6...; `tmp/scratch/padding-farchart/prechange.log`).

## Alternatives Considered

Scored on the five probes against the decision 339/340 state, as fixed / new coordinates (`cmp.py`):
- **chord** (P as it is on every path) 1,363 / 839, **devall** (every hinge unfolded, no gate) 190 / 1,156, **firstonly** 265 / 839, **mindev** (the nearest of P and the gated development) 885 / 363, **nogate_last** (the hinge next to tau always unfolded) 182 / 651.
- **rigid** (only the hinge next to tau's face, gated) 1,255 / 107; **rigid_far** (that for far taps only) 1,255 / 31; **rigid_own** (that for own taps only) 0 / 76.
- **Tau-side variants on top of this rule**: `tau_nogate` (tau-chart hinges always unfolded) 1,311 / 284, `tau_rigid` (never) 1,429 / 314, `tau_cum` (gated against tau's normal) 1,171 / 18. `tau_anyall` (all tau-chart hinges unfolded when any is folded) gives this rule's 1,171 / 0 on these probes and its Wand reference (EXR 85, PNG 49), so they cannot tell the two apart; it is not adopted without a probe that does (open items).

## Consequences

The compiled build (`zig build export-tests`, `tmp/scratch/padding-farchart/prefix`) has decisions 339, 340 and this one. `uzp-export-tests.exe` SHA-256 is cd1c85eb9b07a4eb30cbb5dfd41777f35a010b5a6a5e9ec74e0ce1d755873602.

All 27 kernel probes were run (`tmp/scratch/padding-farchart/native_all.py` and `compare.py`). On each probe, the union over its infinite exports and 24 components equals the CPU reference farchart set coordinate for coordinate, with zero new coordinates against main's compiled state (exe 1000e6a6...).

| probe | before (decision 340) | after |
|---|---:|---:|
| 27 probes, total | 4,615 | 3,444 (1,171 fixed, 0 new) |
| hinge-far | 898 | 395 |
| hinge-single | 1,104 | 677 |
| hinge-vary | 1,151 | 953 |
| corner-reach | 174 | 137 |
| kernel-bevelled-cube-256 | 342 | 336 |
| the other 22 probes | unchanged | unchanged |

**The Wand.** This is the CPU reference and not a compiled check (`tmp/scratch/padding-farchart/wand_reference.py`).
- EXR goes from 86 to 85 misses: (567, 1421) is fixed.
- PNG stays at 49, with an identical coordinate set.
- No coordinate is new.

**Limits.**
- Most remaining multi-facet misses are weight-type: Painter's value lies in the convex span of the chosen taps, and the implied distance of the multi-facet tap is about 0.3 to 0.6 % off (hinge-far's far tap 0.9967 of ours, own taps 1.000). Of the 1,655 multi-facet misses left, 1,574 are of this kind.
- The rule does not explain the Wand PNG 49. Those taps run through tau-side hinges with differing gates (40 of 97 paths; 52 of 97 cross two or more tau-side hinges), which the corpus shows almost only in hinge-single (54 taps) and the cube (4). They need the tau-side rule, which no admitted probe settles.

The refusals of decisions 245 and 259 remain, and item 2.7 stays open.

## Open items

- **Probe request (pending, needs Painter on the owner's machine in an owner-free window).** One 512 px, 8 User channels (24 components) kernel probe: a faceted prism or cylinder like the Wand shaft, with facet hinges alternating both sides of the 0.985 gate (for example 8, 12, 9.9 and 10.25 degrees), and a lengthwise UV seam so that ring texels reach own and far taps 2 or 3 facets away through tau-side hinges with differing gates; infinite padding r1/r2. It settles whether the tau-side development is a matter of the tap set or of the weights, which no admitted probe can.
