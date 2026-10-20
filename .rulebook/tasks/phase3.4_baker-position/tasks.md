## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase3.3_baker-evidence-publication

## 2. Implementation
- [x] 2.1 Implement the `Position` baker for each `Mode` and `Axis` - native CPU map in section 6 (decision 337)
- [ ] 2.2 Implement `Normalization` and `NormalizationScale`; record the effective normalisation in the binding and the receipt
- [ ] 2.3 Author the `Position` Tier 2b manifests under `parity/manifests/`

## 3. Tests
- [ ] 3.1 Tier 2b on plane, sphere and bevelled cube with highs for each exercised `Mode`/`Axis`/`Normalization`: hit/coverage first, then maps, exact
- [ ] 3.2 Tier 2b on the wand and hat low/high/cage pairs, exact against private goldens
- [ ] 3.3 Repeat 3.1 at two thread counts and on each qualified ISA; identical bytes

## 4. Acceptance
- [ ] 4.1 Acceptance: `Position` Tier 2b exact or covered by an owner-approved exception on every fixture

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass

## 6. Native CPU map (2026-10-20, decision 337)
- `src/bake/position_baker.{h,cpp}` on the shared primary hit of `embree_baker.cpp`: the high surface point at the hit (Embree's barycentrics, blended in double) in the meshes' scene frame; `LowAsHigh` gives the low point. `Mode` All axis writes xyz, One axis the coordinate on `Axis`. `BakeResult::position` is float32, unclamped; non-hit texels hold zero and keep their class. The canonical bytes gain a `POS1` block only when the map exists.
- Normalisation: `None` only, in centimetres (mesh units times `scale_to_internal`); no bounds apply, so `NormalizationScale` has no effect. `BBox` and `BSphere` (Painter's default) are refused with `NotYetSupported` naming this task: which bounds they use and how a point maps to a value are not recorded. `SubSampling` > 1 and `DilationWidth` > 0 are refused too.
- Effective normalisation: `PositionNormalizationRecord` in the result and `PositionNormalizationJson` for the binding's `baked.effective_normalization`. Nothing publishes a binding or a receipt yet (`phase3.3_baker-evidence-publication`), so 2.2 stays open.
- Parameters: Position's values are stored per texture set (`StoresBakerValues`), saved in `bake_settings.per_baker.Position`, loaded and mapped by `RequestFromParameters`; no link group (refused, naming this task). `baking_project.cpp`: an AO group compares only AO values, and saving keeps every stored baker's values.
- Evidence for 2.1: native cases `position_plane` (each Mode and Axis on the plane, centimetres at 2.54 cm per unit, within 1e-5), `position_sphere` (the sphere on the ground low as high: the ground's UV-to-position mapping, the sphere's radius), `position_bevel` (the bevelled cube with highs against the analytic chamfer hit points, All axis and One axis), `position_record`, `position_refusals` and `position_parameters`; `baking_project_test roundtrip` carries a Position value through save and reopen.
- Thread counts: `position_threads_in_process` and `test_bytes_equal_across_thread_counts[position-32]`: identical bytes at 1, 4 and N threads on the one qualified ISA (AVX2). Not 3.3, which repeats 3.1's Tier 2b comparison.
- Run: `python -m pytest tests/bake/test_bake_feasibility.py tests/bake/test_baking_project.py -k "position or capability_errors or parameters or bake_settings or linked_groups or roundtrip or transactions or invalid"`, 16 passed, exit 0 (log `tmp/scratch/bakers-simple/pytest-pos.log`). CPU only.
- Still open: 1.1 (prerequisites not accepted); 2.2 (BBox, BSphere and NormalizationScale wait on a golden; binding and receipt publication); 2.3 (manifests under `parity/manifests/`, outside this slice); 3.1-3.3 and 4.1 (Tier 2b against private goldens); the task-wide tails 5.1-5.3. No parity is claimed.
