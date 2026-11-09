## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase3.3_baker-evidence-publication

## 2. Implementation
- [x] 2.1 Implement the `WorldSpaceNormal` baker: high-poly normal at the hit in the project frame (`LowAsHigh` uses the low mesh's own normal) - native CPU map in section 6 (decision 337)
- [ ] 2.2 Encode to the channel format and value mapping established by the Tier 2b goldens; record the mapping in the receipt
- [ ] 2.3 Author the `WorldSpaceNormal` Tier 2b manifests under `parity/manifests/`

## 3. Tests
- [ ] 3.1 Tier 2b on plane, sphere and bevelled cube with highs: hit/coverage first, then maps, exact against private goldens
- [ ] 3.2 Tier 2b on the wand and hat low/high/cage pairs, exact against private goldens
- [ ] 3.3 Repeat 3.1 at two thread counts and on each qualified ISA; identical bytes

## 4. Acceptance
- [ ] 4.1 Acceptance: `WorldSpaceNormal` Tier 2b exact or covered by an owner-approved exception on every fixture

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass

## 6. Native CPU map (2026-10-20, decision 337)
- `src/bake/world_normal_baker.{h,cpp}` on the shared primary hit of `embree_baker.cpp`: the high mesh's interpolated corner normal at the hit, normalised in double, in the meshes' scene frame; `LowAsHigh` gives the low mesh's own normal. `BakeResult::world_normal` is float32 xyz, signed and unencoded; non-hit texels hold zero and keep their class. `SubSampling` > 1 and `DilationWidth` > 0 are refused with `NotYetSupported` (this task, decision 337). The canonical bytes gain a `WSN1` block only when the map exists, so AO and Normal bytes are unchanged.
- Evidence for 2.1: native cases `world_normal_plane` (three authored high normals, every covered texel within 1e-6), `world_normal_sphere` (the sphere on the ground low as high: the ground's own normal, the sphere within the tessellation angle of the radial direction, unit length), `world_normal_bevel` (faces, 45-degree edge chamfers and corner facets of the bevelled cube with highs, against the analytic facet normals; misses match the analytic chamfer depth), `world_normal_isolation` (with AO: same AO bytes, same map) and `world_normal_refusals`.
- Thread counts: `world_normal_threads_in_process` and the cross-process `test_bytes_equal_across_thread_counts[world_normal-32]` give identical bytes at 1, 4 and N threads on the one qualified ISA (AVX2). This is not 3.3, which repeats the Tier 2b comparison of 3.1.
- Run: `python -m pytest tests/bake/test_bake_feasibility.py -k "world_normal or capability_errors"`, 8 passed, exit 0 (log `tmp/scratch/bakers-simple/pytest-wsn.log`). CPU only.
- Still open: 1.1 (prerequisites not accepted); 2.2 (Painter's channel format and value mapping come from the goldens; none exists, so nothing is encoded); 2.3 (manifests under `parity/manifests/`, outside this slice); 3.1-3.3 and 4.1 (Tier 2b against private goldens, owner's machine); the task-wide tails 5.1-5.3. No parity is claimed; the result's status stays `pending-evidence`.

## 7. Recording requests (2026-11-02, decision 384)
- Item 3.1's Painter recordings are requested: `parity/envelopes/painter-12.2.0_js-api.1.1.20-env-a981b586eae7/requests/tier2b/bakes/world-space-normal-<scene>.json` (3). Not yet recorded; 3.2 has no request.

## 8. Shared-core comparison (2026-11-09, decision 415)
- `python -m tools.bake.usage_tier2b` bakes each admitted golden (admitted 2026-11-02, b0f751e2) from its own sequence with `bake-files` and compares Painter's nonzero texels with the native hits and covered texels (counts only; `tests/bake/test_usage_tier2b.py`). The core before 5bcb3c03 and HEAD (decision 408 samples, `SmoothNormals`) were both run through the same driver; r1 = r2 in every golden.
- Coverage: plane and sphere equal before and after (65536, 241782).
- Bevelled cube: Painter writes 129024 texels. Painter texels outside the native hits fall from 22968 to 20832, and the 20832 are exactly the native `CentreMiss` texels: Painter writes a value on covered texels whose ray misses. The native covered set (129024) is equal to Painter's before and after. No golden regressed.
- The native world normal on the sphere depends on the box-size metric (as Normal's does), before and after. Maps are not compared, because no channel format or value mapping is established (2.2). No item is ticked.
