# P1-MESH gate — `phase1.7_mesh-loader`

Task `phase1.7_mesh-loader`, the parent and acceptance task of P1-MESH (`docs/dag.md`: "`12-…` §9 fixtures pass"). Children, all archived: `phase1.4_mesh-importers` (2026-10-10), `phase1.5_mesh-tangents-certificate` and `phase1.6_mesh-reload` (2026-10-11); prerequisites `phase1.3_document-model` and `phase0.9_normal-convention-fixture` archived. Decision 028: the Painter comparison runs locally on the owner's machine and the hosted CPU lane skips it with `oracle_unavailable`. This report is the evidence for the G1 gate record (certificate and reload fixtures).

**Result: P1-MESH gate met. Every `docs/architecture/12-mesh-import.md` §9 fixture passes on one build, the reload/rename/split fixtures preserve or deliberately reject their bindings, and the normal-convention fixture re-run over the production importer and production MikkTSpace frames reproduces the P0-NORMAL verdicts against Painter and the DirectX verdict in UzEngine, which runs only as a separate external process.**

## Integration added by this task

| Item | Change |
|---|---|
| 3.1–3.3 one build | The §9 fixtures are the children's tests; this task runs all of them against a single `zig build painter mesh-tests` prefix (`uzp-mesh-tests.exe`, `uzp-mesh-reload-tests.exe`, `uzp-normal-bake.exe`) and against the current tree, in which `src/mesh/` and every child test file is byte-identical to `8e5f3bc`, the commit of the hosted run below. |
| build half of "UzEngine only as an external consumer" | `tests/mesh/test_mesh_loader.py::test_mesh_build_references_no_uzengine_artifact`: a fresh-cache `zig build mesh-tests --verbose-cc --verbose-link` is inspected with the `build-path` rule of `tools/vendoring/vendor_check.py`, so every include and library path of the mesh library, its native tests and the normal-convention bake comes from the repository, the Zig toolchain or the Windows SDK, and never from a UzEngine checkout. `vendor_check`'s own build covers the render-core and `UzPainter.exe` steps; this adds the mesh steps. The run half is the UzEngine leg below, where only UzEngine's own executables touch UzEngine code. |

## §9 fixture map (all green)

| §9 fixture | Test |
|---|---|
| mirrored UVs | `uzp-mesh-tests.exe` `mirrored_uvs` |
| hard edges | `uzp-mesh-tests.exe` `hard_edge` |
| negative OBJ indices | `uzp-mesh-tests.exe` `obj_negative_indices`; `test_mesh_import.py::test_negative_indices_equal_positive_twin` |
| n-gons | `uzp-mesh-tests.exe` `fan_triangulation`; `test_ngons_fan_triangulated_and_flagged`; `test_tier0_polygon_triangulation_equals_painter` (fan from the last corner, `parity/semantics/polygon-triangulation.json`, `exact`) |
| duplicate material names | `test_mesh_import.py::test_duplicate_material_names` |
| instances / transforms | `test_instances_and_transforms_gltf`, `test_instances_and_transforms_fbx` |
| units | `uzp-mesh-tests.exe` `units`; `test_mesh_import.py::test_units` |
| multi-set body | `test_multi_set_body_three_texture_sets_in_file_order` |
| coincident opposite faces (the hat lesson) | `uzp-mesh-tests.exe` `coincident_opposite_faces`; counted under `faces.coincident_opposite` in the certificate |
| certificate over every format | `test_mesh_certificate.py::test_certificate_of_every_format[obj|gltf|fbx]`; `uzp-mesh-tests.exe` `certificate_defects`, `certificate_in_report`, `auto_unwrap_rejected_first`, `tangent_frame_rules`, `texel_convention`, `uv_metrics_two_islands`, `uv_tiles`, `hashes_separate_concerns`, `formats`, `obj_objects_and_materials`, `obj_missing_attributes`, `obj_parse_errors` |
| reload: bindings preserved | `uzp-mesh-reload-tests.exe` `identical_reload`, `moved_vertices`, `uv_change_replaced`, `added_and_removed_sets` |
| reload: deliberately rejected | `rename_fixture`, `split_fixture`, `merge_fixture` (explicit error with a mapping proposal, project unchanged); `failure_mid_reload` (old mesh and all bindings intact) |
| normal convention across Painter, UzPainter and UzEngine | `test_mesh_certificate.py::test_production_frames_bake_as_the_prototype`, `test_normal_convention_rerun_reproduces_the_verdict`; `python -m tools.parity.normal_convention check`; the UzEngine leg below |

## Owner's machine run (2026-10-11)

| Item | Value |
|---|---|
| Machine | Windows 11 Pro 10.0.26200, NVIDIA GeForce RTX 4090 (these tests use no GPU) |
| Toolchain | Zig 0.15.2 (Debug), Python 3.13.9 |
| Tree | commit `54db879` plus the working-tree changes of this task; `src/mesh/` and the children's tests byte-identical to `8e5f3bc` |
| Build | `zig build painter mesh-tests`: exit 0, no warnings, no diagnostics printed |
| Native | `uzp-mesh-tests.exe run`: 18 cases, all PASS. `uzp-mesh-reload-tests.exe run`: 8 cases, all PASS |
| Python | `python -m pytest tests/mesh`: 29 passed in 140.55 s, 0 skipped |
| Full gate | `zig build painter mesh-tests` (0 warnings); `python -m mypy` no issues; `ruff check .`; `ruff format --check .`; `python -m pytest`; `python -m tools.parity.guard` 0 blocked |

