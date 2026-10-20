# 297. P22-B for the host modules: four requests exercise 64 pending symbols, and 19 take another evidence route

**Status**: accepted
**Date**: 2026-10-19
**Related Tasks**: phase1.24_python-api-facade, phase3.5_embree-bakers, phase2.1_preview-display-presets, phase2.3_realtime-preview

## Context

Decision 189 §3 split P22-B by module into `phase1.24_python-api-facade` item 3.4. This decision covers the host modules: event, resource, ui, substance_painter_plugins, logging, application, async_utils, exception, display and js. Decisions 295 and 296 cover the other modules.

Measured on main 32621fc:

- `tools/capabilities/painter-api-inventory.json` has 83 `pending-evidence` symbols in these modules whose notes named P22-B, once decision 188's 16 (decision 189 §2) are set aside: event 16, resource 15, ui 14, substance_painter_plugins 12, logging 11, application 4, async_utils 4, exception 4, js 2 and display 1. The display module is the only display symbol left: the other display members belong to R-132-D (phase2.1).
- Decision 189 listed these four as possibly unsafe: plugin start, close and reload; UI menus; logging; `ExportStatus.Cancelled` and `Warning`. The two export statuses are decision 295's.

Facts that shaped the probes (A-PYDOC, the recorder, the facade):

- `baking.bake_async` is a release gap. Only it produces the three `BakingProcess*` events and an `async_utils.StopSource`. In Painter, `StopSource` is built from a private object, so a script cannot make one.
- `ui.ApplicationMenu` is taken only by `ui.add_action(menu, QAction)`. That call needs a Qt action, edits Painter's menus, and is `desktop-only-omitted` in UzPainter.
- `exception.ServiceNotFoundError` is documented as raised while a service has not started yet.
- `substance_painter_plugins.load_startup_modules()` and `close_all_plugins()` act on every plugin of the installation. `start_plugin`, `close_plugin`, `reload_plugin` and `is_plugin_started` act on the module they are given.
- `resource.AllResourcesFilter` reloads the modified resources of every shelf, the session and the project.
- The recorder's Iray procedure already switches `ui.switch_to_mode` to Visualisation in recording sessions (`painter_side.switch_mode`).
- `TextureStateEvent.set_cache_key_invalidation_throttling_period` is global to the session and refuses less than 500 ms. Its getter is documented. UzPainter emits `TextureStateEvent` only from phase2.3, and its getter is a release gap until a script sets the period.
- The recorder's provenance check and `golden-public.json` accepted only `substance_painter.*` names. The documented `substance_painter_plugins` package (python-doc `plugins/substance_painter_plugins.html`) was outside both.
- SUP-012: the python-doc labels `TextureSet.name` a property (`name: str`), and `original_name` and `description` too. Its own examples call `name()`, and so do the three Assets3D pipeline scripts that Painter 12.1.5 ran unchanged for the Wand golden. The label does not settle the call form.

**Model panel** (one round: cx/gpt-6-astra and xai/grok-4.5; kimi/kimi-k3 returned HTTP 503 twice, as in decision 112):

