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
