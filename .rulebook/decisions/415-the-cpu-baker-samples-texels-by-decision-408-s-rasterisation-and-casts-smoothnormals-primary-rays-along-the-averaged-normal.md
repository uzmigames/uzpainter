# 415. The CPU baker samples texels by decision 408's rasterisation and casts SmoothNormals primary rays along the averaged normal

**Status**: accepted
**Date**: 2026-11-09
**Related Tasks**: phase3.2_baker-normal, phase3.4_baker-ao, phase3.4_baker-id, phase3.4_baker-thickness, phase3.4_baker-world-space-normal, phase3.4_baker-position, phase3.4_baker-curvature

## Context

Commit 5bcb3c03 changed two things in the CPU baker's shared core (`src/bake/embree_baker.cpp`), and no decision recorded them. Every usage goes through this core, so the change reaches AO, WorldSpaceNormal, Position, Height, Thickness, ID, Opacity and the Normal map that Curvature and BentNormals would read:

1. **Texel samples.** A sample is placed on the low UV triangles as decision 408 rasterises them:
   - each UV coordinate goes through float32 device coordinates, p = ((2 t - 1) + 1) N / 2;
   - p is rounded to the nearest 1/256 texel, ties to even, and the rows are flipped;
   - a sample on a shared edge belongs to the triangle for which that edge is top-left;
   - the sample's barycentric weights are those of the snapped texel-space triangle.

   Before this change, a sample took the exact UV barycentrics of the texel centre, with edges included and the lowest (part, triangle) first.
2. **`SmoothNormals`** ("Average normals", Painter's default on, `assets/defaults/baking.json`) is read. With a distance-based cage, the primary ray starts and runs along the interpolated averaged normal. At each low vertex, that normal is the normalised sum, in double precision and in first-appearance order, of the distinct authored normals of the part's vertices at the same position, compared bit for bit. Off, the ray runs along the interpolated authored normal, as before. A custom cage's rays and the tangent frame still use the authored data. `keys_not_read` is now `SkewFaceBehavior` only.

Evidence (task notes `phase3.2_baker-normal` §11; `tools/bake/normal_tier2b.py`; `tests/bake/test_normal_tier2b.py`):

- **Normal.** `normal-plane` is exact on all 65 536 hit texels and `normal-bevelled-cube` on all 108 192. Hit/coverage equals Painter's on all seven Normal goldens, r1 and r2. On the bevelled cube, change 2 is what closes coverage: without it, Painter hits 2 136 texels near the hard edges where the native centre ray misses. Change 1 alone changes nothing there. On the hemisphere, change 1 brings the differing texels from 36 034 down to 971 (per-vertex) and 1 005 (per-fragment) of 150 140.
- **The other usages** (`tools/bake/usage_tier2b.py`, 2026-11-09). The 60 non-Normal goldens were baked with the core before 5bcb3c03 and with HEAD, both through the same driver:
  - The bevelled cube's AO, ID and Thickness (`None`, `Relative to min/max`) hit sets go from 2 136 Painter-only texels to equal.
  - WorldSpaceNormal and Position on the bevelled cube go from 22 968 to 20 832 Painter texels outside the native hits. Those 20 832 are exactly the native `CentreMiss` texels, and the covered set is unchanged and equal to Painter's.
  - Every plane, sphere and slab golden is unchanged.
  - No golden regressed.

## Decision

1. **The sampling is decision 408's rasterisation for every usage.** The baker uses one sample grid. It is the grid that the export's coverage, the evaluator's geometry masks and the Tier 1 masks already use, so a baked texel and a covered texel are the same texel.
2. **`SmoothNormals` is read for every usage**, as specified above. Painter exposes it as a common parameter, and the bevelled cube's AO, ID, Thickness, WorldSpaceNormal and Position goldens show the same added hits as its Normal golden.
3. **The averaging rule is not confirmed.** It is exact on the bevelled cube, the only recorded mesh whose hard edges split vertex normals. Three things stay open: whether Painter averages by position bitwise or within a tolerance, whether it weights the normals (by angle or area, or counts a repeated normal once as here), and whether parts or UV seams bound the averaging. A golden with unequal face counts or areas around a split vertex settles them (the Wand and Hat high/cage pairs of item 3.3 or a dedicated fixture). Until then, the rule is not extended beyond its current form, and no exception is created or widened.

## Alternatives Considered

- **Scoping the change to the Normal usage.** Rejected: coverage is shared, and the other usages' goldens improve under it in the same way.
- **Keeping exact UV barycentrics for the non-Normal usages.** Rejected: it would give the baker two grids, and none of their goldens prefers the old one.

## Consequences

- `docs/architecture/06-baking.md` §3.2 and the `phase3.2_baker-normal` spec ("Painter's Texel Samples And Ray Directions") describe the rule.
- Native expectations built on the old grid or on `SmoothNormals` off were updated in 5bcb3c03: `subsampling_coverage`, `position_sphere`, `position_parameters`, `height_parameters` and `thickness_parameters`.
- `tests/bake/test_usage_tier2b.py` pins the other usages' coverage, one golden per usage and scene.
- Remaining work:
  - AO, ID, Thickness and Position maps still do not compare, because the native baker refuses Painter's defaults or the recorded settings: AO `Attenuation 'Linear'` and `GroundPlane`, ID colour generators, Thickness `MaximizeRange`, Position `BBox` and `BSphere`.
  - WorldSpaceNormal and Position must still write a value on missed covered texels, as Painter does. This is owned by their tasks.
  - Curvature is not baked natively.
