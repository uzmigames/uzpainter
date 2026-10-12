# 109. The facade reproduces Painter's recorded host: create and open return in edition, and every event is delivered on the dispatcher thread

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase1.21_pyapi-dispatcher-lifecycle, phase1.20_pyapi-facade, phase1.19_pyapi-native-module, phase1.24_python-api-facade

## Context

Task phase1.21 gives the `substance_painter` facade Painter's asynchronous host: the dispatcher thread, the lifecycle events, the busy and edition states, `execute_when_not_busy`, the engine computations, `reload_mesh` with its callback, the resource reload and shelf crawling. The task text, written before the recordings were read, says `project.create/open` "return immediately".

Measured facts. They come from the private goldens of the current envelope, Painter 12.1.5 in Legacy, read by `test_pyapi_lifecycle_tier0.py`. Each handler logged its event, the state it read (open, edition, busy), its argument, and `during_step` when it ran before the probe call returned.

- **Create and open** (`lifecycle-events`, 4 recordings): `BusyStatusChanged(1)` (F, F, T) → `BusyStatusChanged(0)` (T, F, F) → `ProjectCreated`/`ProjectOpened` (T, F, F) → `ProjectEditionEntered` (T, T, F). The host's first poll after the call already saw the project ready, 4 times out of 4.
- **Close:** `ProjectEditionLeft` (T, F, F) → `BusyStatusChanged(1)` (T, F, T) → `ProjectAboutToClose` (T, F, T) → `ProjectClosed` (F, F, T) → `BusyStatusChanged(0)` (F, F, F).
- **Saves** (`lifecycle-events`, `phase1-save-modes` s9, s12, s18): `ProjectAboutToSave(file_path)` → `ProjectSaved`, both with `during_step`. Saves deliver no busy events.
- `BusyStatusChanged.busy` is delivered as `1` and `0`. `is_in_edition_state()` answers False, without raising, while no project is open.
- **Exports** deliver a `BusyStatusChanged(1)`/`(0)` pair (the export before each reopen of the R10 probes).
- **`execute_when_not_busy`** (`phase1-execute-when-not-busy`):
  - When idle, the callback runs during the call (s8).
  - In recording 2, called while a reload was busy, it ran right after `BusyStatusChanged(0)` and before `ProjectEditionEntered` (s10).
  - In recording 1 the reload had not started yet, so it ran during the call. Painter's own timing decides that case.
- **`reload_mesh`** (`phase1-reload-mesh`): the call returns at once. Afterwards: `ProjectEditionLeft` → `BusyStatusChanged(1)` → `BusyStatusChanged(0)` → `ProjectEditionEntered` → callback `SUCCESS`. A missing file gives only the callback `ERROR`.
- **`reload_modified_resources_async`** (`phase1-reload-resources`): `ReloadResourcesStarted` during the call, then `ReloadResourcesEnded` after it, with old → new ids. The fill keeps the old version bound.
- **`LayerStacksModelDataChanged`**: during `insert_fill`, `insert_group`, `set_name`, `delete_node` and `add_mask`. Never during `active_channels`, `set_source`, `import_project_resource` or `update_layer_stack_resource`.
- Painter documents `close` as losing unsaved data. UzPainter's native close keeps every commit (decision 105).
- Assets3D's `painter_create.py` polls `is_busy()` after `create`.

The model panel was asked once (C1-C9 in the scratch dossier): cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5.
- **C1, create/open return in edition.** DISAGREE, AGREE, PARTLY. GPT: fast asynchronous loading would also give ready polls.
- **C2, synchronous delivery on the dispatcher with the caller waiting.** PARTLY, PARTLY, AGREE. The inline re-entrant delivery is UzPainter's own choice, not a recorded Painter behaviour.
- **C3, asynchronous operations race as in Painter.** PARTLY, AGREE, AGREE.
- **C4, discard by revert and re-save.** PARTLY ×3. No save events may come from it, and the reopened content after a close is unrecorded.
- **C9, LayerStacksModelDataChanged.** PARTLY, PARTLY, AGREE. Only the recorded inserts emit it; the rest is decision 110.

## Decision

