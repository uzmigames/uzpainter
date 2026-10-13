# The native Python API (`src/python/`)

Task `phase1.19_pyapi-native-module` (child of `phase1.24_python-api-facade`, P1-PYAPI). Implements the native `uzpainter` module of `docs/architecture/10-python-api.md` §1, §5 and §7 under decisions 082, 085, 105 and 106. Task `phase1.21_pyapi-dispatcher-lifecycle` (decisions 109 and 110) adds the dispatcher thread, the engine-computation state, the mesh reload and the resource queries of §6. Task `phase1.22_pyapi-cli-capabilities` (decisions 111 and 112) adds the `run` host and `uzpainter.capabilities` (§7). Tests: `tests/python/` (`zig build pyapi-tests`, `python -m pytest tests/python`). Local run report: `parity/reports/phase1/pyapi-native-module.md`.

## 1. Shape

| File | Role |
|---|---|
| `interpreter.{h,cpp}` | The embedded CPython 3.13 (phase0.7): isolated configuration, `python313._pth` beside the DLL. |
| `uzpainter_module.cpp` | `PYBIND11_EMBEDDED_MODULE(uzpainter)`: creates the submodules, registers each in `sys.modules`, and keeps `uzpainter._selftest` for `selftest`. |
| `session.{h,cpp}` | The open project (a `store::ProjectStore` bound to a `core::Document`) and the mutation contract: `Mutate`, the native `Transaction`, the script log. |
| `errors.{h,cpp}` | `uzpainter.exception` and the translation of every C++ error into it. |
| `jobs.{h,cpp}` | Worker jobs: one worker thread, `Job.wait` / `cancel`, `BusyError` checks; paused while engine computations are disabled. |
| `dispatcher.{h,cpp}` | The Python dispatcher thread of `02-runtime-topology.md` §4 (§6 below). |
| `stack_sync.{h,cpp}` | The `sync_stack` composite (LAY-07), `RemoveNode`, `ImportResource`. |
| `edits.{h,cpp}` | The native edits the bindings and the worker's typed MCP tools share (decision 164): channel checks, fills, sources, blending, LAY-06 insertion with the insert defaults, levels, texture sets and channels, mesh-map binding, resource import and replacement, the mesh reload (`MeshReloadCall`). An API call submits them with a fresh key (`Mutate`), a typed tool with its client's key (`Submit`). |
| `script.{h,cpp}` | `RunScript`: a script file as `__main__`, its `result`, output (captured until the dispatcher drained), error, and the revisions it committed. |
| `run.{h,cpp}` | `UzPainter.exe run` (§7): the arguments, the interpreter, `RunScript`, one `UZP_JSON:` report line, the exit status. |
| `capabilities.{h,cpp}` | `UzPainter.exe capabilities` and `uzpainter.capabilities` (§7). |
| `bindings.h`, `bind_*.cpp` | The modules: `bind_core` (`Result`, `last_result`, `Transaction`), `bind_color`, `bind_textureset`, `bind_resource`, `bind_layerstack` (with `source` and `levels`), `bind_project`, `bind_export` (with `jobs`), `bind_misc` (`logging`, `application`, `properties` and the later-phase modules). |

`UzPainter.exe` links all of it statically, with the mesh importers. `uzp-pyapi-tests.exe` (`tests/python/pyapi_runner.cpp`) is the test runner: the `run` host of §7 without the rest of `UzPainter.exe`. It is installed beside the embeddable package, `assets/templates/`, `assets/export-presets/` and `capabilities.json`.

## 2. Modules

Module and class names follow Painter's documented API wherever a Painter symbol exists. This module adds UzPainter's own members; the facade (phase1.20) reproduces Painter's quirks on top of it.

