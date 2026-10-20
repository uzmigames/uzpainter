## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase2.10_pilot-tunic-recovery

## 2. Implementation
- [x] 2.1 Vendor Embree 4.x from its upstream release under `thirdparty/` with `LICENSE`, `NOTICE` and `ORIGIN.md`; pin version and build configuration (ISA set, tasking, no fast-math) in `build.zig`
- [x] 2.2 Define `IBaker`, `Capabilities`, `BakeRequest` and `JobHandle`; implement `EmbreeBaker` with the explicit capability error for unqualified CPU/ISA configurations
- [x] 2.3 Implement deterministic sampling (Hammersley by texel index and sample id), fixed reduction order and thread-count-independent tile partitioning
- [x] 2.4 Implement low/high matching (`FilterMethod`, `_low`/`_high`/`_ignorebf` suffixes, `LowAsHigh`) and `IgnoreBackface`
- [x] 2.5 Implement cages: custom cage mesh and distance-based frontal/rear (absolute or relative to the bounding box); report `Automatic` as a release gap in the capability manifest
- [x] 2.6 Implement per-texel hit classification (straight hit, cage hit, centre miss, hidden) and `SubSampling` coverage accumulation
- [x] 2.7 Implement `DilationWidth` with optional `ApplyDiffusion` on the baked map only, keeping RAW; record distances in project units
- [x] 2.8 Implement the `BakingParameters`/`Property` model (`common()`, `baker(usage)`, `set`, `Property.*`) from the Phase 0 discovery capture; enum integers from `enum_values()` labels
- [x] 2.9 Author `assets/defaults/baking.json` with per-entry provenance and a local check on the owner's machine (decision 028) against the private defaults capture
- [x] 2.10 Implement linked groups (`set_linked_group`, `set_linked_group_common_parameters`, `unlink_all*`, `get_link_group*`, `get_linked_texture_sets*`) as one transaction across linked sets; persist `bake_settings {common, detail, per_baker}` — supported Common/Detail and AO surface, with decision 311's explicit refusals retained; project persistence and evidence in section 9
- [x] 2.11 Register the MCP Baking parameter tools `bake_inspect`, `bake_configure`, `bake_set_mesh_inputs`, `bake_capture_preset`, `bake_apply_preset`

## 3. Tests
- [ ] 3.1 Tier 0 API-probe goldens for current baking defaults and property metadata (`common().keys()`, `baker(usage).keys()`, labels, widget types, enum values) compared exactly on the owner's machine
- [x] 3.2 Defaults check: every `assets/defaults/baking.json` entry equals the private capture hash it cites
- [x] 3.3 Local CPU lane (decision 200): repeatability of the ray-cast core on the analytic fixtures (plane, sphere, bevelled cube with highs) at 1, 4 and max threads — identical bytes
- [x] 3.4 Matching and cage tests on the bevelled cube with highs (suffix filtering, `LowAsHigh`, distance-based and custom cage), dilation keeps RAW, subsampling coverage counts
- [x] 3.5 Linked-set transaction test: a failing `set` on one linked set leaves every set unchanged; capability error test on an unqualified ISA configuration

## 4. Acceptance
- [ ] 4.1 Acceptance: defaults and property metadata exact against Tier 0 goldens; repeatable across thread counts; linked-set changes atomic

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
- [x] 5.2 Write tests covering the new behavior
- [x] 5.3 Run tests and confirm they pass

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
  - 2.10 was open at this slice: project persistence is completed in section 9.
  - 2.11: the MCP tools.
- Tests: `zig build bake-feasibility-tests -j4`: exit 0. `uzp-bake-feasibility-tests run`: exit 0, 33 cases passed. `python -m pytest tests/bake/test_bake_feasibility.py`: exit 0, 39 passed. ruff and mypy are clean. The `cage_file` scene's bytes are identical at 1, 4 and 32 threads (SHA-256 `c65e3519...cb284c`), measured on one build and machine; this is not a golden.