- C1, a throwaway plugin package under the run's private directory makes the module-level plugin calls a safe probe: AGREE (Grok), PARTLY (GPT: restore `path`, `sys.path` and the environment, and forget the imports). Adopted with GPT's restorations (§1).
- C2, probe `load_startup_modules` and `close_all_plugins` last in their session: DISAGREE (GPT: closing the session does not undo the hooks' file writes or other effects), PARTLY (Grok: prefer no recording). Rejected. They take route B (§3).
- C3, `switch_to_mode` Baking, Visualisation and Edition, each read back: DISAGREE (GPT: Iray depends on renderer availability and asynchronous work), AGREE (Grok). Adopted. The Iray recorder already makes the same switch in recording sessions. The probe reads the starting mode first and ends in Edition, the mode every probe needs. A switch that raises is recorded, not refused.
- C4, `ApplicationMenu` and its members take no recording: AGREE (Grok), PARTLY (GPT: reading the members needs no menu change). Adopted. A read is an attribute access, not a call, so a replay trace could not count it (decision 112 §1).
- C5, `ServiceNotFoundError` takes route B: AGREE (Grok), PARTLY (GPT). Adopted.
- C6, the baking events and `async_utils` go to the bakers: AGREE ×2.
- C7, logging is a safe probe: AGREE ×2.
- C8, `AllResourcesFilter` takes no recording, and the five project, session and probe-shelf filters are probed: AGREE (Grok), PARTLY (GPT: a project-used resource may sit on an owner shelf). Adopted. The project here uses only the probe's own imports, the probe shelf and the template's starter assets, and the starter-assets shelf is read-only.
- C9, a `ReloadedResourceError` probe through a corrupted staged copy: AGREE (Grok), PARTLY (GPT: corrupt a dedicated copy, and count only an observed error). Adopted: the copy is its own input (`checker-reload`).
- C10, no new manifest status: AGREE ×2.
- C11, texture states logged per dispatch and compared as distinct sets: PARTLY (Grok: record the amendment), DISAGREE (GPT: it needs an explicit decision 112 amendment, not a replay-only normalisation, and close and open do not prove ADD and REMOVE). Adopted as amendment §3.3. An unobserved member takes route B.
- C12, the throttling probe restores the period: AGREE (Grok), PARTLY (GPT: only if a getter exists; it does). Adopted.
- C13, a strong connection to `Event`, with the trace counting a connected class that received an event: AGREE (Grok), PARTLY (GPT: check delivery through that very connection). Adopted as amendment §3.4.
- C14, strong callbacks are disconnected at the end of every golden, failures included: AGREE (Grok), PARTLY (GPT). Adopted: `probe_finish` runs in the host's `finally`.

## Decision

### 1. Vocabulary (`HOST_*` in `painter_probes.py`; `parity/RECORDER.md` §9)

- Every call is written out (provenance rule 4). The host reads `HOST_EDIT_CALLS`, `HOST_GETTER_CALLS` and `HOST_VALUE_ARGS` beside decision 295's `P295_*`. `edit()`, `read()` and `is_read()` each hand the host calls to `host_edit` and `host_read`.
- Getters: `application.version` and `version_info`, the six logging severities, `js.evaluate` (`code`), `ui.get_current_mode`, `list_project_resources`, `ResourceID.from_project` and `from_url`, and the plugin `path`, `plugin_module_names`, `startup_module_names`, `is_plugin_started` and `plugins`.
- Edits: `logging.info`, `warning`, `error` and `log`, `ui.switch_to_mode`, `Dispatcher.connect_strong` (`Event` and `TextureStateEvent` can be named too), `set_cache_key_invalidation_throttling_period`, `Shelves.refresh_all` and `remove`, the plugin `path` with `folder`, `update_sys_path`, `start_plugin`, `close_plugin` and `reload_plugin`.
- Also: `import_project_resource` takes `COLOR_LUT`, `GENERATOR` and `SMART_MATERIAL`, and a reload takes `ShelvesListFilter`.
- Plugins: the host writes the plugin root once per run, under the run's private directory. It holds `plugins/uzp_probe_plugin.py` and `startup/uzp_probe_startup.py`, whose import and hooks append to the run's `hooks.log` in that root (its path is written into each module, amendment §4.7). Only the probe's own modules and folders are recorded: the probe records no installation or user path.
- At the end of a golden, `probe_finish` disconnects the strong callbacks and restores the throttling period it read before the first set. `probe_cleanup` closes and forgets the probe modules, and removes their root from `plugins.path` and their folders from `sys.path`.
- `provenance.py` and both golden schemas now accept `substance_painter_plugins.*`. Its nine documented members joined `documented_symbols.json` with the other new symbols. The five `TextureStateEvent` constructor fields joined the inventory as `release-gap`, like `BusyStatusChanged.busy` (decision 188 §4).
- SUP-012: `TextureSet.from_name`, `get_active_stack`, `original_name` and `description` record the call form as facts (`callable`, `is_str`). The value is read through the form that works, and for a non-callable member the outcome of calling it is recorded too. `location()`, `all_texture_sets` and `Stack.name()` keep `name()`. The fakes model `name` as callable, the form Painter ran. Decision 295's texture-set test now requires readbacks that succeed. A caught `TypeError` no longer passes as a readback.

### 2. Requests (Legacy; `requests/tier0/api-probes/`, recording pending) and the symbols each exercises

- **`p22b-host-application`** (22): `application.version`, `version_info`; `logging` (module), `INFO`, `WARNING`, `ERROR`, `DBG_INFO`, `DBG_WARNING`, `DBG_ERROR`, `info`, `warning`, `error`, `log`; `js` (module), `js.evaluate` (six read-only expressions); `ui` (module), `UIMode`, `UIMode.Edition`, `Visualisation`, `Baking`, `get_current_mode`, `switch_to_mode`.
- **`p22b-host-events`** (11): `Dispatcher.connect_strong` and `DISPATCHER.connect_strong`; `Event`; `EngineComputationsStatusChanged`; `application.enable_engine_computations`, `disable_engine_computations`; `TextureStateEvent.set_cache_key_invalidation_throttling_period`; `TextureStateEventAction` and its `ADD`, `UPDATE` and `REMOVE` (those dispatched).
- **`p22b-host-resources`** (21): list_project_resources; ResourceID.from_project and from_url; Shelves.refresh_all and remove; reload_modified_resources_async with SessionFilter, ProjectFilter, ResourcesUsedByProjectFilter, ResourcesListFilter and ShelvesListFilter; ReloadResourcesStarted, ReloadResourcesEnded, ReloadedResourceResult, ReloadedResourceError; Usage.COLOR_LUT, GENERATOR, SMART_MATERIAL; exception (module), ProjectError (`Shelves.remove` with a project open, `list_project_resources` with none), ResourceNotFoundError (`set_environment_resource` of a missing id).
- **`p22b-host-plugins`** (10): substance_painter_plugins (module), path, update_sys_path, plugin_module_names, startup_module_names, start_plugin, is_plugin_started, plugins, reload_plugin, close_plugin.
- `phase1-engine-computations`, admitted by decision 180, also exercises the engine calls and their event. Its replay is not among the traced ones yet. `phase1-reload-resources` exercises two of the filters, but decision 110's residual excludes them from its trace (`test_pyapi_lifecycle_tier0.py`). The new requests make these symbols independent of both.
- Every symbol stays `pending-evidence` until its request is recorded, admitted, and its replay joins the traced Tier 0 tests (decision 112 §1). `tests/parity/recorder/test_api_probes_p22b_d297.py` checks the coverage both ways. It checks that every description names its symbols, and it records each request `r1`/`r2` against the fake Painter.

### 3. Amendments to decision 112

1. **§3, the P22-B owner.** P22-B is the requests of decisions 295, 296 and 297, not one recording (decision 189 §1). A routed symbol's notes name its route and owner instead of P22-B.
2. **§3, other evidence routes for 19 symbols.** Each stays `pending-evidence`, and none becomes `supported` without a compared replay:
   - **Route A, the owner of the producing call:** BakingProcessAboutToStart, BakingProcessProgress, BakingProcessEnded, async_utils, StopSource, request_stop and stop_requested. Only `bake_async` produces them, and it is a release gap. They are settled by the bake probe that `phase3.5_embree-bakers` records once `bake_async` is supported.
   - **Route B, no safe recording:**
     - `ApplicationMenu` and its six members (File, Edit, Mode, Window, Viewport, Help): the only consumer edits Painter's menus with a Qt action, and is desktop-only.
     - `ServiceNotFoundError`: it is raised only while services start.
     - `load_startup_modules` and `close_all_plugins`: they act on every plugin of the owner's installation (panel C2).
     - `AllResourcesFilter`: it re-imports modified resources of every owner shelf.

     The manifest conformance test keeps them present. G5's "explicit owner scope decision" (roadmap) closes them, unless a later safe probe is found.
   - **Route C, through members:** the display module counts through decision 188's display requests (decision 112 §2).
3. **§1, texture-state dispatches.** A `TextureStateEvent` output is compared as the set of distinct (action, channel type) pairs of each step. Its dispatch count follows throttled asynchronous computation. Every dispatch stays in the record. A `TextureStateEventAction` member that `p22b-host-events` does not show takes route B.
4. **§1, connected event classes.** An event class passed to `Dispatcher.connect` or `connect_strong` counts as exercised when that very connection received at least one event in a compared output. This is how `Event`, the base class, can be evidenced. If Painter delivers nothing to a base-class connection, `Event` takes route B.

### 4. Amendment (SUP-016, SUP-017, 2026-10-19): isolation and cleanup of the host probes

The Codex supervisor found that the host probes could act on the owner's state and could publish a golden after a failed restoration. Their recordings were on hold until this amendment.

1. **A collision refuses the recording before any change (SUP-016).** Before the project is created, `probe_preflight` checks the job's names. A shelf the job adds must not exist yet. A probe plugin module (`uzp_probe_plugin`, `uzp_probe_startup`) must not be in `sys.modules`, findable by the import system, or present in a folder of an existing plugin root. A collision fails the recorder with `ProbeGuardError`. It is never recorded as a step outcome: `probe_step` re-raises that error instead of capturing it.
2. **Shelves by run-owned identity.** A shelf the run added is recorded with its name and folder. `Shelves.remove` and a `ShelvesListFilter` reload accept only that shelf. A name the run did not add, or a shelf of that name in another folder, is refused before the call. `Shelves.add` refuses a name that exists already. A remove of the run's shelf after it is gone still goes to Painter, because that answer is the evidence of step 28.
3. **Plugin modules by origin.** Before each import, start, reload, close or `is_plugin_started` of a probe module, its origin must be `plugins/` or `startup/` under the run's one plugin root. The module of that name in `sys.modules` must be the one the run imported. Cleanup drops a `sys.modules` entry only while it is still the run's module, and removes the root from `plugins.path` only if the run appended it. Other `sys.path` entries stay. The run sets no environment variable (§4.7).
4. **Old state is read before any change (SUP-017).** The throttling period is read before the first set of a golden. If that read fails, the set is refused with `ProbeGuardError` and nothing changes.
5. **Every cleanup stage runs, and a failure blocks publication.** `probe_finish` and `probe_cleanup` run each stage whatever an earlier one did, and list the stages that failed in `cleanup_failures`. The stages are: re-enabling engine computations, each event disconnect, each strong disconnect, the throttling restore (confirmed by reading it back), each shelf removal (confirmed by looking again), each plugin module, the paths and the environment value. A stage that failed keeps its snapshot or ownership record, so a later finish can still restore it. The host runs `probe_finish`, `close_project` and `probe_cleanup` independently. Any failure raises `CleanupFailed`, and no run is written to the inbox, so nothing can be admitted. If the recording had failed already, that error is the cause of `CleanupFailed`, and both messages are reported.
6. `tests/parity/recorder/test_api_probes_p22b_d297.py` covers each case against the fake: a shelf of the probe's name that exists already, a removal or reload naming a shelf the run did not add, a shelf replaced under the run's name, a module of the probe's name already imported, a shadowing file on the path before and during the run, a hook-log value that existed already, a throttling getter that raises, a disconnect that raises after a successful set, and a restore that raises (with and without an earlier recording error).
7. **SUP-028, three residual gaps.** (a) The host runs each of `probe_finish`, `close_project` and `probe_cleanup` whatever the earlier one raised, a transport error (OSError, TimeoutError) or a malformed or undecodable reply included; every failure is listed in `CleanupFailed`, which keeps an earlier recording error as its cause. (b) The probe modules no longer find their hook log through `UZP_PROBE_PLUGIN_LOG`: the host writes the run's `hooks.log` path into each module, and the run sets no environment variable. A module kept for a retried close therefore still logs to the run's own file, and an owner's earlier value of that variable is never read, changed or written to. (c) The origin check asks each `sys.meta_path` finder afresh, as an import or a reload does, without executing anything. `importlib.util.find_spec` returned a loaded module's cached spec, so a folder put ahead on `sys.path` after the first import could be reloaded. Tests: a transport failure or malformed reply at the first stage with both later stages run, a close that fails then succeeds at a retry with an owner's log as a sentinel, and a shadowing folder inserted between start and reload, with no foreign import or hook.

## Alternatives Considered

- **Probe `load_startup_modules` and `close_all_plugins` last in a session.** Rejected by panel C2.
- **Read `ApplicationMenu` members as a probe.** Rejected: an attribute read is not a call the trace can count.
- **One generic request for the whole group.** Rejected, as in decision 189 C3: each request names the symbols it exercises.
- **Read `TextureSet.name` as the documented property (SUP-012, first reading).** Rejected. Painter ran `name()` for the Wand golden, so the probe records the form instead of assuming one.

## Consequences

Editorial clarification: item 3.4 is the authoring work specified by decision 189 section 3. Its completion does not settle any recording or capability: recording, admission and the compared replays remain mandatory under item 4.1 and decision 112.

- The next Painter batch records four more Legacy requests (`parity/RECORDER.md` §11.4). Report the recording if it shows no ADD or REMOVE texture state, or no `ReloadedResourceError`.
- The replay owner (item 4.1 acceptance) adds the four replays, trace amendments §3.3 and §3.4, and a normalisation of the plugin outputs if UzPainter's paths differ.
- Decision 295's `p22b-textureset-texture-set` outputs change shape (value plus form facts). It is unrecorded, so no record is invalidated.

*Clean-room note (2026-10-19, decision 304): the symbol lists of the `p22b-host-application` and `p22b-host-events` requests were marked as code for clean-room hygiene; no wording or reasoning changed.*
