# The `substance_painter` compatibility facade (`python/`)

Task `phase1.20_pyapi-facade` (child of `phase1.24_python-api-facade`, P1-PYAPI). It implements the facade of `docs/architecture/10-python-api.md` §0, §1, §3 and §4 under decisions 107 and 108.

- Tests: `tests/python/test_pyapi_facade.py` runs in every lane. `tests/python/test_pyapi_facade_tier0.py` runs on the owner's machine.
- Local run report: `parity/reports/phase1/pyapi-facade.md`.

## 1. Shape

| Package | Role |
|---|---|
| `substance_painter/` | Painter's documented modules. Each one only re-exports names, so a module holds documented symbols and nothing else. `__version__ = "0.3.7"` and `_version.py` give the API level (10 §4 Versions row). `_version` is the one private name. |
| `substance_painter_plugins/` | `path`, `plugins`, `start_plugin`, `close_plugin`, `is_plugin_started`, `reload_plugin`, `startup_module_names`, `plugin_module_names`, `load_startup_modules`, `close_all_plugins`, `update_sys_path`. They load non-UI `startup/`, `plugins/` and `modules/` folders (`uzpainter_facade/plugins.py`). |
| `uzpainter_facade/` | The implementation, pure Python over the native `uzpainter` (`src/python/PYAPI.md`): `state` (per-interpreter state, one transaction per call), `colour`, `nodes` (layerstack and source), `textureset`, `resource`, `project`, `export`, `levels`, `js`, `ui`, `event`, `plugins`. |

`zig build pyapi-tests` and `zig build painter` install the `.py` files into `bin/python/`. That folder is on the embedded interpreter's search path (`src/python/python313._pth`).

To type-check the facade, run this from `python/`:

```
python -m mypy --strict --ignore-missing-imports -p substance_painter -p substance_painter_plugins -p uzpainter_facade
```

The repository's mypy run cannot include `python/`. On its path, `substance_painter` would shadow Painter's package, which `tools/parity/recorder/painter_side.py` is checked against.

## 2. Surface

