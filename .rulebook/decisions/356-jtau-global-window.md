# 356. One strip map for every island, and the far window takes tau's island

**Status**: accepted
**Date**: 2026-10-22
**Related Tasks**: phase1.25_pilot-wand

## Context

phase1.25 item 2.7 remains open. After decision 342, 3,444 ring coordinates differ on the 27 kernel probes, 494 of them on the three tie-sweep-seams probes. The CPU research of the pad-selection task (`tmp/scratch/pad-selection/`: `variants.py`, `run.py`, `flags.py`, `wand.py`, `reference.diff`, `padding_cpp_sketch.md`) scored seam-selection variants on all 27 probes against main's farchart state. One variant, `jtau_global`, is adopted here.

## Decision

Two changes, in `tests/export/padding_reference.py` (`Ring.global_winners`, `Ring.candidates`) and in `src/export/padding.cpp` (`RingGeometry::drawOrder` and `strips`, `Candidates`):
- **One strip map for every island.** Every seam edge's one-texel strip (decision 339's top-left fill) is drawn into one map, in mesh order (own triangle, edge, far triangle). The last seam drawn owns each sample. An island's query discovers a seam of its own only when that seam's run owns a sample of the 3x3 neighbourhood. This replaces decision 339's separate map per island; seam runs, the reach cap and the exclusions are unchanged.
- **The far window also takes tau's island.** Decision 275's 3 x 3 far window takes the covered texels of J's island or of tau's. An own neighbour of tau's island in the window stays an own tap. Any other texel of tau's island in the window becomes a far tap at its frame distance.

`test_far_window_takes_taus_own_island` pins the rule on the tie-sweep-seams-centred fixture: ring texel (22, 50) takes its three own neighbours of row 49 and, as a far tap, (22, 48) of its own island. On a build at main's `padding.cpp` (exe 59c02de6..., `tmp/scratch/pad-port2/main-exe.log`) it fails with 3 taps.

## Consequences

The compiled build (`zig build export-tests`, `tmp/scratch/pad-port2/prefix`) has decisions 339, 340, 342 and this one. `uzp-export-tests.exe` SHA-256 is 8d76d068ecfdb2bbc0d178da5fc6789b8117d48af15039ef9144d4860f79f9f1.

All 27 kernel probes were run (`tmp/scratch/pad-port2/native_all.py` and `compare.py`, `compare.md`). On each probe, the union over its infinite exports and 24 components equals the CPU reference `jtau_global` set coordinate for coordinate.

| probe | ring | main compiled (decision 342) | reference | compiled | fixed | new |
|---|---:|---:|---:|---:|---:|---:|
| kernel-atlas-512 | 3140 | 41 | 30 | 30 | 11 | 0 |
| kernel-atlas-1024 | 3140 | 43 | 32 | 32 | 11 | 0 |
| kernel-atlas-2048 | 3140 | 42 | 31 | 31 | 11 | 0 |
| kernel-atlas-1024-moved | 3140 | 77 | 65 | 65 | 12 | 0 |
| hinge-vary | 7440 | 953 | 961 | 961 | 1 | 9 |
| tie-sweep-seams-box320 | 7805 | 214 | 36 | 36 | 178 | 0 |
| tie-sweep-seams-centred | 7805 | 142 | 2 | 2 | 140 | 0 |
| tie-sweep-seams-offcentre | 7805 | 139 | 1 | 1 | 138 | 0 |
| the other 19 probes | | unchanged | | | 0 | 0 |
| **total** | | **3,444** | **2,951** | **2,951** | **502** | **9** |

**The 9 new coordinates are undecided.** All are on hinge-vary, and the compiled ring flags each `window-side` (decision 291 (b)): (55, 30), (101, 19), (101, 30), (147, 19), (193, 19), (354, 18), (354, 19), (446, 19), (492, 19). Their far point has f_u - 1/2 within 1e-13 of an integer, so the side of the window decides them, and production treats them as undecided rather than claiming them. The CPU reference flags the same 9 the same way (`tmp/scratch/pad-selection/logs_flags.txt`). Every other probe has zero new coordinates.

**The Wand.** This is the CPU reference and not a compiled check (`tmp/scratch/pad-port2/wand_reference.py`, `wand-reference.log`): EXR 85 and PNG 49, with coordinate sets identical to decision 342's.

**Limits.**
- tie-sweep-seams-box320 keeps 36 misses, left to decision 288's exclusion.
- kernel-sphere-256 keeps its 103 (decision 288's tile-border rows and self-fold boundary).
- The rest are as in decision 342: the multi-facet weight-type misses and the tau-side rule for the Wand PNG 49.

The refusals of decisions 245 and 259 remain, and item 2.7 stays open.
