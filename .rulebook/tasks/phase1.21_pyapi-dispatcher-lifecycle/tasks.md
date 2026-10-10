## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase1.3_document-model, phase1.18_export-engine, phase1.8_project-store, phase1.6_mesh-reload, phase1.19_pyapi-native-module, phase1.20_pyapi-facade

## 2. Implementation
- [ ] 2.1 Python dispatcher thread: queue of committed transitions, delivery outside the document lock, lifetime independent of the originating script
- [ ] 2.2 `event.DISPATCHER.connect/connect_strong/disconnect` with weak and strong references, and all 27 documented event classes
- [ ] 2.3 Asynchronous `project.create/open` with loading on the engine thread, `is_busy()`, `is_in_edition_state()` and the documented event order through `ProjectEditionEntered`
- [ ] 2.4 Close and save events: `ProjectAboutToClose` → `ProjectClosed`, `ProjectAboutToSave(path)` → `ProjectSaved`
- [ ] 2.5 `execute_when_not_busy(cb)` running on the dispatcher thread when busy clears
- [ ] 2.6 Computation state: enable/disable/status, deferred evaluation backlog, `is_busy()` on re-enable, `EngineComputationsStatusChanged`
- [ ] 2.7 Facade `reload_mesh(path, settings, cb)` calling `cb(ReloadMeshStatus)` on the dispatcher thread over the native mesh reload
- [ ] 2.8 `reload_modified_resources_async` with `ReloadResourcesStarted/Ended`; shelf crawling with `ShelfCrawlingStarted/Ended`
- [ ] 2.9 `async_utils` documented helpers bound to the dispatcher

## 3. Tests
- [ ] 3.1 Event-order probes for create, open, save and close compared exactly with `phase0.6_tier0-api-probes` goldens on the self-hosted GPU runner
- [ ] 3.2 `is_in_edition_state()` false until `ProjectEditionEntered` and `is_busy()` true while loading
- [ ] 3.3 A script connects a handler, starts an open and returns; the handler still receives `ProjectEditionEntered` on the dispatcher thread
- [ ] 3.4 Lock test: a handler that calls back into the API does not deadlock and observes the committed state
- [ ] 3.5 Computation state: with computations disabled an export request is deferred, `engine_computations_status` reports disabled, re-enable sets `is_busy()` until the backlog drains and fires `EngineComputationsStatusChanged`
- [ ] 3.6 `reload_mesh` callback receives `ReloadMeshStatus` on the dispatcher thread for a successful and a failing reload
- [ ] 3.7 `disconnect` stops delivery; a `connect` (weak) handler whose owner is collected is not called; `connect_strong` keeps it alive

## 4. Acceptance
- [ ] 4.1 Every §3 test green (hosted CPU lane where no GPU or private golden is needed, self-hosted GPU runner otherwise); results attached to `phase1.24_python-api-facade`

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
