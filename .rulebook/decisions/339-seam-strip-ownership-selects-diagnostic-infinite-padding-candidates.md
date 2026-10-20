# 339. Seam strip ownership selects diagnostic infinite-padding candidates

**Status**: accepted
**Date**: 2026-10-20
**Related Tasks**: phase1.25_pilot-wand

## Context

phase1.25 item 2.7 remains open. Corner endpoint caps did not explain independent authored corner, window and atlas recordings. A union of seam strips also introduced a Wand regression at (578,1618). Native before/after exports now verify the ownership rule against every one of 24 components in all four infinite exports (r1/r2) of each control, with coverage and ring coordinates checked independently.

## Decision

For each source chart, rasterize each seam as a one-texel-wide strip with straight endpoints. The last seam in existing draw order owns each sample, including uncovered samples. A ring query discovers a seam only when it owns a sample in the 3x3 neighborhood. Resolve ownership before visibility, tau and border gates; retain the common reach cap 1.78. Nominal corner reaches use that cap; previous empirical brackets remain diagnostic. This is a measured improvement behind existing production refusals, not a claim of exact infinite padding.

## Alternatives Considered

- A union of strip hits fails the Wand overlap control because a later seam must occlude an earlier seam ID.
- Do not automatically compose scratch FMA, plane weights or 3D-window models: their scratch baselines differ from the current native exporter, and composition can introduce new errors.

## Consequences

Native export runner SHA256 482a81eab6618efbe4d73850ba6c43d05bc7c4ebbe35065269412fa9c936274a -> d68c7e0999d324d22a47d2d562d85623575b95d9494dbeb7c2e4ccb96854e5c4. Differing ring coordinates: corner-reach 426 -> 217, window-side 230 -> 152, atlas-512 102 -> 41; zero new coordinates in each of all four compared exports. Evidence: tmp/scratch/padding-new-recordings/native-strip-comparison.json and native-strip-{before,after}-{probe}.json. Earlier scratch counts 61/118/41 must not be attributed to this native build. Refusals 245/259 remain; Wand/G1 acceptance requires exact maps. Native padding/island/encoder suite is still running, so no task or gate closes from these measurements alone.

## Amendment (2026-10-20): the top-left fill rule and seam runs

**Correction.** The Consequences above claim zero new coordinates. That held only for the three compared controls: corner-reach, window-side and atlas-512. Scored on the cube and the sphere, the strip as first written adds new misses against the pre-strip rule: four on `kernel-bevelled-cube-256`, including decision 285's (4, 234), and one on `kernel-sphere-256`, (0, 255). The two changes below supersede it.

**(a) Top-left fill rule.** A sample exactly on a strip border counts only when that border's outward normal points to -u, or to -v (up the tile) for a border with no u component. The test is `padding_reference.strip_covers` and `StripCovers` in `src/export/padding.cpp`.

