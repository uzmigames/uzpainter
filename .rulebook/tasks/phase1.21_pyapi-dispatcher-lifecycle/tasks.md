## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase1.3_document-model, phase1.18_export-engine, phase1.8_project-store, phase1.6_mesh-reload, phase1.19_pyapi-native-module, phase1.20_pyapi-facade — phase1.3, phase1.6, phase1.19 and phase1.20 are archived; phase1.8_project-store and phase1.18_export-engine are still open (the host runs over their children's code on main)

## 2. Implementation
- [x] 2.1 Python dispatcher thread: queue of committed transitions, delivery outside the document lock, lifetime independent of the originating script — `src/python/dispatcher.{h,cpp}`, `uzpainter.event` (`post`, `flush`, `drain`, `hold`/`release`); hosts drain after the script (`pyapi_runner.cpp`); `src/python/PYAPI.md` §6, decision 109 §1
- [x] 2.2 `event.DISPATCHER.connect/connect_strong/disconnect` with weak and strong references, and all 27 documented event classes — `python/uzpainter_facade/event.py`; bake, camera and texture-state events connectable and emitted by their owners (decision 110 §5)
- [x] 2.3 Asynchronous `project.create/open` with loading on the engine thread, `is_busy()`, `is_in_edition_state()` and the documented event order through `ProjectEditionEntered` — `is_busy()` true while loading (GIL released, other threads and handlers see it); the recorded order and handler states; per decision 109 §3 the call returns once in edition, as Painter's recorded polls show (recording P21-F settles Painter's call timing)
- [x] 2.4 Close and save events: `ProjectAboutToClose` → `ProjectClosed`, `ProjectAboutToSave(path)` → `ProjectSaved` — with `ProjectEditionLeft` and the busy pair around close; saves refused while busy; Painter's discard-on-close (decision 109 §5, recording P21-G)
- [x] 2.5 `execute_when_not_busy(cb)` running on the dispatcher thread when busy clears — now when idle (before returning), else right after `BusyStatusChanged(0)` (`host.py`)
- [x] 2.6 Computation state: enable/disable/status, deferred evaluation backlog, `is_busy()` on re-enable, `EngineComputationsStatusChanged` — native `uzpainter.application` state pausing the job worker; facade exports wait in their busy section; pending recording `phase1-engine-computations` (decision 110 §1)
- [x] 2.7 Facade `reload_mesh(path, settings, cb)` calling `cb(ReloadMeshStatus)` on the dispatcher thread over the native mesh reload — native `uzpainter.project.reload_mesh` (one transaction over `mesh/reload.h`, `MaterialMappingError`); worker thread with the recorded events
- [x] 2.8 `reload_modified_resources_async` with `ReloadResourcesStarted/Ended`; shelf crawling with `ShelfCrawlingStarted/Ended` — the six filters, `is_reload_modified_resources_running`, native `list_used_resources`/`resource_origin`; script-defined shelves crawl on a worker thread; application/user shelves and shelf resources are named gaps (decision 110 §3, §6)
- [x] 2.9 `async_utils` documented helpers bound to the dispatcher — `substance_painter.async_utils.StopSource`

## 3. Tests
- [x] 3.1 Event-order probes for create, open, save and close compared exactly with `phase0.6_tier0-api-probes` goldens in a local run on the owner's machine (decision 028; the local run report is the evidence) — `test_pyapi_lifecycle_tier0.py`: `lifecycle-events` exact in all 4 recordings (events, handler states, arguments, polls); `phase1-save-modes`, `phase1-reload-mesh`, `phase1-reload-resources` and `phase1-execute-when-not-busy` s3-s8 in both recordings, named exclusions only (report `parity/reports/phase1/pyapi-dispatcher-lifecycle.md`)
- [x] 3.2 `is_in_edition_state()` false until `ProjectEditionEntered` and `is_busy()` true while loading
- [x] 3.3 A script connects a handler, starts an open and returns; the handler still receives `ProjectEditionEntered` on the dispatcher thread — the open delivers on the dispatcher thread before returning (decision 109 §3); the after-return delivery is tested with a reload whose `ProjectEditionEntered` and callback run after the script returned
- [x] 3.4 Lock test: a handler that calls back into the API does not deadlock and observes the committed state
- [x] 3.5 Computation state: with computations disabled an export request is deferred, `engine_computations_status` reports disabled, re-enable sets `is_busy()` until the backlog drains and fires `EngineComputationsStatusChanged`
- [x] 3.6 `reload_mesh` callback receives `ReloadMeshStatus` on the dispatcher thread for a successful and a failing reload
- [x] 3.7 `disconnect` stops delivery; a `connect` (weak) handler whose owner is collected is not called; `connect_strong` keeps it alive

## 4. Acceptance
- [x] 4.1 Every §3 test green (hosted CPU lane where no GPU or private golden is needed, with the other tests skipped there with an explicit reason; a local run on the owner's machine otherwise, decision 028); results attached to `phase1.24_python-api-facade` — 10 of 10 in `test_pyapi_dispatcher.py` (CPU, every lane); 5 of 5 in `test_pyapi_lifecycle_tier0.py` (owner's machine, skips without a store); report `parity/reports/phase1/pyapi-dispatcher-lifecycle.md` for phase1.24

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation — `src/python/PYAPI.md` §6, `python/FACADE.md` §8-§9, `docs/architecture/10-python-api.md` §4, decisions 109 and 110
- [x] 5.2 Write tests covering the new behavior
- [x] 5.3 Run tests and confirm they pass
