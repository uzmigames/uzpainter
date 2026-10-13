# P1-PYAPI gate: `phase1.24_python-api-facade`

`phase1.24_python-api-facade` is the parent and acceptance task of P1-PYAPI (`docs/dag.md`; `docs/architecture/10-python-api.md`). Its five children are archived on main: phase1.19 (native module), phase1.20 (facade), phase1.21 (dispatcher and lifecycle), phase1.22 (CLI and capabilities) and phase1.23 (pipeline adapter). Their local run reports are `pyapi-native-module.md`, `pyapi-facade.md`, `pyapi-dispatcher-lifecycle.md`, `pyapi-cli-capabilities.md` and `pyapi-pipeline-adapter.md` in this folder.

Under decision 028, this report is the local-run evidence for the G1 gate record. The run was on 2026-10-12, branch `wt/phase1.24-api-parent` from main `8dc3c96`, envelope `painter-12.1.5_js-api.1.1.20`. The decisions are 115, 116 and 117.

**Result.** The evidence is recorded below. The P1-PYAPI gate is **open** on two items: 1.1, where two prerequisites are not accepted (§5), and 3.1, where the Dota 2 user-channel labels wait for the owner's clean-room ruling (§3). Decision 117 gave every other output outside the supported scope an owning checklist item. The code changes of this task are ready for merge review apart from task acceptance.

## 1. Integration added by this task

| Change | Where | Decision |
|---|---|---|
| The native inserts give Painter's effective defaults: Height `LinearDodge` and Normal `NormalMapDetail` on new content-stack fills, fill effects and groups; BaseColor 0.8 and Height 0 sources on a new fill; "Levels - Base color" and "Compare mask". The facade no longer re-applies them. | `src/python/bind_layerstack.cpp`, `stack_sync.{h,cpp}`, `python/uzpainter_facade/nodes.py` | 115 §1 |
| The native `sync_stack` builds the document `painter_layer_stack.py sync` builds through the facade. It used to blend Height `Normal` on the wand's height layers. | `src/python/stack_sync.cpp` | 115 §2 |
| A user channel takes a uniform colour as given. Before, the facade decoded an sRGB colour on every channel; BaseColor still decodes. | `python/uzpainter_facade/colour.py`, `nodes.py` | 115 §3 |
| The native replay of `fill-layer-readback` goes through UzPainter's own operations: `Transaction`, name addressing, `Stack.uid`, and `export.plan` / `start` / `Job.wait` with the Height map compared. | `tests/python/test_pyapi_tier0.py` | 115 §4 |
| A project records its template. `Settings(template=…)`, `project.templates()` and `project.template()` exist, export and `reload_mesh` read the recorded template, and the facade maps `create(template_file_path=…)` by the shipped file name. | `src/uzp_core`, `src/python`, `src/export/project_export.cpp`, `src/evaluator/templates.*`, `assets/templates` (5 `default_resolution`), `python/uzpainter_facade/project.py` | 116 |
| Each export job records its own sources. The Codex audit found that the adapter rebased every receipt on the project open at the end of the run, so it named the wrong project after a later switch, close or change of directory. Now:<br>• the job result carries `project_path` (absolute, resolved when `open` or `save_as` named the file) and `mesh_path`;<br>• `mesh_path` is the exported revision's own `MeshReference.source`, the absolute path that the last create or `reload_mesh` imported from, persisted in the manifest as the optional `mesh.source`;<br>• a project written before `mesh.source` existed has none, and its manifest is null with the reason;<br>• the adapter rebases each receipt on its own job's sources. | `src/uzp_core/types/project.h`, `manifest/manifest.cpp`, `schema/manifest.schema.json`, `src/mesh/mesh_import.cpp`, `src/python/bind_export.cpp`, `session.{h,cpp}`, `bind_project.cpp`, `adapters/assets3d/runner.py` | coordinator audit items |
| Capability manifest: the trace of 26 compared replays, the new symbols, and the `srgb8-material-channels` release gap of `export_project_textures` in both packages (owner phase1.25_pilot-wand item 2.6). | `tools/capabilities/*.json`, `tests/python/test_capability_conformance.py` | 112, 116 §5 |

## 2. Scope of the acceptance

- **Pipeline scripts (item 3.2)**, wand v1 inputs, pins from the R9 request manifest:
  - `painter_create.py` and `painter_layer_stack.py sync` return their JSON results.
  - `painter_export.py` runs its pinned bytes. The script saves the project, then the export engine refuses the 16-bit sRGB8 BaseColor with `NotYetSupported`, naming R-090, before writing any map file.
  - This task makes no claim about the wand's exported maps. The PNG 16 export of sRGB8 material channels is phase1.25_pilot-wand item 2.6. The five-map export and its parity with Painter are phase1.25 items 3.1 and 4.1 (decision 116 §5).
  - The capability manifest lists that export as a `release-gap` in both packages, owned by phase1.25 item 2.6. The conformance test calls it and requires `NotYetSupported` naming R-090, with the revision unchanged.