- The facade provides the documented symbols of the Phase 1 subset. It also provides the documented symbols whose native counterpart raises `NotYetSupported` or `UnsupportedProcedural`: `baking`, `display`, the smart and procedural inserts, `SourceSubstance` and the material sources.
- A documented symbol with neither is absent and raises `AttributeError`, so `hasattr` keeps working. The capability manifest (phase1.22) lists it as a release gap (decision 107 §1).
- `TextureSet`, `Stack` and `Channel` hold their native handle and resolve it on every call.
- A node holds its uid (`Node(uid)`, as Painter's constructor takes it).
- Projection and levels parameters are dataclasses, as Painter documents them.

## 3. Painter's quirks and inert state (10 §4)

Each quirk comes from a Tier 0 api-probe and is compared exactly by `test_pyapi_facade_tier0.py`.

- **Active channels.** Assigning `active_channels` resets the source of every channel in the new set to its default: BaseColor uniform 0.8 (working space), Height 0.
  - A channel whose default is unrecorded loses its native source. Reading it, or exporting a fill that has it active, raises `NotYetSupported`.
  - `set_source` on an inactive channel activates it without a reset.
  - The native API keeps the sources (LAY-01). Both behaviours are tested side by side.
- **New nodes.** A new fill holds the recorded default sources, and its active channels are empty. A new fill, fill effect or group blends Height with `LinearDodge` and Normal with `NormalMapDetail`.
- **Default names.** "Fill" and "Folder". A content-stack levels effect is "Levels - Base color" and affects BaseColor. A compare mask is "Compare mask".
- **Context errors** (Painter's classes and messages):
  - A content fill given None raises `EditionContextException` "Only valid in mono channel context".
  - A mask fill given a channel raises "Channel 0 isn't valid in this context". Its `active_channels` raises "Only valid in multi channel context", and its `source_mode` is None.
  - Blending or opacity of a mask node with a channel raises `ValueError`. Blending of a content node without a channel raises `ValueError`. A node without blending raises `ValueError`.
  - A second mask raises `ValueError`. `affected_channel` in a mask stack raises `ValueError`.
- **Insertion rules.** `ValueError` with Painter's messages: substack of a non-group, a layer in a content or mask stack, an effect at the top or above a layer, a layer above an effect, compare-mask and colour-selection effects outside a mask stack, an effect's content stack, and the mask of a layer that has none.
- **Saving.** A save drops the content effects of groups, which Painter does not keep through save and reopen.
- **`needs_saving()`.** It is also true after any edit call since the last save, including one that changed nothing: Painter reports the re-binding of the same mesh map as unsaved.
- **Inert state** (10 §3). Selection, selection type and UI mode live in `state.SESSION`, per open project, and are never saved.
  - `set_selected_nodes` and `set_selection_type` raise `RuntimeError` inside a `ScopedModification`, and `ValueError` for a node outside the active texture set.
  - Collapsed groups and the active stack are native state.
- **`ScopedModification(name)`** groups calls. Each call still commits its own revision, and an exception rolls nothing back. Evaluation runs only when an export asks for it, so there is no per-call invalidation to batch.

## 4. Colour (10 §4 Colour row; decision 107 §2-§3)

- **Profile.** Painter's Legacy mode is the one pinned profile: linear working space with sRGB I/O. The facade checks the declared configuration when it opens a project and before every export. Any other mode raises `NotYetSupported` before anything is evaluated.
- **Uniform colours.** A colour without a space is sRGB on an sRGB8 channel and Raw elsewhere.
  - Uniform colours are stored as float32 working-space values. The sRGB decode runs in float32: `((f32(v) + 0.055f) / 1.055f) ^ 2.4f`.
  - That formula is exact on 6 of the 7 recorded components. The 7th (70/255) is 2 ulp off: it is decision 107's named residual.
  - `Color` offers `convert`, `value`, `sRGB` and `working`. The four colour-space enums are the documented ones.
- **Bitmaps.** A bitmap takes Painter's recorded default space on bind:
  - sRGB for a colour image on BaseColor;
  - Data on the data channels and in masks;
  - DataSigned on Height;
  - NormalXYZLeft on Normal.

  The recorded lists of available spaces are those on sRGB8 channels and in masks. Any other case raises `NotYetSupported`, naming the defaults probe.

## 5. Resource ids (decision 107 §4)

- `ResourceID(context, name, version)`: the context is `project<N>`, the session's N-th project created or opened.
- The version is `<sha1>.image`. The facade computes the SHA-1 when it imports a file and keeps it in the project Metadata context `uzpainter.facade`, written in the same native transaction as the import.
- A binding keeps, for the session, the context of the identifier it was given. A reopened project reads back in its new context.

## 6. `js.evaluate` (10 §3; decision 107 §6)

- `evaluate` accepts one whitelisted `alg.*` expression with JSON-literal arguments and runs it as a typed native call. The table is in `uzpainter_facade/js.py`.
- `alg.shaders.*` raises `NotYetSupported` until phase2.3. So does `alg.mapexport.save*`, because no golden records a JavaScript export.
- Anything else raises `UnsupportedInUzPainter` before any native call. Wrong arguments to a whitelisted call raise `RuntimeError`.

## 7. Desktop-only symbols (10 §3)

These raise `UnsupportedInUzPainter(symbol, reason, alternative)`:
- the Qt members of `ui`;
- `Resource.show_in_ui`;
- `resource.show_resources_in_ui`;
- creating `event.GraphicalUserInterfaceStarted`.

## 8. Not here

These belong to `phase1.21_pyapi-dispatcher-lifecycle`:
- the asynchronous lifecycle, events, `is_busy`, `execute_when_not_busy` and the computation state;
- Painter's discard-on-close;
- the `create` arguments the native project does not take yet.
