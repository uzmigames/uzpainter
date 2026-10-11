## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: phase1.3_document-model, phase1.4_store-container-operations, phase1.5_store-planes

## 2. Implementation
- [x] 2.1 `save()` / `ProjectSaveMode.Incremental`: mark the current revision as a named checkpoint and move `checkpoint('previous')` to the checkpoint before it
- [x] 2.2 Retention policy (Q11): compute the retained set = `current`, `previous`, the last 50 mutation revisions and every `protected` checkpoint; refuse to overwrite or collapse a `protected` checkpoint with an explicit error
- [x] 2.3 Reachability walk over every retained manifest: plane bindings → `plane_version` → `plane_chunk` → `blob`, plus resource bindings → `blob`, including chunks first written in revisions no longer retained separately
- [x] 2.4 `save(Full)` / `compact`: checkpoint, drop `cache`, collapse non-retained mutation revisions and older unprotected named checkpoints, delete unreachable planes, plane versions, chunks and blobs, delete the `operation` rows of collapsed revisions and raise `meta.operation_horizon_revision`
- [x] 2.5 `VACUUM INTO` a temporary file next to the project, then atomic rename over the project file; the temporary file is removed on failure
- [x] 2.6 `save_as(path)`: `VACUUM INTO` the target (closed, portable), then relocate the open project and its lock to the target
- [x] 2.7 `save_as_copy(path)`: `VACUUM INTO` the copy; the project keeps its path, lock and dirty state
- [x] 2.8 Revert: open a retained revision as a new `current` revision whose manifest copies the selected manifest, including its raster-plane bindings, unchanged; reject a revision outside the retained set with an explicit error
- [x] 2.9 Dirty flag: `needs_saving()` returns current revision ≠ last named checkpoint
- [x] 2.10 Lock sidecar `<file>.uzp.lock` with the owning worker pid: created on open, open refused while a live pid holds it, stale lock (dead pid) detected and replaced, removed by `close`
- [x] 2.11 `close`, `save_as` and `compact` checkpoint SQLite so no `-wal`/`-shm` companion remains and `journal_mode = DELETE` holds at rest
- [x] 2.12 Test-only fault hooks: kill or I/O failure during `VACUUM INTO` and between `VACUUM INTO` and the rename, excluded from release builds

## 3. Tests
- [x] 3.1 Checkpoint tests: `save()` names the current revision and moves `previous`; `needs_saving()` false after save, true after a committed mutation, exact after revert and after `save_as_copy`
- [x] 3.2 Retention test: commit 60 mutations with named and protected checkpoints in between, compact, and verify the retained set is exactly `current`, `previous`, the last 50 mutation revisions and every protected checkpoint, with older unprotected checkpoints collapsed
- [x] 3.3 Protected checkpoint test (QG-05): overwrite and collapse attempts on a protected checkpoint are refused and its manifest and pixels are unchanged after compaction
- [x] 3.4 Edit → revert → edit → reopen → compact: manifests and raster contents of every retained state equal their pre-compaction values byte for byte, including a protected checkpoint whose chunks were first written outside the retained mutation window (09 §7)
- [x] 3.5 Garbage-collection test: after compaction no `plane`, `plane_version`, `plane_chunk` or `blob` row is unreachable from a retained manifest, and every reachable one still exists
- [x] 3.6 Pruned-key replay (09 §7): commit a non-idempotent mutation, advance beyond retention and compact; replaying its original key with its original precondition and with no precondition returns `outcome_unknown` and creates no revision; a known-key replay inside the window returns the stored outcome despite a newer current revision
- [x] 3.7 `save_as` relocates the project and the lock; `save_as_copy` leaves path, lock and dirty state unchanged; both outputs open as closed, portable files
- [x] 3.8 Interruption during `VACUUM INTO` and before the rename (compact, `save_as`, `save_as_copy`): the original file opens at its previous state, no partial target remains, and the error message names the failed step
- [x] 3.9 Portability test: after `close`, `save_as` and `compact` no `-wal`/`-shm` file exists and the copied `.uzp` opens from another path
- [x] 3.10 Lock tests: second open refused while the owning pid lives; stale lock from a killed worker detected and replaced; `close` removes the sidecar

## 4. Acceptance
- [ ] 4.1 Every §3 test green on the hosted CPU lane; results attached to `phase1.8_project-store` as part of its `09-…` §7 evidence
  - Local run 2026-10-10: `python -m pytest tests/store` 35 passed (`test_store_save.py`: the 10 cases of §3 plus the case-list and child checks). Pending the owner's push: the hosted `parity.yml` CPU lane (`python -m pytest`) must show `tests/store/test_store_save.py` all passed (no skip: zig on PATH) with `PASS checkpoints` … `PASS lock_sidecar`.

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
- [x] 5.2 Write tests covering the new behavior
- [x] 5.3 Run tests and confirm they pass
