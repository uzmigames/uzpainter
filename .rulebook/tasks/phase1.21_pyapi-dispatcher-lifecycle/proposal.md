# Proposal: phase1.21_pyapi-dispatcher-lifecycle

## Why
Child of `phase1.24_python-api-facade` (P1-PYAPI in `docs/dag.md`), implementing D9 (decision 011) as specified in `docs/architecture/10-python-api.md` §4 (lifecycle, events, mesh reload, resources, computation state) and the worker thread model of D1 (decision 003) in `docs/architecture/02-runtime-topology.md` §4. Painter's scripts are written against an asynchronous host: `project.create/open` return immediately, readiness is signalled by events in a documented order, callbacks arrive on a dispatcher after the committed transition, and engine computations can be disabled and re-enabled. A facade that ran synchronously or fired events early would make the scripts take different paths than in Painter, so the lifecycle and the dispatcher thread are reproduced as Painter's observable contract. Requirements: OWN-04, ARC-13, INT-01, INT-05 (`docs/prd.md`).

## What Changes
- `src/python/dispatcher.{h,cpp}`: the Python dispatcher thread of 02 §4, delivering `substance_painter.event` events and facade callbacks after the committed transition, never holding the document lock while calling Python, and surviving the return of the script that started the operation.
- `python/substance_painter/event.py`: `event.DISPATCHER.connect/connect_strong/disconnect` and all 27 documented event classes; events whose operations arrive later stay connectable and are emitted by their owners (`BakingProcessAboutToStart/Progress/Ended` and `StopSource` by `phase3.5_embree-bakers`).
- Lifecycle (10 §4): `project.create/open` return immediately while loading runs on the engine thread; `project.is_busy()` is true meanwhile; event order `ProjectOpened`/`ProjectCreated` → `ProjectEditionEntered` (only when evaluation is ready); `ProjectAboutToClose` → `ProjectClosed`; `ProjectAboutToSave(path)` → `ProjectSaved`; `is_in_edition_state()` becomes true with `ProjectEditionEntered`, never before; `execute_when_not_busy(cb)` runs on the dispatcher thread when busy clears.
- Computation state: `application.enable_engine_computations/disable_engine_computations/engine_computations_status` keep an explicit state; while disabled, evaluation requests are deferred; `is_busy()` reflects the deferred backlog on re-enable; `EngineComputationsStatusChanged` fires. Not a no-op.
- Mesh reload: the facade's `reload_mesh(path, settings, cb)` calls `cb(ReloadMeshStatus)` on the dispatcher thread when done (a callback, not an event, as in Painter), over the native reload of `phase1.6_mesh-reload`.
- Resources: `reload_modified_resources_async` → `ReloadResourcesStarted/Ended`; shelf crawling → `ShelfCrawlingStarted/Ended` over folders of UzPainter assets and user files.
- `async_utils` documented helpers over the same dispatcher.

## Dependencies
- Parent: `phase1.24_python-api-facade` (integration and acceptance of P1-PYAPI).
- Prerequisites: `phase1.3_document-model`, `phase1.18_export-engine`, `phase1.8_project-store` (DAG inputs of P1-PYAPI), `phase1.6_mesh-reload` (native mesh reload, delivered with `phase1.7_mesh-loader`), and the siblings `phase1.19_pyapi-native-module` and `phase1.20_pyapi-facade`.
- Followed by the siblings `phase1.22_pyapi-cli-capabilities` (statuses for these symbols) and `phase1.23_pyapi-pipeline-adapter`.

## Acceptance
- The Tier 0 event-order probes (`phase0.6_tier0-api-probes`) are exact for open, create, save and close.
- Events and callbacks are delivered on the dispatcher thread after the committed transition, including after the originating script returned, and no Python callback runs while the document lock is held.
- Disabling engine computations defers evaluation and re-enabling reports the backlog through `is_busy()` and `EngineComputationsStatusChanged`.

## Impact
- Affected specs: `python-api` (dispatcher thread, lifecycle, events, computation state)
- Affected code: `src/python/dispatcher.*`, `python/substance_painter/event.py`, `python/substance_painter/project.py`, `python/substance_painter/application.py`, `tests/python/`
- Breaking change: NO
- User benefit: Painter scripts that wait for readiness, react to events or pause computations behave as they do in Painter
