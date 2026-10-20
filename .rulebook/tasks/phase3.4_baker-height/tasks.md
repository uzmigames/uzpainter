## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase3.3_baker-evidence-publication

## 2. Implementation
- [ ] 2.1 Implement the `Height` baker: signed low-to-high distance with `NbSecondary`, distances, `Spread`, `Distribution`, in project units
- [ ] 2.2 Implement `MaximizeRange` and `Divisor`; record the effective range and divisor in the binding and the receipt
- [ ] 2.3 Author the `Height` Tier 2b manifests under `parity/manifests/`

## 3. Tests
- [ ] 3.1 Tier 2b on plane, sphere and bevelled cube with highs (with and without `MaximizeRange`, two `Divisor` values): hit/coverage first, then maps, exact
- [ ] 3.2 Tier 2b on the wand and hat low/high/cage pairs, exact against private goldens
- [ ] 3.3 Repeat 3.1 at two thread counts and on each qualified ISA; identical bytes

## 4. Acceptance
- [ ] 4.1 Acceptance: `Height` Tier 2b exact or covered by an owner-approved exception on every fixture

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass

## 6. Native CPU map (2026-10-20, decision 341)
- `src/bake/height_baker.{h,cpp}` on the shared primary hit of `embree_baker.cpp`: the signed distance from the low surface to the high surface along the primary ray (the low point's distance along the ray minus the hit's), positive where the high surface lies in front of the low one, in centimetres (mesh units times `scale_to_internal`). `LowAsHigh` gives zero. `BakeResult::height_map` is float32, unclamped; non-hit texels hold zero and keep their class. The canonical bytes gain an `HGT1` block only when the map exists.
- `MaximizeRange`: every value is refused with `NotYetSupported` naming this task and decision 341, Painter's default "Relative to low mesh (per UV tile)" included: how each maps a signed distance to a value, and how `Divisor` composes with it, are not recorded. Only a request without a normalisation bakes (an evidence request no parameter makes); `Divisor` is recorded and not applied. `SubSampling` > 1 and `DilationWidth` > 0 are refused too.
- Record: `HeightNormalizationRecord` in the result and `HeightNormalizationJson` for the binding's `baked.effective_normalization` (`MaximizeRange: null`, `Divisor`, `normalization_applied`/`divisor_applied` false, `unit: centimetre`, `signed: true`, `range: null`). Nothing publishes a binding or a receipt yet (`phase3.3_baker-evidence-publication`).
- Parameters: Height's values are stored per texture set, saved in `bake_settings.per_baker.Height`, loaded and mapped by `RequestFromParameters`; no link group (refused, naming this task).
- Painter's recorded Height has no `NbSecondary`, `Spread` or `Distribution` keys (`assets/defaults/baking.json`, decision 323), so 2.1's secondary-ray part has nothing to read.
- Evidence: native cases `height_plane` (two high planes at +0.005 and -0.003 mesh units, 2.54 cm per unit, distance-based and through a custom cage), `height_sphere` (zero low as high; the sphere on the ground inflated by 0.01: the ground at +0.01, the sphere within the facet bound), `height_bevel` (the bevelled cube with highs: minus the analytic chamfer depth, the knob at zero), `height_record` (the record and its JSON, `Divisor` not applied, AO's bytes unchanged with Height), `height_refusals` (each `MaximizeRange`, Painter's defaults, `SubSampling`, `DilationWidth`, `Divisor` 0) and `height_parameters` (stored, saved, loaded, mapped; each label refused; no link group); `baking_project_test roundtrip` carries a Height value through save and reopen.
- Thread counts: `height_threads_in_process` and `test_bytes_equal_across_thread_counts[height-32]`: identical bytes at 1, 4 and N threads on the one qualified ISA (AVX2). Not 3.3, which repeats 3.1's Tier 2b comparison.
- Run: `python -m pytest tests/bake/test_bake_feasibility.py -k "height or capability_errors"`, 9 passed, exit 0 (log `tmp/scratch/bakers-more/pytest-height.log`); `python -m pytest tests/bake/test_baking_project.py`, 4 passed, exit 0 (log `tmp/scratch/bakers-more/pytest-baking-project.log`). CPU only.
- Still open: 1.1 (prerequisites not accepted); 2.1 (the signed distance in project units is baked, but Painter's map is always normalised and every `MaximizeRange` is refused, and the item's `NbSecondary`, `Spread` and `Distribution` are not Painter keys; the item's text needs the owner's amendment before it can close); 2.2 (`MaximizeRange` and `Divisor` wait on a golden; binding and receipt publication); 2.3 (manifests under `parity/manifests/`); 3.1-3.3 and 4.1 (Tier 2b against private goldens); the task-wide tails 5.1-5.3. No parity is claimed.
