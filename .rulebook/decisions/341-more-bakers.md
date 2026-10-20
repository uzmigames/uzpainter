# 341. More bakers on the CPU core: Opacity as 1 on a hit and 0 elsewhere; Height as the signed low-to-high distance in centimetres with every MaximizeRange refused; Thickness as per-ray inward evidence with no per-texel value; every value Painter's labels leave open refused before any work; parity pending-evidence

**Status**: accepted
**Date**: 2026-10-20
**Related Tasks**: phase3.4_baker-opacity, phase3.4_baker-height, phase3.4_baker-thickness, phase3.5_embree-bakers

## Context

The coordinator asked for the offline items of the Thickness, Height and Opacity baker tasks on the Embree CPU core, in the pattern of decision 337: CPU only, each map in its own file, a parameter whose Painter semantics are unrecorded refused with `NotYetSupported` naming the owner task and this decision, and nothing claimed equal to Painter.

What is recorded (`assets/defaults/baking.json`, decision 323): Opacity has no keys of its own. Height has `Divisor` ("Scaling divisor", default 1, range 1e-5 to 100) and `MaximizeRange` ("Normalization": Relative to ray distances / Relative to low mesh (per UV tile) / Relative to min/max (per UV tile) / Manual, default Relative to low mesh); it has no secondary-ray keys, although its task lists `NbSecondary`, `Spread` and `Distribution`. Thickness has AO's ray keys without `IgnoreBackfaceSecondary` (`NbSecondary` 64, `MinDistance` 1e-5, `MaxDistance` 0.1, `MaxDistanceRelativeScale` on, `Spread` 180, `Distribution` Cosine, `FilterMethodSecondary` Always) and `MaximizeRange` ("Normalization": Relative to ray distances / Relative to min/max (per UV tile) / None, default Relative to min/max). No Tier 2b golden of any of the three exists, and no recorded output states a channel format, a value mapping or a normalisation formula.

The rule of decision 337 §1 applies unchanged: a value whose label names exactly one computation on data the bake mesh carries is implemented (`pending-evidence`); a value that needs a formula, a constant or an input nothing recorded fixes is refused before any work.

## Decision

### 1. Shared to the maps of this decision
Decision 337 §2 holds for each of them:
- they run on the shared primary hit of `embree_baker.cpp` and, combined with other usages, leave those maps' bytes alone;
- a non-hit texel holds zero and is told apart by the class map;
- `SubSampling` above 1 and `DilationWidth` above 0 are refused;
- each map present is appended to the canonical bytes as a tagged block; a result without it keeps its bytes;
- every value is written by one texel's own slot, so the bytes do not depend on the worker count.

### 2. Opacity (phase3.4_baker-opacity)
- **The value.** The opacity of the high surface the primary ray hit. A bake mesh carries no transparency input (no alpha, texture or material), so a hit surface is opaque: 1. Non-hit texels (misses, back-face hits, hidden, uncovered) are 0 with their class.
- **Stored unencoded.** `BakeResult::opacity`, float32 in [0, 1]. Painter's channel format (item 2.2) is established by the Tier 2b goldens, so no encoding is chosen. The block tag is `OPA1`.
- **Refused.** `SubSampling` above 1: a texel partly covered by the high mesh would need a coverage fraction or another resolve, and neither is recorded. `DilationWidth` above 0.
- **No parameters.** Opacity has no keys, so nothing is stored for it and `RequestFromParameters` maps nothing.
- **Assumption.** If Painter's Opacity reads a transparency of the high mesh (a texture's alpha, a material opacity), that input is outside the bake mesh and outside every analytic fixture, which have none: on them the computation above is the only one.
- **Settles it:** an Opacity golden on the plane, sphere and bevelled cube, for the encoding and the edge coverage.