- **Tier 0 (item 3.1).** Every output in the supported scope is compared exactly with the golden, both recordings. The outputs outside it are listed in §3.

## 3. Outputs outside the supported scope, with their owners

| Outputs | Kind | Owner |
|---|---|---|
| Content-stack fill effects and their steps (`set-source-none-multichannel` s5…, `insert-positions` s5, s9, s12, s18, s23…) | Refused: `NotYetSupported` before any change (decision 081) | phase3.2_proc-filter-families |
| Mask-stack levels effects (`mask-stack` s13…, `insert-positions` s7, s26) | Refused (decision 081) | phase4.2_remaining-nodes |
| Compare masks (`insert-positions` s8, s21, s29) | Refused (decision 081) | phase4.1_nodes-mask-effects items 2.1, 3.1 |
| BaseColor PNG 16 exports (`active-channel-*`, `fill-layer-readback`, `mask-stack`, the R10 probes) | Refused before writing any map file (decision 103) | phase1.25_pilot-wand item 2.6 |
| A uid's value (`phase1-delete-node` s17, `phase1-resource-update` s14-s15) | Normalisation: Painter's own allocation. The identity outputs compare what a uid resolves to. | — |
| Resource contexts `project<N>` | Normalisation up to the session offset (decision 107 §4) | — |
| `phase1-execute-when-not-busy` s9-s10 | Painter's two recordings differ from each other | the recording (decision 109) |
| **Known divergences that return a value.** Each test requires them to still differ. | | |
| Painter's empty default paint layer "Layer 1" | Divergence: UzPainter creates no such layer. The structure readbacks are compared without it after asserting it is exactly that empty layer. | phase4.1_nodes-paint-layers item 2.8 |
| `phase1-reload-resources` recording 2 s9, s12: Painter reports reloads of bytes the project already holds | Divergence (decision 110 §6) | phase5.2_parity-report-tiers item 2.10 (decision 117): after recording 1 is exact, explained by a recording that settles it, or entered in `parity/exceptions.json` as a decision-032 r2 divergence. Named first by decision 110 §6 and phase1.21 item 2.8 (archived). |
| The channel labels of Dota 2's User0-User3 (`project-templates`) | Divergence: they read "", Painter's text is not shipped (decision 116 §4) | **Owner question q1** in the task's `.metadata.json` (decision 117): (a) ship generic labels, or (b) ship Painter's label text after the owner's licence review. Item 3.1 stays open until it is answered. |

Closed by phase1.15_compositor-colour-fits item 2.1 (decision 214, 2026-10-13): `phase1-reload-resources` recording 1 s9 and s12 (a grey bitmap on BaseColor now binds in sRGB, P20-A) and the 70/255 decode of `export-ocio-encode-legacy` (the Legacy decode fitted from P20-B) are compared exactly; their rows are removed.

## 4. Local run on the owner's machine

Each line is one pytest command, run directly with no pipe, with `UZP_UPDATE_TIER0_TRACE` unset unless noted. The exit status is pytest's own.

| Command | Result |
|---|---|
| `python -m pytest -q tests/python/test_pyapi_facade.py` | exit 0, 9 passed |
| `python -m pytest -q tests/python/test_pyapi_native.py` | exit 0, 16 passed |
| `python -m pytest -q tests/python/test_pyapi_dispatcher.py` | exit 0, 10 passed |
| `python -m pytest -q tests/python/test_pyapi_tier0.py tests/python/test_pyapi_lifecycle_tier0.py tests/python/test_pyapi_facade_tier0.py --deselect tests/python/test_pyapi_facade_tier0.py::test_uniform_colour_ramps_export_as_painter` | exit 0, 23 passed, 3 deselected (the ramps, row below) |
| `UZP_UPDATE_TIER0_TRACE=1 python -m pytest -q tests/python/test_pyapi_facade_tier0.py::test_uniform_colour_ramps_export_as_painter` | 3 passed in 979 s. All 192 exported maps and all 216 readbacks of each of `colour-ramps-srgb`, `-working` and `-raw` are exact, both recordings. A first run, with the facade decoding sRGB on user channels, failed 384 readbacks of `-srgb`: that measurement set decision 115 §3. |
| `python -m pytest -q tests/python/test_pyapi_cli.py tests/python/test_capability_conformance.py tests/capabilities` | 40 passed, 1 failed: the new `srgb8-material-channels` recipe lacked `dithering`, so it raised `ValueError` before the gap. The recipe was fixed (RGB channels, `dithering` false, `paddingAlgorithm` passthrough). The node was re-run alone (§4.1). |
| `python -m pytest -q tests/adapters` | exit 0, 40 passed |

