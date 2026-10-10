# 10 — Python API

Implements D2 and D9 (`05-resolution.md`). Requirements: INT-01, INT-02, INT-10, INT-20, INT-23, LAY-01, LAY-06, LAY-07, LAY-08, LAY-12, QG-03, ARC-03, ARC-13, ARC-14 (`docs/prd.md`). Painter facts: the public API documentation (`PAINTER\resources\python-doc\**\*.html`). The earlier inventory `docs/analysis/substance-parity/01-python-api-inventory.md`, `02-layer-stack-model.md` and `08-review-response.md` are quarantined in the approved-source index, `docs/approved-sources.md`, and are historical context only.

## 0. Provenance rule

The facade and the native API mirror the **documented API shape** — module and symbol names, signatures, enum members, documented semantics and documented errors — written from Painter's public API documentation (`PAINTER\resources\python-doc\**\*.html`, the same pages Adobe publishes online). Adobe's shipped `.py` sources are not consulted and nothing is copied from them (`docs/licensing-and-clean-room.md`). Undocumented behaviour is established only by observing Painter through that documented API (Tier 0 probes). The facade contains documented Painter symbols only; adaptations for calls the pipeline makes to unsupported or private Painter interfaces live in the separate UzmiGames pipeline adapter (§2) and are identified there as migrations.

## 1. Two packages, one core

| Package | Role |
|---|---|
| `uzpainter` | The native, typed API (pybind11 module compiled into the executable). Same module and class names as Painter wherever a Painter symbol exists (`uzpainter.project`, `.textureset`, `.layerstack`, `.source`, `.resource`, `.baking`, `.export`, `.display`, `.colormanagement`, `.event`, `.properties`, `.levels`, `.logging`, `.exception`, `.async_utils`, `.application`), plus UzPainter-only modules `.jobs`, `.render`, `.diagnostics`, `.capabilities`. Synchronous conveniences (`bake(ts).wait()`, `export(...)`) over the job engine and revision snapshots. |
| `substance_painter` | The compatibility facade (pure Python over `uzpainter`): Painter's observable behaviour — asynchronous lifecycle, events, readiness, computation state, quirks — so the Assets3D scripts run unchanged. `substance_painter_plugins` is provided for non-UI `startup/` and `plugins/` modules (`start_plugin`, `close_plugin`, `path`, `load_startup_modules`). |

CPython 3.13 (Painter 12.1 ships 3.13.9) with a private, vendored site-packages (pip is unsupported in the embeddable package). The facade reports `substance_painter.__version__ = "0.3.7"` (the API level whose symbols Painter 12.1.0 ships) and exposes the UzPainter version and the named compatibility profile `uzpainter.capabilities.profile() == "painter-12.1-api-0.3.7"`; feature detection by `hasattr` keeps working.

## 2. Hosting

Scripts run inside the worker's interpreter: `UzPainter.exe run script.py` (single process), the MCP `run_python` tool (registered only when the supervisor starts with `--allow-python`; trusted execution for the local operator, owner Q12; `11-mcp-server.md` §6), or the UzmiGames pipeline adapter. Every required operation is also reachable through typed MCP tools, so a deployment can run without `run_python`. The pipeline adapter is UzmiGames code, not part of the facade: it replaces `painter_mcp_client.py execute_python` with `run`, supplies, only to the scripts it runs, a UzmiGames-owned shim for the pipeline's private viewport-capture call (`_substance_painter.display.save_viewport(path, w, h, _)`) that calls the native `uzpainter.render.capture(mode=painter_viewport)` (always the current state, never stale), lists each such shim as a migration, and preserves the contract: the script assigns `result`, which is returned as JSON together with captured stdout and stderr; an uncaught exception is a structured failure with the traceback.

## 3. Capability manifest

Generated at build time from the Painter inventory plus UzPainter additions; shipped as `capabilities.json`, printed by `uzpainter capabilities`, exposed as the MCP resource `uzpainter://capabilities`. One entry per qualified symbol and per operation context:

```json
{"symbol": "substance_painter.layerstack.Node.set_blending_mode", "context": "content-stack|mask-stack",
 "status": "supported|desktop-only-omitted|release-gap", "since": "0.1.0", "tier_evidence": "T0-blend-modes",
 "notes": "mask context requires channel=None (ValueError otherwise)", "evidence": "PAINTER\\resources\\python-doc\\substance_painter\\layerstack\\navigation.html#substance_painter.layerstack.Node.set_blending_mode; T0-api-probes/mask-blend.json"}
```