### Normal-convention re-run with the production loader and frames

`python -m tools.parity.normal_convention check --prototype uzp-normal-bake.exe`: exit 0, "residuals equal the published semantics". The production bake (production importer `ImportMeshFile`, production MikkTSpace frames, `InterpolateFrame` / `ToTangentSpace` / `FromTangentSpace`) reproduces every residual and verdict of `parity/semantics/tangent-frame.json` (sha256 `d49694bf9d9ba64f4a4ba417f47e34cf0a1b2978d0b71e0a7a7c7b686f5506cf`) against Painter's two recordings in the private store: `green-channel-directx` and `no-hit-texels` `exact`, `green-channel-opengl`, `tangent-frame-per-fragment`, `tangent-frame-per-vertex` and `tangent-frame-project-default` `calibrated`, best modes `PerFragment` / `PerVertex` / `PerVertex` as published.

Production bake of the plane-dome pair, 512 px, `max-height` 0.5, `max-depth` 0.01: 2 low triangles, 176 high triangles, 262144 covered texels, 128404 hit texels, worst coded round-trip 0.0011980284 degrees. `plane-dome-PerFragment-inverse-opengl.png` sha256 `3a79be10cb7674338dcf8df5274cc0e66d5f0a3b868405a3ed8db90e0c75e5a7`; its hit texels, the 16-bit consumer map and the 8-bit consumer map are code-for-code equal to the Phase 0 prototype's (133740 no-hit texels filled with the flat normal, as in Phase 0).

### UzEngine leg (external consumer only)

UzEngine's own executables at commit `f4dcfc467b79b0538ef5f0aa615f16e15e8820ab`, built in Phase 0 outside both repositories, run as separate processes: `uzmesh.exe` cooks the authored low OBJ and `uzengine.exe --hidden --screenshot` shades it with the production map. No UzPainter target links or includes any UzEngine artifact (the build-path test above).

| Item | Value |
|---|---|
| Consumer inputs (sha256) | `plane-dome-low.obj` `f0546bc9a99737447522cb62a047c9f22586b93d51b0dbab51ac0c19ad1b7323`; `plane-dome-normal-opengl-16bit.png` `404514dc1147422b580581e1b7dd06df89ee9cf9cd55474fb2cc07dfacb65e16`; `plane-dome-normal-opengl-8bit.png` `d07a2a70c24da6a3f9176823aa2d936818bff36b3ad2d39b95dd0508442cd493`; `flat-normal-8bit.png` `519ef34110c7a17ce423b1ec52cd8114ede5a959fe86bd6b0597a540ffce8589` |
| `uzengine.exe` | sha256 `009a89c60ec41fb4c66ad06001a1e1bc1ef72131f7aa871a577191234a76f49a`, run-manifest hash `fnv1a64:e4d34b13be80977e` |
| Cooked meshes | `plane.uzmesh` and `cube.uzmesh` byte-identical to the Phase 0 run |
| Renders | 18 screenshots (4 lights x {dome 16-bit, dome 8-bit, flat}, 3 world-normal views, 1 tangent view, 2 orientation views): every one pixel-identical to the Phase 0 consumer run, max \|Δ\| 0, 0 differing pixels |
| Measurements | half mean linear luminances and G-buffer world-normal means equal the Phase 0 run and the published values of `tools/parity/normal_convention/uzengine-consumer.json` |
| Verdict | `directx` reproduced: with the light from OBJ -Z the +v-leaning half of the dome is the darker one (0.01554 against 0.09440) and reverses with the light from +Z (0.09494 against 0.01561); the red control behaves as expected. An OpenGL-convention map needs its green inverted, or a DirectX export, for this consumer path |

## Hosted CPU lane

| Item | Value |
|---|---|
| Run | Parity run `38100063195` on commit `8e5f3bc` (2026-10-11), hosted `windows-latest`, `UZP_NO_GPU=1` |
| Result | `tests/mesh/test_mesh_import.py`, `test_mesh_certificate.py` and `test_mesh_reload.py` all passed; the Painter comparison skipped with `oracle_unavailable` (decision 028), its evidence being the local run above. The run's two `tests/store` failures came from a partial commit of the store task and are fixed in `4c75222` |
| Coverage | `src/mesh/` and every child test file are byte-identical between `8e5f3bc` and this tree, so that run is the hosted evidence for the §9 fixtures. `tests/mesh/test_mesh_loader.py` is new in this task and first runs on the hosted lane after the owner's next push; what it must show there is one `zig build mesh-tests` with exit 0 and no build-path violation |

## Reproduce

```
zig build painter mesh-tests
zig-out\bin\uzp-mesh-tests.exe run
zig-out\bin\uzp-mesh-reload-tests.exe run
python -m pytest tests\mesh
python -m tools.parity.normal_convention check --prototype zig-out\bin\uzp-normal-bake.exe
```
