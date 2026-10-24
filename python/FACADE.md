# The `substance_painter` compatibility facade (`python/`)

Task `phase1.20_pyapi-facade` (child of `phase1.24_python-api-facade`, P1-PYAPI). It implements the facade of `docs/architecture/10-python-api.md` §0, §1, §3 and §4 under decisions 107 and 108. Task `phase1.21_pyapi-dispatcher-lifecycle` adds Painter's asynchronous host (§9; decisions 109 and 110).

- Tests: `tests/python/test_pyapi_facade.py` and `test_pyapi_dispatcher.py` run in every lane. `tests/python/test_pyapi_facade_tier0.py` and `test_pyapi_lifecycle_tier0.py` run on the owner's machine.
- Local run reports: `parity/reports/phase1/pyapi-facade.md`, `parity/reports/phase1/pyapi-dispatcher-lifecycle.md`.

## 1. Shape

| Package | Role |
|---|---|
| `substance_painter/` | Painter's documented modules. Each one only re-exports names, so a module holds documented symbols and nothing else. `__version__ = "0.3.7"` and `_version.py` give the API level (10 §4 Versions row). `_version` is the one private name. |
| `substance_painter_plugins/` | `path`, `plugins`, `start_plugin`, `close_plugin`, `is_plugin_started`, `reload_plugin`, `startup_module_names`, `plugin_module_names`, `load_startup_modules`, `close_all_plugins`, `update_sys_path`. They load non-UI `startup/`, `plugins/` and `modules/` folders (`uzpainter_facade/plugins.py`). |
| `uzpainter_facade/` | The implementation, pure Python over the native `uzpainter` (`src/python/PYAPI.md`): `state` (per-interpreter state, one transaction per call), `host` (busy, edition and engine-computation state, §9), `event` (the event classes and the dispatcher), `colour`, `ocio_srgb` (Painter's measured OCIO sRGB decode, §4), `nodes` (layerstack and source), `textureset`, `baking` (the bake parameters), `resource`, `project`, `export`, `levels`, `display` (§10), `js`, `ui`, `async_utils`, `plugins`. |

`zig build pyapi-tests` and `zig build painter` install the `.py` files into `bin/python/`. That folder is on the embedded interpreter's search path (`src/python/python313._pth`).

To type-check the facade, run this from `python/`:

```
python -m mypy --strict --ignore-missing-imports -p substance_painter -p substance_painter_plugins -p uzpainter_facade
```

The repository's mypy run cannot include `python/`. On its path, `substance_painter` would shadow Painter's package, which `tools/parity/recorder/painter_side.py` is checked against.

## 2. Surface

- The facade provides the documented symbols of the Phase 1 subset. It also provides the documented symbols whose native counterpart raises `NotYetSupported` or `UnsupportedProcedural`: the link groups of `baking`, `display`, the smart and procedural inserts and the material sources.
- A documented symbol with neither is absent and raises `AttributeError`, so `hasattr` keeps working. The capability manifest (phase1.22) lists it as a release gap (decision 107 §1).
- `TextureSet`, `Stack` and `Channel` hold their native handle and resolve it on every call.
- `baking.BakingParameters` holds its native handle too (`src/python/PYAPI.md`, `baking`). `common()` and `baker(usage)` return the native `properties.Property` handles, so a `Property` is one class in both packages. `BakingParameters.set` is an edit call: the project then needs saving. Its refusals are decision 323's, each a `NotYetSupported` before any change. `tests/python/test_pyapi_baking.py` compares the defaults with the Tier 0 golden `tier0/defaults-templates/baking-defaults` on the owner's machine (phase3.1_baker-request-model item 3.1).
- A node holds its uid (`Node(uid)`, as Painter's constructor takes it).
- Projection and levels parameters are dataclasses, as Painter documents them.
- `SourceSubstance` wraps stored scalar snapshot fills. Parameter edits merge keys and require an exact stored signature; `active_output`, pinned UzPainter `resource_id` and explicit `resolution` are available. Missing default-resolution metadata is refused. Both APIs retain `pending-evidence` status for this surface; metadata, presets, image inputs and general procedural binding remain gaps. See `docs/procedural-snapshots.md`.
- `source.ResolutionMode` and the `ResolutionOverride` dataclass reproduce the admitted `tier0/api-probes/source-resolution-values` contract (46 readbacks, both recordings): legacy enum aliases and numeric construction, two power-of-two dimensions from 128 through 4096, constructor and assignment errors. Values retain their input list/tuple shape; mode and offset remain unvalidated as recorded. These standalone values do not evaluate procedural assets or establish automatic resolution and Filter assignment semantics. Evidence: `tests/python/test_pyapi_procedural_values.py`.

## 3. Painter's quirks and inert state (10 §4)

Each quirk comes from a Tier 0 api-probe and is compared exactly by `test_pyapi_facade_tier0.py`.

- **Active channels.** Assigning `active_channels` resets the source of every channel in the new set to its default, in the working space: BaseColor uniform 0.8, BaseMetalness 0, Height 0, Normal (0.5, 0.5, 1) and SpecularRoughness 0.3 (P20-A, `phase1-fill-channel-defaults`; decision 214).
  - A channel whose default is unrecorded (a channel outside the default template's five) loses its native source. Reading it, or exporting a fill that has it active, raises `NotYetSupported`.
  - `set_source` on an inactive channel activates it without a reset.
  - The native API keeps the sources (LAY-01). Both behaviours are tested side by side.
- **New nodes.** A new fill holds the recorded default sources, and its active channels are empty. A new fill, fill effect or group blends Height with `LinearDodge` and Normal with `NormalMapDetail`. The native inserts give these defaults themselves (decision 115); the facade adds nothing.
- **Default names.** "Fill" and "Folder". A content-stack levels effect is "Levels - Base color" and affects BaseColor. A compare mask is "Compare mask". These are the native defaults too.
- **Context errors** (Painter's classes and messages):
  - A content fill given None raises `EditionContextException` "Only valid in mono channel context".
  - A mask fill given a channel raises "Channel 0 isn't valid in this context". Its `active_channels` raises "Only valid in multi channel context", and its `source_mode` is None.
  - Blending or opacity of a mask node with a channel raises `ValueError`. Blending of a content node without a channel raises `ValueError`. A node without blending raises `ValueError`.
  - A second mask raises `ValueError`. `affected_channel` in a mask stack raises `ValueError`.
- **Insertion rules.** `ValueError` with Painter's messages: substack of a non-group, a layer in a content or mask stack, an effect at the top or above a layer, a layer above an effect, compare-mask and colour-selection effects outside a mask stack, an effect's content stack, and the mask of a layer that has none.
- **Saving.** A save drops the content effects of groups, which Painter does not keep through save and reopen.
- **`needs_saving()`.** It is also true after any edit call since the last save, including one that changed nothing: Painter reports the re-binding of the same mesh map as unsaved. The value edits `set_name`, `set_opacity`, `set_visible` and `set_blending_mode` made while the project is as saved form a run until another edit; the project is as saved again whenever each value the run changed reads back its saved value (`phase1-restored-values` s8-s28 and `phase1-save-modes` s15-s17, both recordings; refines decision 111 §6).
- **`get_default_export_path()`** returns UzPainter's own `<Documents>/UzPainter/export`, read from the Windows Documents Known Folder. It never creates the folder, and `Settings.export_path` does not change it. An export without `exportPath` still raises Painter's `ValueError`. It is a host policy, not Painter's path (decision 320).
- **Stale nodes.** `get_node_by_uid` of a deleted node raises Painter's `ValueError("This node is not valid")` (`phase1-delete-node`).
- **`update_layer_stack_resource`** returns the identifiers it replaced, as documented and recorded (`phase1-resource-update`). A mesh map bound to the replaced resource then binds the new one under its name, in the same transaction (`phase1-mesh-map-update`; decision 111 §7). A mesh map bound to another name of the same bytes keeps its binding, and replacing a resource by itself returns `[]` (`p22b-mesh-map-alias-update`; decision 336).
- **Inert state** (10 §3). Selection, selection type and UI mode live in `state.SESSION`, per open project, and are never saved.
  - `set_selected_nodes` and `set_selection_type` raise `RuntimeError` inside a `ScopedModification`, and `ValueError` for a node outside the active texture set.
  - Collapsed groups and the active stack are native state.
- **`ScopedModification(name)`** groups calls. Each call still commits its own revision, and an exception rolls nothing back. Evaluation runs only when an export asks for it, so there is no per-call invalidation to batch.

## 4. Colour (10 §4 Colour row; decisions 107 §2-§3, 202, 214 and 240)

- **Profile.** Two profiles are pinned: Painter's Legacy mode (linear working space with sRGB I/O) and OCIO with Painter's substance config, identified by its SHA-256 `15059d4b…` (the file is hashed at create, never parsed). The facade checks the declared configuration when it opens a project and before every export. Any other configuration raises `NotYetSupported` before anything is evaluated.
- **Uniform colours.** A colour without a space is sRGB on an sRGB8 channel and Raw elsewhere.
  - Uniform colours are stored as float32 working-space values, computed by the native rule every path uses: the facade calls it through the private `uzpainter.colormanagement._working_value` with its own profile and channel, and the native `set_source`, `set_color`, the MCP `source_set` and `sync_stack` call it directly (`python::WorkingColour`, decision 240). So the same colour stores the same value, or is refused with the same error, on every path. The facade keeps no decode of its own.
  - The Legacy sRGB decode runs in float32 (decision 214): `x * (1 / 12.92f)` up to 0.04045f, else `((x + 0.055f) * (1 / 1.055f)) ^ 2.4f`, with x = f32(v). Each reciprocal is the float32 quotient of 1 by the float32 constant, and the power of the float32 operands is rounded once to float32.
  - Only an sRGB8 channel that is not a user channel decodes (`nodes.decodes_colour`). Any other channel takes a uniform colour as given, whatever its space: Painter reads back and exports the value set on a user channel, RGB16 or sRGB8 (decision 115; the three `colour-ramps-*` goldens replay through the facade exactly, `test_pyapi_facade_tier0.py`).
  - It equals Painter's readback on all 448 components of P20-B (`phase1-srgb-uniform-decode-part1..4`: the 256 codes c / 255 and 192 random components, both recordings), and on decision 107's 70/255. Dividing by the constants instead of multiplying by their reciprocals misses 62 of the 448.
  - `Color` offers `convert`, `value`, `sRGB` and `working`. The four colour-space enums are the documented ones.
- **Bitmaps.** A bitmap takes Painter's recorded default space on bind, a grey image as a colour one (P20-A):
  - sRGB on BaseColor;
  - Data on the data channels and in masks;
  - DataSigned on Height;
  - NormalXYZLeft on Normal.

  The recorded lists of available spaces are those on sRGB8 channels (Raw, Working, sRGB and the two Legacy spaces), on user channels of the other formats, BaseMetalness, SpecularRoughness, Height and in masks (Raw, Data, DataSigned), and on Normal (Raw, NormalXYZRight, NormalXYZLeft). Any other case raises `NotYetSupported`, naming the defaults probe.
  - On a user channel that is not sRGB8 and in a mask, Painter offers Raw, Data and DataSigned and refuses sRGB with `ValueError: Invalid colorspace 'standard sRGB'`; the facade raises the same before any change, and the bitmap keeps Data (decision 174).
  - A `LegacyColorSpace` member is stored under its qualified name, so `get_color_space` returns the Legacy member that was set.
- **Under OCIO** (decision 202) only what Session O records is admitted. Everything else raises `NotYetSupported` before any change.
  - An sRGB uniform colour on a decoding channel reads Painter's measured working value of each float32 component (`uzpainter_facade/ocio_srgb.py`, generated into the native table the decode reads, decision 212): the 256 codes c / 255 and the 193 other recorded components. No analytic decode reproduces it: its error from the IEC decode is a pseudo-random ±5·10⁻⁷, also on the linear segment. The decode is per component (`export-ocio-encode` s0 and s6 equal the table).
  - Raw, Working and a colour without a space on a channel that does not decode are taken as given. An sRGB colour on such a channel, another OCIO space for a uniform colour and the encode of a working value to sRGB (`Color.sRGB`, `value`, `convert`) are not recorded.
  - A bitmap on BaseColor lists Raw, Working and sRGB, then the strings `Linear`, `sRGB`, `Rec709`, `Rec2020`, `ACES - ACEScg`, `Display P3`, `ACES sRGB` and `False Color`. A mask's mono source lists Raw, Data and DataSigned. A colour image on BaseColor defaults to sRGB and a mask source to Data. Other channels and a fill's reset default source are not recorded.
  - A bitmap whose image the evaluator does not record is refused when it is bound, with `NotYetSupported` from the native support check and nothing changed (decision 240). Session O records an 8-bit colour image on an sRGB8 channel and a 16-bit grey mask source, each at the texture set's size with the identity UV transform. So are a projection change and a resolution or channel change of its set that would break that use. Inside a `uzpainter.Transaction` these are checked once, on the state it commits, so a resize and a rebind to the new size go in either order.
  - **Export** (decision 190). The files are the native export's (`src/export/EXPORT.md`). Where an OCIO and a Legacy project of one stack store the same values, they write the same PNG 8 and OpenEXR files, and the OCIO PNG 16 of an sRGB8 BaseColor differs by one code on 73 of the 256 sRGB8 codes and on the empty BaseColor, as Painter's own files do (`export-ocio-encode` against `export-ocio-encode-legacy`, s3 and s7; B17 of `parity/reports/phase2/practical-e2e.md`). They store the same values for every recorded source but one: an 8-bit colour bitmap in Raw on an sRGB8 channel stores the image codes 176, 245, 247 and 254 one sRGB8 code lower under OCIO (decision 190 fact 3), so its PNG 8, PNG 16 and OpenEXR 32f files differ from Legacy's, as Painter's do (s4). A value of an sRGB-encoded channel other than those 256 codes and the empty BaseColor, a luma for example, raises `NotYetSupported` in a PNG of either depth before anything is written.
  - **Creation** (decision 207). `project.create` takes the mode from the environment at the call, as Painter documents. `OCIO` naming Painter's substance config (the file is hashed) creates an OCIO project with that hash, also when `PAINTER_ACE_CONFIG` is set. Any other OCIO configuration, and `PAINTER_ACE_CONFIG` alone, raise `NotYetSupported`; a configuration file that cannot be read raises `ProjectError`. Both come before anything is created. With neither variable set (or both empty) the project is Legacy. The variables are read at the call, not at start-up, because the pipeline's `painter_create.py` sets `OCIO` in-process just before `create`.

## 5. Resource ids (decision 107 §4)

- `ResourceID(context, name, version)`: the context is `project<N>`, the session's N-th project created or opened.
- The version is `<sha1>.image`. The facade computes the SHA-1 when it imports a file and keeps it in the project Metadata context `uzpainter.facade`, written in the same native transaction as the import.
- A binding keeps, for the session, the context of the identifier it was given. A reopened project reads back in its new context.

## 6. `js.evaluate` (10 §3; decision 107 §6)

- `evaluate` accepts one whitelisted `alg.*` expression with JSON-literal arguments and runs it as a typed native call. The table is in `uzpainter_facade/js.py`.
- `alg.shaders.*` raises `NotYetSupported`: Painter's shader instance ids and parameter keys are unrecorded (recording R-132-D). The shader is read through `uzpainter.render.shader` (decision 132). So does `alg.mapexport.save*`, because no golden records a JavaScript export.
- Anything else raises `UnsupportedInUzPainter` before any native call. Wrong arguments to a whitelisted call raise `RuntimeError`.

## 7. Desktop-only symbols (10 §3)

These raise `UnsupportedInUzPainter(symbol, reason, alternative)`:
- the Qt members of `ui`;
- `Resource.show_in_ui`;
- `resource.show_resources_in_ui`;
- creating `event.GraphicalUserInterfaceStarted`.

## 8. Not here

- `create(mesh_map_file_paths=...)` with a file whose name is not `<texture set>_<suffix>` for one of the seven suffixes recording P21-A binds (`project.MESH_MAP_SUFFIXES`), names no texture set or does not exist: unrecorded (decision 319). The seven are imported under their file names and bound to their usages.
- `create(template_file_path=...)` with a template not shipped with Painter 12.1: a custom template's content is a release gap. A shipped template is mapped by its file name to the installed template, which the project records (decision 116); a missing file raises `NotYetSupported` naming recording P24-A.

## 9. Painter's asynchronous host (phase1.21; decisions 109 and 110)

Each row comes from a Tier 0 recording and is compared exactly by `test_pyapi_lifecycle_tier0.py`. Handlers and facade callbacks run on the native dispatcher thread (`src/python/PYAPI.md` §6), never under the document lock. A transition changes the state first and then delivers its event, so each handler reads the state Painter's handler read.

| Operation | Events, with what a handler reads (open, edition, busy) | Returns |
|---|---|---|
| `create`, `open` | `BusyStatusChanged(1)` (F, F, T) → `BusyStatusChanged(0)` (T, F, F) → `ProjectCreated` / `ProjectOpened` (T, F, F) during the call, then `ProjectEditionEntered` (T, T, F) once the call returns, as Painter delivers it from its event loop (P21-F, P21-G). A pending entry is also delivered before the edition state changes again, so a `close` right after `create` sees it in edition (decision 319) | Once in edition. Painter's polls saw the project ready right after the call, 4 times out of 4 (`lifecycle-events`). `Settings.default_save_path` and `export_path` are taken and change nothing a documented call reads (P21-B, decision 319). |
| `close` | `ProjectEditionLeft` (T, F, F) → `BusyStatusChanged(1)` (T, F, T) → `ProjectAboutToClose` (T, F, T) → `ProjectClosed` (F, F, T) → `BusyStatusChanged(0)` (F, F, F) | After the events. What was not saved is discarded: the project returns to its last save, so reopening gives the saved content with nothing to save. |
| `save`, `save_as`, `save_as_copy` | `ProjectAboutToSave(file_path)` → `ProjectSaved`, delivered during the call | After the events. Refused with `ProjectError` while busy. |
| `export_project_textures` | `ExportTexturesAboutToStart` (not busy) → `BusyStatusChanged(1)` → `ExportTexturesEnded` (busy) → `BusyStatusChanged(0)`, all during the call (R10 `phase1-engine-computations` s13, decision 319) | After the events. |
| `reload_mesh` | After the call: `ProjectEditionLeft` → `BusyStatusChanged(1)` → `BusyStatusChanged(0)` → `ProjectEditionEntered`, then `loading_status_cb(ReloadMeshStatus.SUCCESS / ERROR)`. A missing file gives only `ERROR`. | At once (`phase1-reload-mesh`). |
| `execute_when_not_busy(cb)` | Idle: `cb()` during the call. Busy: right after `BusyStatusChanged(0)`, before anything else the operation delivers. | `phase1-execute-when-not-busy` s8 and s10. |
| `reload_modified_resources_async(filter)` | `ReloadResourcesStarted(filter)` during the call; `ReloadResourcesEnded(filter, reloaded, errors)` after it. Returns False while a reload runs. | True at once (`phase1-reload-resources`). |
| `enable_engine_computations`, `disable_engine_computations()` | `EngineComputationsStatusChanged(enabled)` on each change. While disabled, edits apply and `export_project_textures` still completes with `Success`, without waiting for computations to be enabled again; `is_busy()` stays false outside the export's own busy section (R10 s9-s16, decision 319). | After the event. |
| `insert_fill` (layer or effect), `insert_group`, `insert_levels_effect`, `set_name`, `delete_node`, `add_mask`, `remove_mask`, `set_blending_mode`, `set_opacity` (also when unchanged), `set_visible` (on a change) | `LayerStacksModelDataChanged`, during the call. `active_channels`, `set_source`, `set_mask_background`, `enable_mask`, `set_projection_mode`, `set_projection_parameters`, `affected_channel`, `SourceUniformColor.set_color`, `reset_source` and the `SourceBitmap` colour-space setters emit nothing, as recorded (P21-E, decision 319). Every other edit call is unrecorded and emits nothing. | — |

- **`is_busy()`** is true from the first `BusyStatusChanged(1)` to the last `BusyStatusChanged(0)`. Busy sections nest: a create, open or close, a mesh reload, an export.
- **`is_in_edition_state()`** is true from `ProjectEditionEntered` to `ProjectEditionLeft`, and false (not an error) while no project is open, as Painter answers.
- **`BusyStatusChanged.busy`** is `1` or `0`, as Painter delivers it (`busy_argument` of every recording).
- **Resource reload.** A resource is modified when the bytes of its origin match none of the versions its name holds. The reload imports a new version under the same name and leaves every binding as it was. The four `p22b-reload-order-*` controls compare all three independent Painter sessions, before and after reopen. In these controls, live aliases retain distinct origins; aliases restored with the same current version use their saved canonical origin. A chronological import history is stored in the same transaction as each new import, so repeated reloads report the latest version as `old`, independently of native hash ordering. `AllResourcesFilter` and `ProjectFilter` select that current version; explicit and used-resource filters retain their selected identifiers. The controls do not establish parity for new same-content aliases imported after reopen or outdated identifiers in explicit filters. For the multi-result outputs measured by decision 338, complete results and multiplicity are compared while their unstable internal order remains unclaimed; raw orders are preserved. Other outputs remain ordered comparisons.
- **Shelves.** `Shelves.add(name, path)` adds a folder of user files for the session. `add`, `Shelf.refresh()` and `Shelves.refresh_all()` crawl it on a worker thread: `ShelfCrawlingStarted` is delivered during the call, `ShelfCrawlingEnded` once the walk ends, and `is_crawling()` is true meanwhile (P21-D, decision 319). `application_shelf`, `user_shelf` (recording P21-D), `resources`, `import_resource` and `can_import_resources` (phase3.3_procedural-families) raise `NotYetSupported`.
- **Texture notifications.** `TextureStateEvent` follows committed changes to materialized document-channel DAGs. Open/close emit ADD/REMOVE on the dispatcher while the project is open and busy. Source changes, including successful no-op setters, invalidate dependent channels. UPDATE delivery coalesces per texture, pauses with engine computations and respects the configured period (default 2000 ms, minimum 500 ms). Rollback and rejected edits emit nothing. Lifecycle generations reject stale queued deliveries. Cache keys identify content and survive reopen; equality to Painter's keys is not claimed (decisions 297 and 332). The bounded native queue preserves structural changes; overflow or an unsupported materialized DAG reports an explicit observer error instead of a false REMOVE. Channels without visible contributing content need no evaluator base and emit no texture events; adding their metadata cannot break project close or observation of other channels.
- **Bakes** (`baking.bake_async`, `bake_selected_textures_async`; decision 355). Every refusal raises before any event, including the default configuration's bakers that no binding holds yet. Then `BakingProcessAboutToStart(stop_source)` → `BusyStatusChanged(1)` during the call → `BakingProcessProgress(progress)` at each change → `BakingProcessEnded(status)` (busy) → `BusyStatusChanged(0)`, on the dispatcher thread. This order follows the recorded export, not a bake recording: every symbol stays `pending-evidence`. Every usage is `pending-evidence`, so a bake ends `BakingStatus.Fail` with nothing bound (decision 001) and logs its cause.
- **Connectable, emitted later.** `CameraPropertiesChanged` (phase2.3_realtime-preview).
- **`async_utils.StopSource`**: `request_stop()` and `stop_requested()` over a state its operation shares. A bake's `request_stop()` cancels it at once and returns False once it ended.

## 10. Display (decisions 038, 042 and 132)

`substance_painter.display` keeps Painter's documented symbols over the native `uzpainter.display` (`src/python/PYAPI.md`, Display). It accepts only the fixed render pipeline.
- `get/set_environment_resource` take and return Painter-shaped `resource.ResourceID`s. The environment is a project resource imported with `Usage.ENVIRONMENT`: an OpenEXR equirectangular map, versioned `<sha1>.image` like a texture. Anything other than a `ResourceID` raises `TypeError`, as documented.
- `set_color_lut_resource(None)` is accepted, and `get_color_lut_resource()` is None. Any LUT raises `UnsupportedInUzPainter` naming decision 038.
- `get/set_tone_mapping` raise `UnsupportedInUzPainter` on a Legacy project. On a colour-managed project (an OCIO project the facade opens or creates, §4) the native call raises `RuntimeError`, as Painter documents.
- `Camera`, `CameraProjectionType` and `ToneMappingFunction` are the native ones. A project has no camera until one is set, and `field_of_view` and `focal_length` cannot be set one at a time (decision 132; recordings R-132-A and R-132-B).