Rules:
- `supported` requires Tier 0 evidence (set→get readback through a freshly resolved handle; persisted after save/reopen; output-affecting ones with golden comparison).
- `desktop-only-omitted` is justified per symbol by "changes no texture, render or script-visible state in Painter": the Qt members of `ui` (`show_main_window`, `get_main_window`, layouts, docks, menus, toolbars, actions, `delete_ui_element`), `Resource.show_in_ui`, `show_resources_in_ui`, `GraphicalUserInterfaceStarted`. Calling one raises `uzpainter.UnsupportedInUzPainter(symbol, reason, alternative)`.
- `release-gap` marks output-affecting Painter behaviour not yet implemented (paint layers and paint effects receiving bitmaps and projections until Phase 4, warp and UV-set-to-UV-set projections, UV-tile workflow, auto-unwrap, vector and font sources, material layering, USD scene export (absent from the documented export API), TIFF/PSD/WebP/J2K export, arbitrary `.sbsar` evaluation). Using one raises `uzpainter.NotYetSupported` before any mutation. Each open gap blocks release (G5, `roadmap.md`) unless an explicit owner scope decision covers it; milestones are named by the scope they prove (owner Q5).
- Brush strokes are out of scope (owner Q5): Painter's Python API does not expose strokes, so there is no stroke symbol to mirror and no stroke engine.
- Inert script context is kept as **state**, never an error: `layerstack.get/set_selected_nodes`, `get/set_selection_type`, `GroupLayerNode.is_collapsed/set_collapsed`, `textureset.get/set_active_stack`, `ui.get_current_mode/switch_to_mode/UIMode`, `ui.ApplicationMenu`. Readback returns what was set; nothing in evaluation or export reads them except where Painter does (the facade's `get_stack()` default resolves to the active stack, exactly as Painter).
- `js.evaluate(code)` accepts a documented whitelist of `alg.*` calls with JSON-literal arguments — `alg.version.painter`, `alg.project.isOpen()`, `alg.project.name()`, `alg.shaders.instances()`, `alg.shaders.parameters(id)`, `alg.shaders.setParameters(id, params)`, `alg.shaders.updateShaderInstance(id)`, `alg.mapexport.*` (`save`, `saveChannelMap`, `saveMeshMap`, `saveConvertedMap`, identifiers), `alg.project.saveAndClose()` — parsed into typed calls; any other expression raises `UnsupportedInUzPainter` before mutation. The native equivalents are `uzpainter.render.shader.*` and `uzpainter.export.*`.

## 4. Facade behaviour (Painter's observable contract)

| Behaviour | Facade rule |
|---|---|
| Lifecycle | `project.create/open` return immediately; loading runs on the engine thread; `project.is_busy()` is true meanwhile; events in order `ProjectOpened`/`ProjectCreated` → `ProjectEditionEntered` (only when evaluation is ready); `ProjectAboutToClose` → `ProjectClosed`; `ProjectAboutToSave(path)` → `ProjectSaved`. `is_in_edition_state()` becomes true with `ProjectEditionEntered`, never before. |
| Events | `event.DISPATCHER.connect/connect_strong/disconnect` with all 27 event classes; dispatch on the Python dispatcher thread after the committed transition; delivered even if the script that started the operation returned; `execute_when_not_busy(cb)` runs on that thread when busy clears. |
| Bake | `bake_async`/`bake_selected_textures_async → StopSource`; `BakingProcessAboutToStart/Progress/Ended`; `StopSource.request_stop/stop_requested`. |
| Mesh reload | `reload_mesh(path, settings, cb)` calls `cb(ReloadMeshStatus)` on the dispatcher thread when done (callback, not event — as Painter). |
| Resources | `reload_modified_resources_async` → `ReloadResourcesStarted/Ended`; shelf crawling → `ShelfCrawlingStarted/Ended` (shelves are folders of UzPainter assets and user files). |
| Computation state | `application.enable_engine_computations/disable_engine_computations/engine_computations_status` keep an explicit state: while disabled, evaluation requests are deferred, `is_busy()` reflects the deferred backlog on re-enable, and `EngineComputationsStatusChanged` fires. Not a no-op. |
| Quirks that change output | Reproduced because a replayed instruction sequence depends on them: assigning `active_channels` after `set_source` resets the fill's sources to the channel default (`A3D\Docs\Pipeline\Licoes\pintura-fill-ordem-dos-canais.md`); mask-stack contexts require `None` for channel and source mode; `set_source(None, …)` on a multichannel fill raises `EditionContextException`; `insert_*` position rules raise as Painter. Each quirk is a Tier 0 golden. The native `uzpainter` API does not reset values on toggle (LAY-01); the two behaviours are documented side by side. |
| Colour | `colormanagement.Color(r,g,b, color_space)` with `GenericColorSpace`, `LegacyColorSpace`, `DataColorSpace`, `NormalColorSpace` and the OCIO string form; a colour without a space is sRGB on colour-managed channels and Raw otherwise. The facade preserves the project's declared colour-management mode, working space, input rules and display/view transform. Each supported configuration is pinned and tested with permitted public specifications and private oracle outputs; linear working space with sRGB I/O (the Assets3D contract, PRJ-05) is the named default profile, not a rewrite of other configurations. An unsupported configuration fails explicitly before evaluation; recording a configuration variable (`OCIO`, `PAINTER_ACE_CONFIG`) does not make it supported. |
| Versions | `_version.py` reports 0.3.7; `application.version()` returns the UzPainter version string; `application.version_info()` the tuple. |
| Private Painter symbols | Not provided: the facade contains documented symbols only, and a private name is absent like any unknown attribute. The pipeline's one private call is served by the UzmiGames pipeline adapter's shim (§2). |

## 5. Mutation contract (both packages)

- Handles are thin objects with `__slots__`; assigning an unknown attribute raises `AttributeError` (the community bridge's false success on `PaintLayerNode.active_channels` cannot recur — `08-review-response.md` F01, historical context).
- Every setter has a getter; readback goes through a freshly resolved handle (`layerstack.get_node_by_uid`); tests assert set → get → save → reopen → get.
- Every operation takes an explicit `(texture_set, stack)` address; the active stack is only a default.
- One API call = one transaction (`03-project-model.md` §6); composite operations attach on success only; results enumerate created/modified/hidden ids and imported/skipped resources. A failed call leaves that mutation unapplied. A script that raises after earlier calls keeps those calls committed; its error receipt reports the last committed revision and the partial changes. Atomic multi-call execution exists only through the native `Transaction` (§7); the facade's documented grouped-modification context (`layerstack.ScopedModification`) groups calls but is not an atomic commit and rolls nothing back on an exception.
- Errors: `ProjectError`, `ServiceNotFoundError`, `ResourceNotFoundError`, `ValueError`, `EditionContextException`, `RuntimeError` where Painter raises them; `UnsupportedInUzPainter`, `NotYetSupported`, `UnsupportedProcedural`, `BusyError(job_id)`, `StaleRevisionError(expected, current)` as UzPainter additions. No failure returns an empty success.
- Node identity: 64-bit ids persisted in the project; `Node.uid()` returns it; a stale handle (deleted node) raises `ValueError` as Painter.

## 6. The three pipeline scripts

`A3D\Docs\Pipeline\Retopologia\cajado-v10\painter_create.py`, `painter_export.py` and `A3D\Docs\Pipeline\Pintura\painter_layer_stack.py` (`sync`, `smart`, `capture`, `run`) use only supported symbols, apart from the private viewport-capture call served by the adapter's shim (§2) (`docs/analysis/assets3d-pipeline/02-painter-usage.md` §4; checked symbol by symbol in `docs/analysis/architecture-discussion/01-claude-proposal.md` D9, historical context; the facade check re-runs against the public API documentation). These scripts are UzmiGames code and may be read freely. Required host-side changes: the transport (`painter_mcp_client.py execute_python` → `UzPainter.exe run`), absolute paths unchanged. Resource names in `smart` configs resolve through the internal compatibility alias table (`05-procedural-content.md`; CLR-06, decision 002). The tunic's per-layer overrides (`F03 → M_piping_lining_v9`) are expressed as explicit bindings, never a global filename replacement (LAY-07, LAY-13).

Behaviour the scripts rely on, tested directly:
- **Name addressing (LAY-06):** name-addressed operations are idempotent within an explicit project/set/stack/parent scope; an ambiguous match fails before mutation; repeating the same named operation creates no duplicate node. Tests: ambiguous names, repeated operations, save/reopen.
- **Stack sync (LAY-07):** `sync` loads the existing stack JSON unedited and rebuilds only the named group; other root groups are hidden, never deleted, unless their names match the explicit keep-visible prefixes (`--keep-visible`; `keep_visible` in the MCP `sync_stack` tool). Tests: unrelated roots and resources survive, and only the addressed group is rebuilt.

## 7. Native additions (`uzpainter` only)

`uzpainter.jobs` (`Job.id/status/progress/wait/cancel`, `list()`), `uzpainter.render` (`shader.parameters/set_parameters`, `display.set_exposure/rotation/opacity/blur/shadows/background`, `capture(...)` with the modes of `07-preview-and-render-parity.md` §5, including the parity mode `painter_iray`), `uzpainter.diagnostics` (`isolate`, `contribution`, `material_views`, `region_stats`), `uzpainter.project.dump_recipe()`, `uzpainter.project.revision()`, `uzpainter.capabilities`, typed `Transaction` context manager (atomic multi-call), `uzpainter.export.plan(config)` (dry run returning the typed plan).