## 9. Project persistence (2026-10-20, branch `fix/baking-project-persistence`)
- Item 2.10 now includes `src/bake/baking_project.{h,cpp}`: independent loading, validated all-set storage, and `EditBakingSession`/`ExecuteBakingSession` through the real document and project-store transactions. Common/Detail and AO groups persist by texture-set ID in `bake_settings.linked_groups`; explicit empty groups survive reopening. Unrelated extension fields remain intact. The legacy common-group default applies only to consistent member values.
- `tests/bake/test_baking_project.py`: 3 passed, 0 skipped on Debug (29.53 s). The three native cases (`roundtrip`, `transactions`, `invalid`) also passed on each of ReleaseSafe, ReleaseFast and ReleaseSmall. Real `.uzp` save/reopen covers values, groups, rename/reorder and unlink; transaction checks cover no-op, replay, stale revision, idempotency conflict, invalid values and commit-sink failure. Malformed metadata and unsupported original settings are rejected before replacement. Evidence: `tmp/scratch/baking-project/evidence.json`.
- Documentation: `docs/architecture/06-baking.md` section 3.1 and this task's baker spec. Source citation/revision audit, Python lint/type checks, Zig formatting and Rulebook validation passed. No GPU or Painter session was used.
- Other baker usages, unrecorded property metadata/defaults and unsupported regrouping retain decision 311's refusals and their existing owners. Items 2.8, 2.9, 3.1, 3.2 and acceptance 4.1 remain open; this persistence result does not accept the parent task or any parity gate.

## 10. Closing items (decision 323; 2026-10-20, branch `wt/bake-model`)
- 2.5 ticked. What is implemented:
  - the custom cage, in memory or read from a mesh file (decisions 306 and 311);
  - the distance-based frontal and rear distances, absolute in centimetres or relative to the project mesh's bounding box.

  What stays refused, each refusal now naming `phase3.5_embree-bakers`:
  - the relative box-size metric: `NotYetSupported` unless the request names it;
  - `CageMode` Automatic: `CapabilityError`. It is the capability manifest's release gap `substance_painter.baking.bake_async` @ `cage-mode:automatic`, seeded in `RELEASE_GAPS` and listed in `10-python-api.md` §3.

  Evidence:
  - `uzp-bake-feasibility-tests run capability_errors` and `run relative_distances` (built with `zig build bake-feasibility-tests -j2`): exit 0, PASS each;
  - `python -m pytest tests/capabilities/test_capabilities.py -k "release_gap or schema or evidence"`: exit 0, 9 passed.
- 2.7 ticked. What is implemented:
  - `DilationWidth`, into uncovered texels only, writing the baked map with RAW kept (decisions 306 and 311);
  - distances in centimetres over `scale_to_internal`, recorded with the map (`DistanceRecord`, `UZPBAKE3`).

  What stays refused: `ApplyDiffusion` on, with `NotYetSupported` before any work, owned by `phase3.5_embree-bakers`. The manifest adds the release gaps `bake_async` @ `apply-diffusion` and @ `relative-to-bounding-box`.

  Evidence: `uzp-bake-feasibility-tests run dilation`, `run units` and `run capability_errors` (exit 0, PASS each), plus the capabilities tests named under 2.5.
- 2.9 and 3.2 ticked.
  - The table: `assets/defaults/baking.json`, authored by UzmiGames, 60 keys plus the texture set's baking state. Each entry cites the Tier 0 record `tier0/defaults-templates/baking-defaults` on Painter 12.1.5 (`53d9cfc9...`, recordings r1 to r3 equal).
  - The local check: `tools/bake/bake_defaults.py`, decision 323 §4.
  - Evidence: `python -m tools.bake.bake_defaults check --model <catalog dump>` run on the owner's machine against the private store, read only. Exit 0, status `pass`, 0 problems; table SHA-256 `cb5c925d...` in the working tree, after the check moved to `tools/bake/` (the paths of `tools/parity/` were held for Codex). `python -m pytest tests/bake/test_bake_defaults.py`: exit 0, 11 passed, with `test_the_private_capture_equals_the_table` run, not skipped.