- **`project`.**
  - Lifecycle: `create(mesh_file_path, Settings(...))`, `open`, `close`, `is_open`.
  - Templates (decision 116): `Settings(template=<id>)` creates the stacks from an installed template (`templates()` lists `{id, name, painter_template}`; an unknown id raises `ValueError` before anything is created). The project records it (`template()`; the manifest's `settings.template`), and every evaluation and export reads its base values. The settings' resolution overrides the template's `default_resolution`.
  - `absolute_file_path()` (decision 118): the project's store file as an absolute path, resolved against the working directory when `open` or `save_as` ran, and None while untitled. A bundle directory opens as the `.uzp` it is imported into, and this names that file, which reopens the project; the directory would be imported again. `file_path()` returns the path as the call named it. The Assets3D adapter carries the absolute path between calls, so a script that changes directory before a relative `save_as` is reopened where it saved.
  - `reload_mesh(path, import_cameras=None, material_mapping={})`: one transaction over `mesh/reload.h`. Texture sets are matched by material, added sets get the channels of the project's template, and the new mesh's bytes are stored with the commit. Renamed, split or merged materials raise `MaterialMappingError` (a `ProjectError` whose `details` hold the proposal and the renames to pass back).
  - Saving: `save(ProjectSaveMode)`, `save_as`, `save_as_copy`, `revert(revision | checkpoint)`.
  - State: `revision()`, `checkpoints()`, `needs_saving()`, `file_path()`, `name()`, `get_uuid()`, `last_imported_mesh_path()`, `Metadata(context)`.
  - Recipes (decision 122): `dump_recipe()` returns the recipe dump of the current revision
    (`src/uzp_core/MANIFEST.md` §8; inside a `Transaction`, the committed revision).
    `rebuild_from_recipe(recipe, resources_dir)` opens a new untitled project rebuilt from a dump
    (a dict or the path of its JSON) and the resource files of `resources_dir` (named `<sha256>`,
    any extension: the `export-bundle` `res/` layout), in one transaction. Every stored resource
    must be there with its bytes, the mesh must re-derive from them alone, and the support check
    runs on the whole project; anything else raises before a project exists. `recipe.{h,cpp}`
    holds the session dump and the application's recipe host (its version and the installed
    templates' base values), which `UzPainter.exe inspect` uses too.
- **`textureset`.**
  - Module functions: `all_texture_sets`, `set_resolutions`, `get_active_stack`, `set_active_stack`. The active stack is the default address of calls that take a stack and is otherwise inert.
  - `TextureSet`: `from_name`, `name`, `get_resolution` / `set_resolution`, `all_stacks`, `get_stack`, `all_uv_tiles`, `get_mesh_map_resource` / `set_mesh_map_resource`.
  - `Stack`: `from_name`, `all_channels`, `get_channel`, `add_channel`, `remove_channel`, `edit_channel`. `remove_channel` also removes the channel's per-node entries.
  - `Channel`, `Resolution`, and the enums `ChannelType`, `ChannelFormat`, `MeshMapUsage`.
- **`layerstack`.**
  - Node classes: `Node`, `LayerNode`, `EffectNode` and the twelve node classes.
  - Navigation: `InsertPosition`, `get_root_layer_nodes`, `get_node_by_uid`, `get_node_by_name` (LAY-06), `find_nodes_by_name`.
  - Edition: `insert_fill` / `insert_paint` (a layer or an effect by position), `insert_group`, `insert_levels_effect`, `insert_compare_mask_effect`, `insert_color_selection_effect`, `insert_anchor_point_effect`, `instantiate`, `delete_node`, `sync_stack` (LAY-07).
  - Every insert takes an optional `name`. A node of that name and type already in the position's list is returned and the call is a no-op; a match of another type, or several matches, fails before any change.
  - `insert_generator_effect`, `insert_filter_effect`, `insert_smart_material` and `insert_smart_mask` raise `UnsupportedProcedural`.
- **`source`.** `SourceUniformColor` (`get_color` / `set_color`), `SourceBitmap` (`resource_id`, `get_color_space` / `set_color_space` / `reset_color_space`), `SourceMode`.
- **`levels`.** `LevelsParamsMono` and `LevelsParamsRGB`, read and written by `LevelsEffectNode.get_parameters` / `set_parameters` with `affected_channel`.
- **`resource`.**
  - `ResourceID` is `resource://project/<name>?version=<sha256>`; `Resource` and `Usage` go with it.
  - `import_project_resource` imports PNG files of usage TEXTURE; other usages and formats raise `NotYetSupported` naming their owner.
  - `list_project_resources`, `replace_node_resource(node, resource, channel=None)` (LAY-08), `update_layer_stack_resource`.
  - `list_used_resources()`: the entries the layer stacks and mesh maps bind. `resource_origin(id)`: the file an entry was imported from.
- **`export`.** `plan(config)` is the typed dry run. `list_project_textures(config)`, `start(config, fixed_names=[])` returns a `jobs.Job`, and `export_project_textures(config, fixed_names=[])` starts and waits (decision 105 §5). The job's result names the publication (`directory`, `files`, `fixed_names`, `generation`, `receipt`, `receipt_sha256`, `plan_hash`, `revision`) and the sources the export was queued from: `project_path`, the store file as `absolute_file_path()` names it, and `mesh_path`, the exported revision's mesh source (the absolute path the last create or `reload_mesh` imported from, persisted as the manifest's `mesh.source`). Either is None when unknown. The Assets3D adapter rebases each receipt on its own sources, even when the run ends on another project, on none, or in another directory.
- **`jobs`.** `Job.id`, `.kind`, `.status`, `.progress`, `.message`, `.wait(timeout=None)`, `.cancel()`, `.receipt()`, `list()`, and `busy()` (the id of a queued or running job, or None). `receipt()` reports the job in the supervisor's terms (task phase2.3, decision 140): `{id, kind, status, progress, message, committed, stopped, cancel_requested, no_op}`. `committed` is what the job made durable (an export: `{generation, directory, revision}` once its generation is published); `stopped` is null for a success no cancel was asked of, otherwise `before_commit` or `after_commit`. A job is `succeeded` only when it ran to its end; one cancelled or failed after its commit point says so with its `committed`. An export checks for cancellation at every tile the CPU evaluator allocates, before every file and before every fixed-name folder.
- **`colormanagement`.** `Color(r, g, b, color_space=None)` keeps `value_raw` and the space as given. `GenericColorSpace`. `get_color_management()`.
- **`exception`.** Painter's `ProjectError`, `ServiceNotFoundError`, `ResourceNotFoundError` and `EditionContextException`, plus `UnsupportedInUzPainter(symbol, reason, alternative)`, `NotYetSupported`, `UnsupportedProcedural`, `BusyError(job_id)`, `StaleRevisionError(expected, current)`, `AmbiguousNameError(message, candidates)` (a `ValueError`) and the mesh-import classes (`MeshParseError`, `UnsupportedFormat`, `DuplicateMaterialNames`, `UVOutsideTile`, `ReleaseGap`). Each is also exported by `uzpainter`.
- **`logging`, `application`, `properties`.** Log lines go to the script's standard error; `version()` and `version_info()`; the `Property` type of procedural parameters, which no Phase 1 call returns.
- **Engine computations (`application`).** `enable_engine_computations(enable)`, `engine_computations_status()` and the context manager `disable_engine_computations()`. While computations are disabled the job worker starts no queued job: an export is deferred, not dropped, and `jobs.busy()` names it until it ran.
- **`event`.** The dispatcher thread (§6): `post(task)`, `flush()`, `drain()`, `hold()` / `release()`, `on_dispatcher_thread()` and `dispatcher_thread_id()`.
- **`diagnostics`** (`bind_diagnostics.cpp`, `diagnostics.{h,cpp}`; decision 136). Nothing here commits or changes the document.
  - `isolate(node, map)`, `contribution(node, map)`, `material_views(material)` and `region_stats(map, mask)` read the committed revision. They refuse inside an open `Transaction`, as the export does.
  - They evaluate on the CPU evaluator with the export's inputs and the entry points of its `diagnosticMap` sources, so each view equals the export of its source.
  - Each result names its source (decision 076) and the revision it read. A map is `{width, height, components, values}`, with `values` the float32 little-endian bytes, rows top first.
  - A view reading a channel whose template base is inferred is refused by the export's guard (decision 126; no shipped template has one since decision 169). The three single views raise `NotYetSupported`. `material_views` lists such a view in `refused` and returns the others.
  - `snapshot_layer_tree()` returns the layer tree of the committed revision (`uzp_core/document/layer_tree.h`). `diff_snapshots(before, after)` returns the nodes and stacks added, removed and modified, each change as a JSON pointer with its values.
- **Display** (`display.{h,cpp}`, `bind_display.cpp`; task phase2.1_preview-display-presets, decisions 038, 042 and 132). Only the fixed render pipeline exists: every setter accepts the pipeline's values and raises `UnsupportedInUzPainter` naming the setting, the accepted values and decision 038 for anything else, before any change. Each setter is one transaction and returns a `Result`.
  - `display`:
    - `get/set_environment_resource`: a project resource imported with `Usage.ENVIRONMENT`. `resource.import_project_resource` stores an OpenEXR equirectangular map as its unmodified bytes under its SHA-256; another file raises `ValueError`. A resource that is not an environment raises `ResourceNotFoundError`.
    - `get/set_color_lut_resource`: None only. Importing a `COLOR_LUT` is refused too.
    - `get/set_tone_mapping`: always raise, `RuntimeError` on a colour-managed project and `UnsupportedInUzPainter` on a Legacy one.
    - `ToneMappingFunction`, `CameraProjectionType`.
    - `Camera(_camera_id)` and `Camera.get_default_camera()`, with Painter's eight properties. A project has no camera until one is set; until then, reading or setting a property raises `NotYetSupported` (recording R-132-A). `field_of_view` and `focal_length` are set only in a whole record (R-132-B), and `aperture` accepts 0 only.
    - `camera()`, `set_camera(record)`, `camera_to_blender(record)`, `camera_from_blender(record)`: the standard's coordinate contract. Position maps `(x, y, z) → (x, −z, y)`, and the rotation `B @ Rx @ Ry @ Rz` becomes Blender's XYZ Euler angles on the canonical branch. Lens values pass unchanged.
  - `render.display`:
    - `state()`: the preset's fields, `parity` (the environment is the active preset's standard one) and the shader.
    - `preset()` and `presets()`: presets as `uzpainter/display-preset/1` JSON. The standard has two, `common` (the v2 block) and `ref_match` (v3).
    - `apply_preset(preset)`: validates the whole preset, then commits once. An environment the project does not store raises `ResourceNotFoundError`, with no substitute.
    - `set_exposure`, `set_opacity`, `set_blur`: 0 only. `set_rotation`, `set_shadows`, `set_background` (sRGB8): the active preset's values only.
    - A new project starts on `common` with no environment.
  - `render.shader`: `parameters()` and `set_parameters(dict)`. These are the default `open-pbr` instance's settings, read back under OCIO, under UzPainter's identifiers:
    - `diffuse_roughness_enabled`, `anisotropy_enabled`, `specular_ior` (IOR), `specular_color_enabled`, and `transmission_enabled`, `subsurface_enabled`, `coat_enabled`, `fuzz_enabled`, `thin_film_enabled` (each section's enable);
    - `emission_luminance`;
    - `displacement_enabled`, `displacement_source_channel`, `displacement_scale_unit`, `displacement_scale`;
    - `tessellation_mode`, `tessellation_subdivisions`;
    - `alpha_test_enabled`, `alpha_blending_enabled`, `double_sided`.

    `set_parameters` accepts these at their default values only.
- **Capture** (`capture.{h,cpp}`, bound in `bind_display.cpp`; task phase2.2_preview-capture, decision 148). `render.capture(path, mode, camera=None, size=None, samples=None, seed=None, preset=None, stack=None)` captures the committed revision and returns the receipt (`capture-receipt.schema.json`), which is also written as `<stem>.receipt.json`. Nothing commits.
  - `painter_viewport` is the preview pass rendered offscreen (needs `size`).
  - `base_color`, `channel:<name>` and `mask:<uid>` are texture-space files equal to the export.
  - `painter_iray` raises `PathTracerUnavailable`, a `NotYetSupported`, before anything else.
  - See `src/preview/PREVIEW.md`.
- **Later phases.** `baking` (phase3.5) is importable. Every call raises `NotYetSupported` naming the owner before anything changes.
- **`capabilities`.** `profile()` (`"painter-12.1-api-0.3.7"`), `manifest()` (the shipped `capabilities.json`) and `entry(symbol, context="any")` (§7).
- **Top level.** `Result`, `last_result()`, `Transaction(name)`.

## 3. Mutation contract (10 §5)

- **Handles.** A handle holds a persistent id and resolves it again on every call against the project the thread reads. A deleted node raises `ValueError` ("stale handle"). Handle classes have `__slots__ == ()` and no instance dictionary, so assigning an unknown attribute raises `AttributeError`. `Node.uid()` is the 64-bit id, stable across save and reopen.
- **Addressing.** Every operation addresses its texture set and stack explicitly, through a node, a `Stack` or an `InsertPosition`. The active stack is only the default of the calls that take a stack.
- **One call, one transaction.** Each setter or insert is one transaction submitted through the project store with a fresh idempotency key and the current revision as its precondition (`ProjectStore::Submit`, `core::Execute`).
  - The Phase 1 support check `evaluator::RequireSupported` runs on the working copy, so a release gap raises `NotYetSupported` before anything is committed.
  - A failing call commits nothing and raises the typed error of the call.
  - A call that waited for another thread's transaction raises `StaleRevisionError(expected, current)`.
  - Setters return a `Result`: `status` `committed` / `no_op` / `pending`, `revision`, the `created`, `modified`, `removed` and `hidden` node ids, the `imported` and `skipped` resource hashes, and `returned`. Inserts return the new handle. `last_result()` gives the thread's last result.
- **Native `Transaction`.** Inside `with uzpainter.Transaction():` the calls of the thread are applied to one working copy and reads see it. A clean exit commits one revision (`.result`); an exception commits nothing.
- **No reset on toggle (LAY-01).** Assigning `active_channels` replaces the set and keeps every source.
- **Channel contexts.** A content-stack node needs a channel: None raises `EditionContextException`. A mask-stack node takes None: a channel raises `ValueError`.
- **Stored values.** Floats are stored as float32, as Painter stores them, and colours keep their raw value and colour-space string (decision 105 §2). Inserts give Painter's effective defaults (decision 115): the names "Fill", "Folder", "Levels - Base color" (a content-stack levels effect, which affects BaseColor) and "Compare mask"; Height `LinearDodge` and Normal `NormalMapDetail` blending on a new content-stack fill, fill effect or group; BaseColor 0.8 and Height 0 working-space sources on a new content fill, its active channels empty. A mask-stack node keeps the plain defaults.
- **Threads (02 §4).** The bindings release the GIL around every call that can wait: the document lock, the store, a job. A call holds the document lock only while it edits the working copy, or for the length of a native `Transaction`. Another Python thread runs meanwhile.
- **Saving (decision 105 §1).** Commits are durable, and `close()` keeps them. A project created from a mesh is "Untitled" in a private temporary folder until `save_as`. `ProjectSaveMode.Full` compacts the file. Saving or closing while a job is queued or running raises `BusyError`.

## 4. `sync_stack` (LAY-07)

`layerstack.sync_stack(stack_json, masks_dir, stack=None, keep_visible=[], stack_key=None)` reads the Assets3D stack JSON (a dict, or a file, optionally under a dotted key) without changing it. In one transaction it:

1. imports the PNG images the stack names from `masks_dir`; bytes already stored under the name are skipped;
2. builds the root group named `title` detached, with groups and layers bottom to top as listed;
3. deletes the earlier root groups of that title;
4. attaches the new group at the top of the stack in one step;
5. hides every other visible root layer, unless its name starts with a keep-visible prefix. It never deletes them.

Every node it builds starts with the insert defaults of §3, as the script's inserted nodes do, so it builds the document `painter_layer_stack.py sync` builds through the facade on a Legacy project (decision 115). On an OCIO project, a layer's sRGB `base` on an sRGB8 BaseColor raises `NotYetSupported`, and nothing is committed: the facade stores Painter's measured decode there (decision 202), which the native module does not hold (decision 207).

The result's `returned["sync"]` lists the groups, layers, imported and skipped images, deleted and hidden nodes. The JSON fields and their channels are documented in `stack_sync.h`. The MCP `sync_stack` also names the imported entries `<resource_prefix><name>` in a `resource_group` (`SyncOptions`, decision 164); the API call keeps the image names.

## 5. Tests

`tests/python/test_pyapi_native.py` (CPU, every lane):

- set → get → save → reopen → get of every Phase 1 setter through fresh handles;
- LAY-01;
- `AttributeError`, stale handles, `__slots__`;
- every later-phase call raising `NotYetSupported` with an unchanged revision;
- `test_display_presets.py`: the preset round trip and the standard's values, the missing environment, the camera conversion, the refusals outside the fixed pipeline, tone mapping on an OCIO project, the facade's `display` symbols and the shipped environments' provenance (decision 132);
- failed calls, a script raising after two calls (its report names revision 3), raising and clean `Transaction`s, results;
- a waiting thread's `StaleRevisionError`;
- LAY-06 ambiguity, repeats and save/reopen;
- LAY-07;
- LAY-08;
- a second Python thread running while an export job is waited on;
- the export dry run, job errors and `BusyError`.

`tests/python/test_pyapi_diagnostics.py` (CPU) checks `diagnostics` against OpenEXR 32f exports of the same project:
- the isolated map equals the export with the node hidden by hand, and the revision and every visibility flag are unchanged;
- the contribution equals the float32 difference of the two exports;
- a seeded Roughness leak is detected and a clean fixture reports none;
- the statistics equal those recomputed from the exported map and mask;
- every view equals the export of its `diagnosticMap` source;
- decision 126 refuses per source;
- the snapshot diff reports exactly the seeded changes.

`tests/python/test_pyapi_tier0.py` compares the native-owned Tier 0 readbacks with the private goldens on the owner's machine (decision 106).

## 6. The dispatcher thread (phase1.21)

`dispatcher.{h,cpp}` is the Python dispatcher thread of `02-runtime-topology.md` §4. The facade delivers `substance_painter.event` events and its callbacks through it (`python/FACADE.md` §9).

- **Tasks.** `event.post(task)` queues a Python callable. The thread takes the GIL, calls the tasks in queue order and prints a task's error on the standard error. It never takes the document lock itself: a task that calls back into the API takes the lock inside that call, like any other thread.
- **`flush()`.** Returns once every task queued before the call has run, with the GIL released while it waits. A synchronous operation posts its event and flushes, so the handlers run on the dispatcher thread before the operation returns. On the dispatcher thread itself (a handler that starts such an operation), `flush()` runs the queued tasks inline.
- **`hold()` / `release()`.** An asynchronous operation in flight that will post later. `drain()` returns once the queue is empty and nothing is held. The host drains after the script returned, so deliveries of operations the script started outlive it.
- **Lifetime.** The thread starts with the first task and lives as long as the process.

Tests: `tests/python/test_pyapi_dispatcher.py` (every lane) and `tests/python/test_pyapi_lifecycle_tier0.py` (owner's machine). Local run report: `parity/reports/phase1/pyapi-dispatcher-lifecycle.md`.

## 7. The `run` host and the capability manifest (phase1.22)

`UzPainter.exe run <script.py> [args...] [--gpu-backend dx12|vulkan] [-- args...]` (`run.{h,cpp}`, decision 111):

- **Arguments.** `--gpu-backend` anywhere before `--` is the process's backend (dx12 by default). It is never passed to the script; what follows `--` is passed as given.
- **Run.** The host starts the interpreter and runs the script with `RunScript`. Its output stays captured until the dispatcher has drained, so the events and callbacks of operations it started are part of the run. It then prints one line `UZP_JSON:{status, result, stdout, stderr, error?, last_committed_revision, committed, gpu_backend}` and closes a project left open. The process ends without finalizing the interpreter.
- **Exit status.** 0 when the script ran to its end with a JSON `result`; 1 for a structured failure; 2 for a usage error (message on stderr, no JSON line); 3 when the interpreter did not start (`{"status": "host_error"}`).
- **GPU.** No Phase 1 Python call uses the GPU, so no device is created. The GPU calls are release gaps and refuse first; the first GPU call of phase2 creates the device and reports `gpu_backend_unavailable`.

`UzPainter.exe capabilities` (`capabilities.{h,cpp}`) prints `capabilities.json`, installed beside the executable, as one `UZP_JSON:` line. A missing or unreadable file is exit status 3. `uzpainter.capabilities` reads the same file.

Tests: `tests/python/test_pyapi_cli.py` (`UzPainter.exe` of a fresh `zig build painter`) and `tests/python/test_capability_conformance.py` (decision 112).
