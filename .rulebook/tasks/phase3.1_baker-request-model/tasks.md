## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase2.10_pilot-tunic-recovery

## 2. Implementation
- [x] 2.1 Vendor Embree 4.x from its upstream release under `thirdparty/` with `LICENSE`, `NOTICE` and `ORIGIN.md`; pin version and build configuration (ISA set, tasking, no fast-math) in `build.zig`
- [x] 2.2 Define `IBaker`, `Capabilities`, `BakeRequest` and `JobHandle`; implement `EmbreeBaker` with the explicit capability error for unqualified CPU/ISA configurations
- [x] 2.3 Implement deterministic sampling (Hammersley by texel index and sample id), fixed reduction order and thread-count-independent tile partitioning
- [x] 2.4 Implement low/high matching (`FilterMethod`, `_low`/`_high`/`_ignorebf` suffixes, `LowAsHigh`) and `IgnoreBackface`
- [ ] 2.5 Implement cages: custom cage mesh and distance-based frontal/rear (absolute or relative to the bounding box); report `Automatic` as a release gap in the capability manifest
- [x] 2.6 Implement per-texel hit classification (straight hit, cage hit, centre miss, hidden) and `SubSampling` coverage accumulation
- [ ] 2.7 Implement `DilationWidth` with optional `ApplyDiffusion` on the baked map only, keeping RAW; record distances in project units
- [ ] 2.8 Implement the `BakingParameters`/`Property` model (`common()`, `baker(usage)`, `set`, `Property.*`) from the Phase 0 discovery capture; enum integers from `enum_values()` labels
- [ ] 2.9 Author `assets/defaults/baking.json` with per-entry provenance and a local check on the owner's machine (decision 028) against the private defaults capture
- [ ] 2.10 Implement linked groups (`set_linked_group`, `set_linked_group_common_parameters`, `unlink_all*`, `get_link_group*`, `get_linked_texture_sets*`) as one transaction across linked sets; persist `bake_settings {common, detail, per_baker}`
- [ ] 2.11 Register the MCP Baking parameter tools `bake_inspect`, `bake_configure`, `bake_set_mesh_inputs`, `bake_capture_preset`, `bake_apply_preset`

## 3. Tests
- [ ] 3.1 Tier 0 API-probe goldens for current baking defaults and property metadata (`common().keys()`, `baker(usage).keys()`, labels, widget types, enum values) compared exactly on the owner's machine
- [ ] 3.2 Defaults check: every `assets/defaults/baking.json` entry equals the private capture hash it cites
- [x] 3.3 Local CPU lane (decision 200): repeatability of the ray-cast core on the analytic fixtures (plane, sphere, bevelled cube with highs) at 1, 4 and max threads — identical bytes
- [x] 3.4 Matching and cage tests on the bevelled cube with highs (suffix filtering, `LowAsHigh`, distance-based and custom cage), dilation keeps RAW, subsampling coverage counts
- [x] 3.5 Linked-set transaction test: a failing `set` on one linked set leaves every set unchanged; capability error test on an unqualified ISA configuration

## 4. Acceptance
- [ ] 4.1 Acceptance: defaults and property metadata exact against Tier 0 goldens; repeatable across thread counts; linked-set changes atomic

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass

