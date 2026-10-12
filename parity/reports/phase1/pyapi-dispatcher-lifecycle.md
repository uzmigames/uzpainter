# `phase1.21_pyapi-dispatcher-lifecycle`: local run on the owner's machine

This task is a child of `phase1.24_python-api-facade` (P1-PYAPI; `docs/architecture/10-python-api.md` §4, `02-runtime-topology.md` §4; OWN-04, ARC-13, INT-01, INT-05). Under decision 028 its Tier 0 comparison runs locally against the private oracle store. This report is its evidence for `phase1.24_python-api-facade`.

- Run on 2026-10-12, branch `wt/phase1.21-dispatcher`, on main `21f35d8`, current envelope `painter-12.1.5_js-api.1.1.20`.
- Decisions 109 and 110. Implementation: `src/python/dispatcher.{h,cpp}` (`src/python/PYAPI.md` §6) and `python/` (`python/FACADE.md` §9).

## Result

### `tests/python/test_pyapi_lifecycle_tier0.py` (item 3.1): 5 of 5 pass

The recorder's own Painter-side code runs inside UzPainter's interpreter against the facade, exactly as the recorder drives Painter. Every event a handler logged is compared with the state that handler read (open, edition, busy), its argument and the states polled after each call.

| Golden | Exact | Excluded (reason) |
|---|---|---|
| `lifecycle-events` | All 4 recordings: create, save_as, close, open, save, close. Every event, handler state, argument (`busy_argument` 1/0, `file_path_argument`) and polled state. | — |
| `phase1-save-modes` | Every step's events in both recordings. `ProjectAboutToSave(copy.spp / main.spp)` → `ProjectSaved` during `save_as_copy`, `save_as` and `save`. | — |
| `phase1-reload-mesh` | Every step's events in both recordings. `LayerStacksModelDataChanged` during `insert_fill` and `set_name`; the reload's `ProjectEditionLeft` → `BusyStatusChanged(1)` → `(0)` → `ProjectEditionEntered` → callback `SUCCESS`; a missing file gives only `ERROR`. | — |
| `phase1-execute-when-not-busy` s3-s8 | The idle callback during its call, in both recordings. | s9-s10: Painter's own recordings differ (the reload starts before or after s10). |
| `phase1-reload-resources` | Every step's events except those listed. | Recording 1 s9, s12: the facade refuses s6's grey bitmap on BaseColor (decision 107, recording P20-A). Recording 2 s9, s12: Painter reloads bytes the project already holds (decision 110). The test requires both to still differ. |

Normalisations, outside the instruction sequence: resource contexts up to the session offset (decision 107), and `during_step` on the events of asynchronous steps (decision 109).

### `tests/python/test_pyapi_dispatcher.py` (items 3.2-3.7, every lane): 10 of 10 pass

- **2.2, 3.7.** All 27 classes connect and disconnect. `disconnect` stops delivery. A weak handler whose owner is collected is not called, and `connect_strong` keeps its handler alive. A failing handler is reported on stderr and the others still run.
- **2.3, 2.4, 3.2.** The lifecycle order and the handler states above. `is_in_edition_state()` is false until `ProjectEditionEntered`, and `is_busy()` is true while loading. Close discards unsaved data: reopening shows the last save with `needs_saving()` false.
- **3.3.** A script connects a handler, starts a reload and returns. The dispatcher is held behind a gate for one second, so the handler and the callback run after the script returned. Both run on the dispatcher thread.
- **3.4.** A handler on `ProjectEditionEntered` reads the stack and commits a native `Transaction` while the script's `open` waits. There is no deadlock, and the handler sees the committed state.
- **2.5.** `execute_when_not_busy`: when idle, the callback runs before the call returns; queued while busy, it runs right after `BusyStatusChanged(0)` and before `ProjectEditionEntered`.
- **2.7, 3.6.** `reload_mesh` (grid2x2 to grid4x2): the callback gets `SUCCESS` on the dispatcher thread, the texture sets become s0-s7 and the fill keeps its name. A missing file gives `ERROR` with no events.
- **2.6, 3.5.** With computations disabled, an export from a second thread stays queued with no file written, `is_busy()` is true and a save is refused. Re-enabling fires `EngineComputationsStatusChanged(True)` with `is_busy()` still true, and the export then completes. The events arrive in the order of decision 110.
- **2.8.** A reload of the bound bitmap gives `ReloadResourcesStarted` during the call; inside it a second reload returns False. `ReloadResourcesEnded` then carries old → new while the binding stays. A project reload finds nothing more. A script shelf crawls between `ShelfCrawlingStarted` and `ShelfCrawlingEnded`.
- **2.9.** `StopSource`, the queue order, and the `create` gaps naming their recordings.

### Other affected tests

All 92 tests of these files pass in one run:
- `tests/python/test_pyapi_facade.py` (9) and `test_pyapi_facade_tier0.py` (9). The provenance test covers the new documented members (the `TextureStateEventAction` members and the `MeshReloadingSettings` parameters). Those members were added to the inventory and to `documented_symbols.json`. `preserve_strokes` stays private (decision 019).
- `tests/python/test_pyapi_native.py` (14) and `test_pyapi_tier0.py` (2).
- `tests/capabilities/test_capabilities.py` (27) and `tests/parity/recorder/test_provenance.py` (16).
- `zig build pyapi-tests` and `zig build painter` (`-Werror`).

One observation outside this task: in `phase1-save-modes` recording 2, s17, Painter reports `needs_saving()` false after two renames that end on the saved name. The facade's dirty-on-edit rule (decision 107 §7) would report true. Its owner is the facade's saving rule (phase1.20's decision 107). This task compares events only.

## Open

- **Item 1.1.** `phase1.8_project-store` and `phase1.18_export-engine` are not accepted yet. The host runs over their children's code on main.
- **Recordings** (decisions 109 and 110, owner action): `phase1-engine-computations` (requested), P21-A (mesh maps in `create`), P21-B (default paths), P21-C (texture throttling), P21-D (shelves), P21-E (layer-stack events of the other edit calls), P21-F (create and open timing), P21-G (close without saving).
- `create(template_file_path=...)`: phase1.24_python-api-facade.