### 3. Height (phase3.4_baker-height)
- **The distance.** The signed distance from the low surface to the high surface along the primary ray: the low point's distance along the ray (`max_height` for the distance-based cage, the cage-to-low length for a custom cage) minus the hit's. It is positive where the high surface lies in front of the low one, towards the ray's origin, and negative behind it. `LowAsHigh` gives zero.
- **The unit.** Centimetres: the mesh-unit distance times `scale_to_internal`, the project's unit rule (`12-mesh-import.md` §3, decision 311).
- **`MaximizeRange`: every value refused** before any work, naming phase3.4_baker-height and this decision. Nothing recorded says, for Relative to ray distances, which of the frontal and rear distances bounds each sign and where zero falls; for Relative to low mesh, what range the low mesh gives a UV tile; for Relative to min/max, which texels the per-tile range spans and where zero falls; for Manual, what range it reads. Nor is it recorded how `Divisor` composes with any of them. Relative to low mesh is Painter's default, so a Height bake with Painter's defaults is refused.
- **The evidence request.** The request's normalisation is optional, as ID's generator is (decision 337 §5): absent, the bake produces the signed distance, unnormalised. `RequestFromParameters` always sets one, so a parameter-made Height bake is refused until a golden settles it. `Divisor` is recorded with the map and not applied.
- **The map.** `BakeResult::height_map`, float32 and unclamped (the result's `height` is the image height). The block tag is `HGT1`.
- **The record.** `HeightNormalizationRecord` holds the settings, the unit scale and whether a normalisation and the divisor were applied (neither is). `HeightNormalizationJson` gives it as the binding's `baked.effective_normalization` (`MaximizeRange: null`, `unit: centimetre`, `signed: true`, `range: null`). Publishing the binding and the receipt belongs to `phase3.3_baker-evidence-publication`.
- **The parameter model.** Height's values are stored per texture set (`StoresBakerValues`), saved in `bake_settings.per_baker.Height` and loaded like Position's, with no link group. `RequestFromParameters` maps both keys.
- **Not read.** The task's `NbSecondary`, `Spread` and `Distribution` are not keys of Painter's Height, so no secondary ray is cast for it.
- **Settles it:** a Height golden on the bevelled cube and an inflated sphere for each `MaximizeRange`, at two `Divisor` values.

### 4. Thickness (phase3.4_baker-thickness)
- **The rays.** At each hit, `NbSecondary` rays from the high surface point over the hemisphere opposite the interpolated high normal (inward), by `Distribution`, searched from `MinDistance` to `MaxDistance`. The labels name these: the ray count, the occluder window, the angle (only 180 is cast, as for AO) and the distribution. The samples are decision 302's, Hammersley by texel index and ray id, so a Thickness ray set is the same with or without AO.
- **The distances.** Absolute distances are centimetres over `scale_to_internal`; with `MaxDistanceRelativeScale` they are fractions of the project mesh's box size, under decision 311's rule, so a request without a box-size metric is refused (`NotYetSupported`, phase3.5_embree-bakers). `BoundingBoxSize` now gives that size to both AO's record and Thickness's; AO's bytes are unchanged.
- **The evidence.** Each ray's first hit is classed as an AO ray is (decision 302 §4: escaped, front face, back face, its own triangle); off hits it is `NotCast`. `thickness_ray_class` holds the class and `thickness_ray_distance` the hit distance in centimetres (0 when escaped), one slot per texel and ray. `ThicknessRecord` holds the settings, the box size, the effective distances and the ray totals, apart from AO's `rays`. The block tag is `THK1`.
- **No per-texel thickness.** How a texel's ray distances combine is not recorded: their mean, a median, whether escaped rays count and at what distance, which hit classes count (from inside, the far wall is a back face by our winding). The task's own wording names no reduction either. So no thickness value exists, and every `MaximizeRange` value is refused before any work, naming phase3.4_baker-thickness and this decision; Relative to min/max is Painter's default, so a Thickness bake with Painter's defaults is refused. The request's normalisation is optional: absent, the bake produces the per-ray evidence (an evidence request no parameter makes).
- **Refused too.** `Spread` other than 180 and `FilterMethodSecondary` ("Self occlusion") other than Always, by `RequestFromParameters`, as AO's (decision 323). `SubSampling` above 1 and `DilationWidth` above 0. More than 2^26 rays (texels times `NbSecondary`; 1024 x 1024 at 64 rays): the evidence is for fixtures, and a full-size map waits on the recorded value.
- **The record for the binding.** `ThicknessRecordJson` gives the settings, the effective distances and the unit, with `value` and `range` null.
- **The parameter model.** Thickness's values are stored per texture set, saved in `bake_settings.per_baker.Thickness` and loaded like Height's, with no link group. `RequestFromParameters` maps every key.
- **Settles it:** a Thickness golden on the slab, the sphere and the bevelled cube for each `MaximizeRange`, against which a reduction of the stored rays is fitted.

## Alternatives Considered

- **Encoding Opacity as 8-bit or 16-bit grey.** Not taken: the channel format is item 2.2's, established by the goldens. A float in [0, 1] loses nothing.
- **Averaging sub-samples into a coverage fraction.** Rejected: the resolve rule is not recorded (decision 337's rule for every map).
- **A Height mapping of our own** (zero at 0.5, the frontal distance at 1 and the rear at 0; or the divisor applied to the raw distance). Rejected under the rule: where zero falls, which bound each sign takes and how the divisor composes are choices the labels leave open.
- **A thickness value of our own** (the mean distance of the hit rays, escaped rays at `MaxDistance`, then each normalisation). Rejected under the rule: the reduction and the miss value are choices the labels leave open. The per-ray evidence loses nothing, so any reduction a golden settles can be applied to it.
- **Per-texel summaries instead of every ray** (hit count, sum, minimum and maximum of the distances). Not taken: they lose what a reduction other than those needs; the bound keeps the evidence to fixture sizes.
- **The distance along the low normal instead of along the ray.** Not taken: it differs only for a custom cage, and the task names the distance along the cast ray.

## Consequences

- New: `src/bake/opacity_baker.{h,cpp}` (in the `bake-feasibility-tests` step) and `tests/bake/opacity_bake_cases.h` (six native cases, the `opacity` cross-process fixture).
- Changed: `bake_request.*` (the `opacity` map and its `OPA1` block), `embree_baker.*` (the usage, its validation and its texel write), `tests/bake/bake_feasibility_test.cpp`, `test_bake_feasibility.py`, `06-baking.md` §3.3.
- Height: new `src/bake/height_baker.{h,cpp}` and `tests/bake/height_bake_cases.h` (seven native cases, the `height` cross-process fixture); changed `baking_parameters.*` (Height values stored, saved, loaded and mapped) and `tests/bake/baking_project_test.cpp` (the round trip carries a Height value).
- Thickness: new `src/bake/thickness_baker.{h,cpp}` and `tests/bake/thickness_bake_cases.h` (seven native cases, the `thickness` cross-process fixture); changed `bake_request.*` (`BoundingBoxSize`, the per-ray maps and their `THK1` block), `embree_baker.cpp` (`CastSecondary`, the texel hook and the serial count) and `baking_parameters.*` (Thickness values stored, saved, loaded and mapped). The capability case's unsupported usage is now BentNormals.
- The bytes of every AO, Normal, WorldSpaceNormal, Position and ID result are unchanged.
- No Python or MCP symbol is added. `BakingParameters.set` through Python and MCP `bake_configure` now store Thickness and Height values, where they refused them before. Parity stays `pending-evidence`; every Tier 2b item stays open.