1. **Dispatcher.** `src/python/dispatcher.{h,cpp}` is the Python dispatcher thread of 02 §4.
   - It runs queued Python tasks in order, with the GIL, and never takes the document lock itself.
   - `flush()` waits, with the GIL released, until the tasks queued before it have run. On the dispatcher thread it runs them inline: this is UzPainter's choice for deadlock avoidance, unrecorded in Painter.
   - `hold()`/`release()` mark an asynchronous operation in flight. Hosts drain the dispatcher after a script returns, so deliveries outlive the script.
2. **Delivery.** Every event and facade callback runs on the dispatcher thread.
   - A transition changes the state first, then delivers its event, so a handler reads the recorded state.
   - Synchronous operations wait for their deliveries: create, open, close, the saves, the export's busy pair, `execute_when_not_busy` when idle, `ReloadResourcesStarted` and `LayerStacksModelDataChanged`. Their handlers run before the call returns.
   - Asynchronous operations deliver from a worker thread after the call returns: `reload_mesh`, `ReloadResourcesEnded` and shelf crawls. Like Painter, they do not fix whether a call made right after them sees busy.
3. **Create and open** load with `is_busy()` true. They deliver the recorded sequence and return once `ProjectEditionEntered` has been delivered. This follows the recorded polls rather than the task text. Whether Painter's own call waits is unrecorded: recording **P21-F** (below) settles it.
4. **Busy and edition.**
   - Busy sections nest: create, open, close, a mesh reload, an export. The first entry delivers `BusyStatusChanged(1)` and the last exit `BusyStatusChanged(0)`, then runs the `execute_when_not_busy` callbacks queued meanwhile.
   - Saves and `reload_mesh` raise `ProjectError` while busy, as Painter documents.
   - Edition runs from `ProjectEditionEntered` to `ProjectEditionLeft`.
5. **Close discards unsaved data.**
   - A saved project is reverted to its last named checkpoint and re-saved through the native API, with no save event, before it closes. The reopened file then shows the last save with `needs_saving()` false.
   - An untitled project's folder is removed by the native close. The native API keeps its durable close.
   - The reopened content after a close without saving is unrecorded: recording **P21-G** settles it.
6. **`reload_mesh`** runs the native reload (`uzpainter.project.reload_mesh`, one transaction over `mesh/reload.h`) on a worker thread, between the recorded events. It then calls the callback with `ReloadMeshStatus` on the dispatcher thread. A missing file gives only `ERROR`.
7. **Tier 0 harness.** `test_pyapi_lifecycle_tier0.py` runs the recorder's own Painter-side code inside UzPainter.
   - It replays `lifecycle-events` exactly: every event, state, argument and polled state.
   - It replays every step of `phase1-save-modes`, `phase1-reload-mesh`, `phase1-reload-resources` and `phase1-execute-when-not-busy` (s3-s8), in both recordings.
   - Normalisations: resource contexts (decision 107), and `during_step` on the events of asynchronous steps, a timing that varies in Painter itself.

## Recordings this decision names (not recorded; owner action)

- **P21-F, create and open timing.** The lifecycle procedure with the probe-step marker set during `create` and `open`. It also needs a second Python thread polling `is_busy()` and `is_in_edition_state()` every millisecond from the call until `ProjectEditionEntered`.
- **P21-G, close without saving.** Create, `save_as`, rename a fill, `close`, then `open`: the fill's name and `needs_saving()`, with the lifecycle events connected.

## Alternatives Considered

- **Returning from create/open at once.** Rejected: the polls would show a busy state that Painter's 4 recordings never show.
- **Calling handlers on the thread that made the transition.** Rejected: 02 §4 and the task require the dispatcher thread, and handlers would run under the caller's state.
- **Discarding by truncating the store's history.** Rejected: history is append-only (decision 105). Revert and re-save gives the same file content and saved state.
- **A busy flag set synchronously by `reload_mesh`.** Rejected: handlers would read busy during `ProjectEditionLeft`, against the recording.

## Consequences

- Scripts that poll `is_busy()` or wait for `ProjectEditionEntered` work unchanged.
- phase1.22 lists the host symbols' statuses.
- When P21-F or P21-G is recorded, any difference is fixed or excluded by name in `test_pyapi_lifecycle_tier0.py`.