- 2.8 ticked (decision 323 §3).
  - The model: `BakingParameters`/`Property` are built from the authored table, embedded through `EmbedInputs`. `common()` gives 19 keys and `baker(usage)` gives every usage's observed keys. `name()`, `label()`, `widget_type()`, `enum_values()` and `enum_value()` answer from the table; enum integers come only from `enum_values()`. `set()` is typed and range-checked, in one transaction.
  - What stays refused with `NotYetSupported`:
    - `properties()`, since Painter's meta properties carry its descriptive text and the clean room does not copy it;
    - a value outside a key's range;
    - storing a value for a baker other than AO (its owner task);
    - the unestablished defaults of `OutputSize` and `TonemappingBounds`.
  - Evidence: `zig build bake-feasibility-tests baking-project-tests -j2` exit 0, then the native cases `run parameters`, `linked_groups`, `bake_settings`, `parameters_to_request` and `capability_errors` (exit 0, PASS each).
    - `python -m pytest tests/bake/test_baking_project.py`: exit 0, 4 passed, including `test_model_equals_the_authored_table` (the `catalog` dump equals the table).
    - `python -m pytest tests/bake/test_bake_feasibility.py -k "parameters or linked_groups or bake_settings or capability_errors or dilation or units or relative_distances"`: exit 0, 8 passed.
    - `tools.bake.bake_defaults check --model`: model equals table equals capture, exit 0.
  - Item 3.1 stays open. Its Tier 0 API probe compares the Python `substance_painter.baking` surface, and `uzpainter.baking` is still gapped: binding the parameter API to Python (this task's Impact) is not done yet. The native model's metadata is already compared exactly through the `catalog` dump.
- 2.11 ticked (decision 323 §5).
  - The tools: `bake_inspect`, `bake_configure`, `bake_set_mesh_inputs`, `bake_capture_preset` and `bake_apply_preset` are served by the worker over the parameter model, each change one transaction.
  - The gates: the texture set's baking state arguments are gated release gaps, and `bake_start` stays a gap.
  - The manifest: `mcp-tools.json` was regenerated (`UZP_UPDATE_MCP_TOOLS=1`), and the five matrix rows are `available` with the Python-disabled fixture.
  - Evidence: `zig build painter -j2`: exit 0.
    - `python -m pytest tests/supervisor/test_typed_tools.py -k "bake_parameter_tools or every_family_is_listed or unavailable_families or direct_pipe_client or resources_and_prompts"`: exit 0, 5 passed.
    - `tests/supervisor/test_operation_matrix.py -k "registered_tools or matrix_is_published"`: exit 0, 2 passed.
    - `tests/capabilities/test_operation_matrix.py`: exit 0, 16 passed.
    - `tests/supervisor/test_registry.py -k "prompt or capabilities"`: exit 0, 4 passed.

## 11. The Python surface and item 3.1 (2026-10-20, branch `wt/bake-py`, commit 628513d7)
- Bound: `substance_painter.baking.BakingParameters` (`BakingParameters(material_id)`, `from_texture_set`, `from_texture_set_name`, `texture_set`, `common()`, `baker(usage)`, `set()`, `get_curvature_method`, `get_enabled_bakers`, `is_textureset_enabled`), `baking.CurvatureMethod` and `properties.Property` (`value`, `name`, `short_name`, `label`, `widget_type`, `enum_values`, `enum_value`), over the native model (`src/python/bind_baking.cpp`, `python/uzpainter_facade/baking.py`).
  - Each handle resolves through `bake::LoadBakingSession` on every call. `set()` is one transaction over `bake::EditBakingSession`. An `Enum` value is its integer; a pair is a tuple, as Painter documents `value()`.
  - Decision 323's refusals are kept, each `NotYetSupported` before any change: `Property.properties()`, the unestablished defaults of `OutputSize` and `TonemappingBounds`, out-of-range values, and values for a baker other than AO. The baking-state setters, `is_baker_enabled` and the UV-tile members name `phase3.5_embree-bakers`. `bake_async`, `bake_selected_textures_async` and the link-group functions stay gaps.
  - The manifest keeps the three `bake_async` release gaps. It adds `Property.value` @ `default-unestablished` and `BakingParameters.set` @ `out-of-range` and @ `baker-other-than-ao`. The replay's trace (`facade/baking-defaults` in `tools/capabilities/tier0-trace.json`) makes the exercised symbols `supported` with `tier0/defaults-templates/baking-defaults` (decision 112). `set`, `from_texture_set_name`, `texture_set` and `CurvatureMethod.FromNormalMap` are `pending-evidence`.
- Item 3.1 stays open. `tests/python/test_pyapi_baking.py::test_baking_defaults_equal_painter` runs the recorder's own `painter_side.baking_capture` inside the embedded interpreter against the facade. It replays the golden as `record-defaults` recorded it: r1 fresh, r2 after save and reopen, r3 on a second fresh project. It compares every captured field with the private record (`53d9cfc9...`, read from the store, read only) by type-strict equality, on all 60 keys and the three state outputs.
  - Exact on all three recordings: `common().keys()` and every `baker(usage).keys()`, `name`, `short_name`, `label`, `widget_type`, `enum_values`, `enum_value` of every label, the `value()` of 58 of the 60 keys, `get_curvature_method`, `get_enabled_bakers` and `is_textureset_enabled`.
  - Not exact (refused with `NotYetSupported`, named in the test's `REFUSED`; the test asserts this exact set):
    - the `value()` of `OutputSize` and of Curvature's `TonemappingBounds`: Painter returns a value on a fresh project, and UzPainter refuses it as an unestablished default (decision 323);
    - `properties()` of every key: the clean-room refusal (decision 323).
  - So the metadata the item names is exact, but two current defaults are refused, not equal. 3.1 closes when those two values are established by a recording (for example `OutputSize` at a second texture-set resolution) or the owner accepts the refusal.
- Tail 5.1 to 5.3 ticked (this section with sections 6 to 10):
  - Docs: `src/python/PYAPI.md` (`baking` and `properties`), `python/FACADE.md` §1 and §2, `docs/architecture/06-baking.md` §2.
  - Tests: `tests/python/test_pyapi_baking.py` (table readback, set, save and reopen; refusals before any change; the Tier 0 replay), and the baking recipes added to `tests/python/test_capability_conformance.py`.
- Evidence (no GPU, no Painter). Logs are in `tmp/scratch/bake-py/`:
  - `zig build pyapi-tests -j2` and `zig build painter -j2`: exit 0.
  - `python -m pytest tests/python/test_pyapi_baking.py tests/python/test_capability_conformance.py tests/python/test_pyapi_native.py::test_later_phase_calls_raise_not_yet_supported_before_mutation tests/python/test_pyapi_facade.py::test_every_facade_symbol_is_documented_and_no_private_symbol_exists`: 9 passed, 1 failed (`pytest-python.log`). The failure was `test_supported_entries_equal_the_tier0_trace`: `uzpainter.exception` still cited the golden after `NotYetSupported` was dropped from the evidence. After the fix, that node id alone passed: exit 0, 1 passed (`pytest-rerun.log`). `test_baking_defaults_equal_painter` ran against the store, not skipped.
  - `python -m pytest tests/capabilities/test_capabilities.py`: exit 0, 28 passed (`pytest-capabilities.log`).
  - ruff and mypy are clean on the touched Python, and `mypy --strict` on `python/`.
- Not ticked: 1.1 (`phase2.10_pilot-tunic-recovery` is not accepted), 3.1 (above) and 4.1.