The traced Tier 0 replays number 26. New ones: `native/fill-layer-readback` with its Height map, `facade/colour-ramps-*` (3) and `facade/project-templates`, where all 26 shipped templates are exact as created and after save and reopen (texture sets, resolution, channels, formats).

The capability manifest:

| Package | supported | pending-evidence | release-gap | desktop-only-omitted |
|---|---|---|---|---|
| `uzpainter` | 220 | 290 | 69 | — |
| Painter inventory | 262 | 295 | 294 | 15 |

Of the 63 UzPainter-only `pending-evidence` entries, 9 are now `supported`. The rest name gate G5 (phase5.6_gate-g5) as owner, with the reason (decision 115 §4).

### 4.1 After the provenance and recipe fixes

Build at 07:38, `zig build painter pyapi-tests --prefix <scratch>/p124/build`, exit 0. The native test targets `uzp-core-tests`, `uzp-core-transaction-tests`, `uzp-store-tests`, `uzp-store-inspect-tests` and `export-tests` also built, exit 0.

| Command | Result |
|---|---|
| `python -m pytest -q tests/python/test_capability_conformance.py::test_release_gaps_raise_not_yet_supported_before_mutation` (on the 07:29 build) | exit 0, 1 passed |
| `python -m pytest -q tests/uzp_core` | exit 0, 48 passed |
| `python -m pytest -q tests/python/test_pyapi_native.py` | exit 0, 16 passed |
| `python -m pytest -q tests/adapters` | exit 0, 44 passed |

The adapter regressions export a project, then each of the following, and require the manifest to name the export's own project and mesh:
- save it under another name;
- close it;
- create from a relative mesh path, save under a relative path and leave from another directory;
- reopen from another directory;
- reload identical mesh bytes from another folder;
- that reload followed by a revert to the revision before it.

## 5. Open

- **Item 1.1.** `phase1.18_export-engine` is not accepted: it waits on phase1.14_compositor-core and phase1.15_export-plan-compiler. `phase1.8_project-store` is not accepted: it waits on phase1.6_store-save-retention and phase1.7_store-inspect-census. Every child's code is on main.
- **Item 3.1.** Owner question q1 (`.rulebook/tasks/phase1.24_python-api-facade/.metadata.json`): may UzPainter ship Painter's label text for Dota 2's User0-User3? Decision 117 leaves it to the owner.
- **Recordings named** (owner action): P23-A, `save_as` onto an existing `.spp` (decision 113); P24-A, a template path that is missing or is not a template (decision 116); P22-B, one api-probe calling every Painter symbol marked `pending-evidence` (decision 112).
- **The adapter's session carry: fixed (decision 118; commits 1c09894, fbfbf97, 254d96e).** The runner stored `project.file_path()`, as given, as the next call's project. A script that changed directory and then saved under a relative path carried a path that the next process resolved in the client's directory. The call failed, or another project of the same name was reopened (Codex audit, P2).
  - The fix: the runner now carries `uzpainter.project.absolute_file_path()`, the path `open` or `save_as` resolved when it ran, and refuses a session file that names a relative path.
  - The host tests pass (`tests/adapters/assets3d/test_adapter_units.py`).
  - Verified natively on 2026-10-12: `test_a_project_saved_under_a_relative_path_is_reopened_where_it_was_saved` (`tests/adapters/assets3d/test_pipeline_adapter.py`) passed at fbfbf97, on `UzPainter.exe` SHA-256 `f7cf93233b44faf00e2be309691ba3fb44238e2551d5c08ceeb14cde01bfdcff`. Its first call changes directory and saves under a relative path. The second call, run from a directory that holds a same-named copy of another project, reopens the saved project: same UUID, same absolute path.
  - A bundle directory (Codex audit): it opens as the `.uzp` it is imported into, but the carry named the directory, and reopening it fails because the `.uzp` exists. `project_source`, which `absolute_file_path()` and the export jobs read, is now the store's own file, resolved when `open` or `save_as` ran. Host test `test_a_project_opened_from_a_bundle_is_carried_as_its_store_file`; native regression `test_a_project_opened_from_a_bundle_directory_is_reopened_from_its_store_file`. Both native regressions passed at 254d96e on 2026-10-12, on `UzPainter.exe` SHA-256 `ddd14fe0f9ed5af1e647797c3af9b63b90427890e194e7931e39223da592aa23`.

## 6. Reproduce

```
zig build painter pyapi-tests --prefix <prefix>
python -m pytest -q tests/python/test_pyapi_native.py tests/python/test_pyapi_facade.py
python -m pytest -q tests/python/test_pyapi_tier0.py tests/python/test_pyapi_lifecycle_tier0.py tests/python/test_pyapi_facade_tier0.py
python -m pytest -q tests/adapters
```