## 6. Notes (feasibility slice, decision 302; 2026-10-19, branch `wt/bake-feas`)
- A permitted early-feasibility slice (SUP-014, `docs/roadmap.md` rule 1), not acceptance of any item above: no box is ticked, and prerequisite 1.1 still gates the task.
- Built: `src/bake/` (`EmbreeBaker` on the vendored Embree 4.4.1, its `BakeRequest`/`Capabilities`/`BakeResult`, the distance-based cage's primary ray, the AO usage), `tests/bake/` (authored fixtures generated in code, no Painter or Assets3D data) and the `bake-feasibility-tests` build step.
  - Toward 2.2: a synchronous `bake`, plus the capability error for an unqualified CPU, ISA or Embree build. `IBaker` and `JobHandle` are still open.
  - Toward 2.3: Hammersley addressing by texel index and sample id, a fixed reduction order and fixed 16 x 16 tiles.
  - Toward 2.6: the texel classes uncovered / straight hit / back-face hit / centre miss, and the ray classes escaped / front / back-face / self. Cage hit, hidden and `SubSampling` are still open.
- Toward 3.3 (plane, box and sphere-on-ground fixtures; the bevelled cube with highs is still open): the scene's bytes are identical at 1, 4 and 32 threads (SHA-256 `11cdde9b…e1d0fa`). `python -m pytest tests/bake/test_bake_feasibility.py`: exit 0, 12 passed.
- Parity: AO is `pending-evidence` (owner `phase3.4_baker-ao`), never `supported`. No Python or MCP symbol is exposed, so the capability manifest is unchanged.

## 7. Notes (request-model slice, decision 306; 2026-10-19, branch `wt/bake-req`)
- A second permitted slice (SUP-014), not acceptance: no box is ticked, prerequisite 1.1 still gates the task, and AO stays `pending-evidence` (owner `phase3.4_baker-ao`). No Python or MCP symbol is exposed, so the capability manifest is unchanged.
- Toward 2.2: `IBaker` (`caps()`, `bake() -> JobHandle`) and `JobHandle` (id, progress in tiles, `cancel()`, `wait()`, `Success | Cancel | Fail`, the result published whole on `Success` only); refusals are thrown before any job exists. SUP-023 fixed: workers in a joining container (a failed spawn no longer reaches `std::terminate`), Embree scene and geometries owned from their first acquisition, only the serial BVH build qualified (any other count bakes only on an explicit diagnostic path); SUP-031 fixed: a throwing tile callback fails the job instead of escaping a worker thread.
- Toward 2.4: `FilterMethod` Always / By mesh name with the `_low`/`_high`/`_ignorebf` suffixes, `LowAsHigh` with name matching, and `IgnoreBackface`, through an Embree argument filter on the primary ray.
- Toward 2.5: a custom cage given in memory (one per low part, same topology); loading it from a file stays `NotYetSupported`. Relative-to-bounding-box distances are still open.
- Toward 2.6: the `CageHit` and `Hidden` (request mask) texel classes; `SubSampling` 1/2/4/8 as per-texel coverage and hit counts.
- Toward 2.7: `DilationWidth` into uncovered texels only, RAW kept; `ApplyDiffusion` is refused (`NotYetSupported`). Units are still open.
- Toward 2.8: `BakingParameters`/`Property` with the keys of `06-baking.md` §2, labels and option labels from the public pages, value types only where a page widget or the task states them (others `Pending`), typed `set()` in one transaction; Painter's `name()`, `widget_type()`, enum integers, ranges, `properties()` and every default but the three suffixes raise `NotYetSupported` until the Tier 0 capture (2.8, 2.9, 3.1). Linked groups (2.10) are not started.
- Toward 3.3 and 3.4: the bevelled cube with highs (a chamfered cube, a knob with an `_ignorebf` cover, a decoy) with analytic per-texel classes. Its bytes are identical at 1, 4 and 32 threads (SHA-256 `0034cd97…2f3ed`); the sphere scene's RAW AO, class and ray maps are byte-identical to slice 1's. `python -m pytest tests/bake/test_bake_feasibility.py`: exit 0, 31 passed.

## 8. Reconciliation and slice 3 (decision 311; 2026-10-19, branch `wt/bake3`)
- A third permitted slice (SUP-014), not acceptance. Prerequisite 1.1 and acceptance 4.1 stay open, and AO stays `pending-evidence` (owner `phase3.4_baker-ao`). No Python or MCP symbol is exposed: `uzpainter.baking` stays gapped and the capability manifest is unchanged.
- Ticked against main, with evidence. The test file is `tests/bake/test_bake_feasibility.py`, and a case name `X` stands for its node id `test_native_case[X]`.
  - 2.1: the package was vendored in 4b34ecb (`thirdparty/embree/`: `ORIGIN.md`, `MANIFEST.json` with the DLLs' SHA-256, the licence files; the release has no `NOTICE`, as `ORIGIN.md` records). This slice pins the version, ISA and tasking in `build.zig` `bake_flags`, compiles with no fast-math and no contraction, and qualifies only a TBB device (`capability_errors`, `build_threads_diagnostic`).
  - 2.2: e9a3152 and 444636d. Cases `capability_errors`, `job_async`, `job_cancel`, `job_fail`, `worker_spawn_failure`, `embree_acquisition_failure`, `tile_callback_throws`.
  - 2.3: e9a3152. Cases `sampling` and `threads_in_process`, and `test_bytes_equal_across_thread_counts[scene-256]`.
  - 2.4: 444636d. Cases `match_by_name`, `match_always`, `low_as_high_matching` and `back_face_primary`.
  - 2.6: e9a3152 and 444636d. Cases `open_plane`, `centre_miss`, `custom_cage`, `hidden_mask`, `subsampling_bevel` and `subsampling_coverage`.
  - 3.3: plane, sphere and bevelled cube at 1, 4 and every hardware thread. Evidence: `test_bytes_equal_across_thread_counts[scene-256]` and `[bevel-32]` (e9a3152, 444636d), with `[cage_file-32]` added here.
  - 3.4: 444636d and this slice. Cases `match_by_name`, `low_as_high_matching`, `custom_cage`, `cage_file`, `dilation` and `subsampling_bevel`.
  - 3.5: this slice's `linked_groups` (a failing `set()` across linked sets changes nothing and leaves the revision where it was), plus `capability_errors` (unqualified ISA).
- Implemented here, under decision 311:
  - toward 2.5: relative distances, with the box size metric named by the request. The cage is read from a mesh file (`src/bake/mesh_inputs.*`) and its vertices pair with the low mesh's by index.
  - toward 2.7: distances in centimetres over the mesh's required `scale_to_internal`, recorded in the result (`UZPBAKE3`).
  - toward 2.8: `RequestFromParameters`.
  - toward 2.10: `BakingSession` link groups as one transaction, and `ToBakeSettings`/`LoadBakeSettings`.
- Still open:
  - 2.5: the box size metric is not established, so a relative distance from the Painter parameters is refused.
  - 2.7: `ApplyDiffusion` stays `NotYetSupported`, by the panel's majority.
  - 2.8, 2.9, 3.1 and 3.2: the Tier 0 capture on the owner's machine.
  - 2.10: link groups are not persisted, and `bake_settings` is not yet written into the project document.
  - 2.11: the MCP tools.
- Tests: `zig build bake-feasibility-tests -j4`: exit 0. `uzp-bake-feasibility-tests run`: exit 0, 33 cases passed. `python -m pytest tests/bake/test_bake_feasibility.py`: exit 0, 39 passed. ruff and mypy are clean. The `cage_file` scene's bytes are identical at 1, 4 and 32 threads (SHA-256 `c65e3519...cb284c`), measured on one build and machine; this is not a golden.
