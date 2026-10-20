## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase3.3_baker-evidence-publication

## 2. Implementation
- [ ] 2.1 Implement the `Thickness` baker: inward secondary rays per `NbSecondary`, distances, `Spread`, `Distribution`
- [ ] 2.2 Implement `MaximizeRange`; record the effective range in the binding and the receipt
- [ ] 2.3 Author the `Thickness` Tier 2b manifests under `parity/manifests/`

## 3. Tests
- [ ] 3.1 Tier 2b on plane, sphere and bevelled cube with highs (with and without `MaximizeRange`): hit/coverage first, then maps, exact
- [ ] 3.2 Tier 2b on the wand and hat low/high/cage pairs, exact against private goldens
- [ ] 3.3 Repeat 3.1 at two thread counts and on each qualified ISA; identical bytes

## 4. Acceptance
- [ ] 4.1 Acceptance: `Thickness` Tier 2b exact or covered by an owner-approved exception on every fixture

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass

## 6. Native CPU ray evidence (2026-10-20, decision 341)
- `src/bake/thickness_baker.{h,cpp}` on the shared primary hit of `embree_baker.cpp`: at each hit, `NbSecondary` rays from the high point over the hemisphere opposite the interpolated high normal by `Distribution`, searched from `MinDistance` to `MaxDistance` (centimetres over `scale_to_internal`, or fractions of the box size with `MaxDistanceRelativeScale` under decision 311's rule), with decision 302's samples. Each ray's first hit is classed as an AO ray is (escaped, front, back face, self; `NotCast` off hits). `BakeResult::thickness_ray_class` and `thickness_ray_distance` (centimetres, 0 when escaped) hold one slot per texel and ray; `ThicknessRecord` the settings, effective distances, box size and ray totals (apart from AO's). The canonical bytes gain a `THK1` block only when the evidence exists.
- No per-texel thickness value is computed: how a texel's ray distances combine (mean, median, escaped rays, which hit classes) is not recorded. So every `MaximizeRange` is refused with `NotYetSupported` naming this task and decision 341, Painter's default "Relative to min/max (per UV tile)" included; only a request without a normalisation bakes (an evidence request no parameter makes). Also refused: `Spread` other than 180 and `FilterMethodSecondary` other than Always (by `RequestFromParameters`, as for AO), `SubSampling` > 1, `DilationWidth` > 0, more than 2^26 rays, and relative distances without a box-size metric (phase3.5_embree-bakers).
- Parameters: Thickness's values are stored per texture set, saved in `bake_settings.per_baker.Thickness`, loaded and mapped by `RequestFromParameters`; no link group (refused, naming this task). `ThicknessRecordJson` gives the record for the binding (`value` and `range` null).
- Evidence: native cases `thickness_plane` (a 0.25-deep slab at 2.54 cm per unit: every ray a back-face hit at 0.25 / cos or escaped past 10, for Cosine and Uniform; an open plane: every ray escapes), `thickness_sphere` (low as high: the sphere's chords from inside within the tessellation bound, the open ground's rays all escape), `thickness_bevel` (the bevelled cube with highs: each ray's exit from the chamfered cube's 26 planes within 1e-4, or escaped past 1.5; the knob's rays escape), `thickness_record` (relative distances times the named box size equal the absolute ones; the JSON; with AO, AO's bytes and ray totals unchanged), `thickness_refusals` and `thickness_parameters` (Painter's defaults mapped and refused; stored, saved, loaded; `Spread` and `FilterMethodSecondary` refused; no link group).
- Thread counts: `thickness_threads_in_process` and `test_bytes_equal_across_thread_counts[thickness-32]`: identical bytes at 1, 4 and N threads on the one qualified ISA (AVX2). Not 3.3, which repeats 3.1's Tier 2b comparison.
- Run: `python -m pytest tests/bake/test_bake_feasibility.py -k "thickness or capability_errors"`, exit 1 with `thickness_bevel` failing (the test drew its rays around the analytic facet normal; the baker's interpolated normal carries -0 in a zero component, which selects the other orthonormal frame), 8 passed (log `tmp/scratch/bakers-more/pytest-thickness.log`); after the test drew its rays around the baked normal, `test_native_case[thickness_bevel]` 1 passed, exit 0 (log `tmp/scratch/bakers-more/pytest-thickness-bevel.log`); the `BoundingBoxSize` extraction: `-k "relative_distances or units or cage_file"`, 5 passed, exit 0 (log `tmp/scratch/bakers-more/pytest-box-size.log`). CPU only.
- Still open: 1.1 (prerequisites not accepted); 2.1 (the rays are cast, but `Spread` other than 180 is refused and no thickness value exists until a golden settles the reduction); 2.2 (`MaximizeRange` and the effective range wait on the value; binding and receipt publication); 2.3 (manifests under `parity/manifests/`); 3.1-3.3 and 4.1 (Tier 2b against private goldens); the task-wide tails 5.1-5.3. No parity is claimed.