**(b) Seam runs.** Seams of one island join a run when they share a UV end, are collinear (UV |sin| at most decision 294's COLLINEAR, 1e-3) and have far triangles of one island. The join is transitive. A strip writes its run's ID. A ring texel discovers every seam of a run that owns a sample of its 3x3 neighbourhood, within the 1.78 reach cap.

A lone endpoint edge, one whose run owns no sample, is no longer discovered. Painter drops that edge class on the recorded window-side texel (28, 82) and 77 more window texels. Decision 285's cube basis (4, 234) is kept: its 1.772004 endpoint edge is found through a collinear seam neighbour to the same far island. `test_ring_point_neighbours_and_reach_follow_decision_279` now builds that case.

**Evidence.** The table below counts differing ring coordinates per probe: the union over the probe's four infinite exports and all 24 components.
- The pre-strip, strip and CPU-reference columns come from `tmp/scratch/strip-rule` (`score.py` and `table.py`).
- The compiled column is decision 340's build, `uzp-export-tests.exe` SHA-256 1000e6a6f1504ffe3dbd6da91ba9e04395d53eff265961c5c51d050d301a2810 (`tmp/scratch/padding-port`, `native_all.py` and `compare.py`). On every probe its miss set equals the CPU reference of this rule plus decision 340, coordinate for coordinate.

| probe | ring | pre-strip | strip (as first written) | strip + fill + runs (CPU reference) | + decision 340, compiled | new vs pre-strip (reference / compiled) |
|---|---:|---:|---:|---:|---:|---:|
| kernel-bevelled-cube-256 | 2344 | 346 | 340 | 342 | 342 | 0 / 0 |
| kernel-sphere-256 | 2176 | 196 | 197 | 103 | 103 | 0 / 0 |
| corner-reach | 19354 | 426 | 217 | 217 | 174 | 0 / 0 |
| window-side | 6276 | 230 | 152 | 152 | 132 | 0 / 0 |
| kernel-atlas-512 | 3140 | 102 | 41 | 41 | 41 | 0 / 0 |
| hinge-far | 5920 | 898 | 898 | 898 | 898 | 0 / 0 |
| hinge-single | 8640 | 1105 | 1105 | 1105 | 1104 | 0 / 0 |
| hinge-vary | 7440 | 1153 | 1153 | 1153 | 1151 | 0 / 0 |
| kernel-tie-512 | 780 | 0 | 0 | 0 | 0 | 0 / 0 |
| kernel-tie-2048 | 3084 | 0 | 0 | 0 | 0 | 0 / 0 |
| concave-fine | 12240 | 4 | 4 | 4 | 4 | 0 / 0 |
| concave-fold | 7760 | 1 | 1 | 1 | 0 | 0 / 0 |
| concave-shape | 15494 | 7 | 7 | 7 | 0 | 0 / 0 |
| kernel-atlas-1024-moved | 3140 | 133 | 79 | 79 | 77 | 0 / 0 |
| kernel-atlas-1024 | 3140 | 104 | 43 | 43 | 43 | 0 / 0 |
| kernel-atlas-2048 | 3140 | 103 | 42 | 42 | 42 | 0 / 0 |
| kernel-ramp-r1-p0 | 2056 | 0 | 0 | 0 | 0 | 0 / 0 |
| kernel-ramp-r15-p0 | 2568 | 0 | 0 | 0 | 0 | 0 / 0 |
| kernel-ramp-r15-p25 | 2568 | 0 | 0 | 0 | 0 | 0 / 0 |
| kernel-ramp-r2-p0 | 1544 | 0 | 0 | 0 | 0 | 0 / 0 |
| kernel-ramp-r2-p25 | 1544 | 0 | 0 | 0 | 0 | 0 / 0 |
| tie-sweep-seams-box320 | 7805 | 214 | 214 | 214 | 214 | 0 / 0 |
| tie-sweep-seams-centred | 7805 | 142 | 142 | 142 | 142 | 0 / 0 |
| tie-sweep-seams-offcentre | 7805 | 139 | 139 | 139 | 139 | 0 / 0 |
| tie-sweep-strips-box320 | 8864 | 4 | 4 | 4 | 4 | 0 / 0 |
| tie-sweep-strips-centred | 8864 | 3 | 3 | 3 | 3 | 0 / 0 |
| tie-sweep-strips-offcentre | 8864 | 2 | 2 | 2 | 2 | 0 / 0 |
| **total** | | **5312** | **4783** | **4691** | **4615** | **0 / 0** |

**The Wand.** This is decision 285's normal-from-height holdout, scored on the CPU reference and not on a compiled check (`tmp/scratch/strip-rule/wand_score.py`, and `tmp/scratch/padding-port/wand_reference.py` for the integrated reference).
- Pre-strip, strip, and this rule without decision 340: 88 EXR and 49 PNG misses.
- With decision 340: 86 EXR and 49 PNG misses, with zero new coordinates against pre-strip in either format.

**What stays.** Misses remain on 18 of the 27 probes (4,691 ring coordinates; 16 probes and 4,615 coordinates with decision 340), so production keeps the refusals of decisions 245 and 259, and phase1.25 item 2.7 stays open.
