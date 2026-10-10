# Proposal: phase1.6_store-save-retention

## Why
Child of `phase1.8_project-store` (P1-STORE in `docs/dag.md`), implementing D8 as specified in `docs/architecture/09-project-file-format.md` §1 and §4, with owner answer Q11 (decision 024: retention of the current and previous checkpoints plus the last 50 mutation revisions) and the commit-as-autosave rule of `docs/architecture/02-runtime-topology.md` §6. Every committed mutation already lands durably in the `.uzp` (delivered by `phase1.4_store-container-operations`); what is still missing is the Painter-compatible saving vocabulary on top of that history: named checkpoints, compaction with garbage collection, `save_as`/`save_as_copy`, revert, an exact dirty flag, protected approved checkpoints, the retention window and the lock sidecar. Without these the file grows without bound, an approved baseline could be overwritten, and a retry of an old mutation could not be told apart from a new one once history is pruned. Requirements: SAV-01, SAV-02, SAV-05, QG-05, OWN-07, ARC-02 (`docs/prd.md`).

## What Changes
- `save()` (facade `ProjectSaveMode.Incremental`): marks the current revision as a named checkpoint and moves `checkpoint('previous')` to the checkpoint before it (09 §4; `03-project-model.md` §5).
- `save(Full)` / `compact` (Painter's "Save and compact" equivalent): checkpoint; drop the regenerable `cache` table; garbage-collect `plane`, `plane_version`, `plane_chunk` and `blob` rows unreachable from every retained manifest while preserving every chunk reachable from a retained manifest, including chunks first written in revisions no longer retained separately; delete the `operation` rows of revisions no longer retained and record the highest collapsed revision in `meta.operation_horizon_revision`; `VACUUM INTO` a temporary file, then atomic rename over the project file.
- Retention policy (owner Q11): keep `current`, `previous`, the last 50 mutation revisions and every checkpoint flagged `protected`; `compact` collapses older mutation revisions and older unprotected named checkpoints; a `protected` checkpoint can be neither collapsed nor overwritten (SAV-02, QG-05).
- `save_as(path)`: `VACUUM INTO` the new path (closed, portable), then the open project relocates to it; `save_as_copy(path)`: `VACUUM INTO` the copy while the project stays where it was and keeps its dirty state (Painter semantics).
- Revert: opening any retained revision as the new `current` appends a new revision whose manifest copies the selected manifest, including its raster-plane content bindings unchanged; history stays append-only.
- Dirty flag: `needs_saving()` = current revision ≠ last named checkpoint, exactly (SAV-01).
- Lock sidecar `<file>.uzp.lock` holding the owning worker pid: created on open, stale locks detected by pid liveness, removed by `close` (SAV-05).
- Files at rest are portable: `close`, `save_as` and `compact` checkpoint SQLite so no `-wal`/`-shm` companion remains and `journal_mode = DELETE` holds (09 §1).
- Fault injection for this child: interruption during `VACUUM INTO` (compact, `save_as`, `save_as_copy`) and between `VACUUM INTO` and the atomic rename.
- Code: `src/store/save.{h,cpp}` (checkpoints, `save_as`, `save_as_copy`, revert, dirty flag), `src/store/compact.{h,cpp}` (retention, reachability, garbage collection, `VACUUM INTO` + rename), `src/store/lock.{h,cpp}` (sidecar); tests in `tests/store/`.

## Dependencies
- Parent: `phase1.8_project-store` (integration and acceptance of P1-STORE).
- Prerequisite: `phase1.3_document-model` (the DAG input of P1-STORE: revisions, checkpoints, transactions and operation records in the document model).
- Prerequisites (siblings): `phase1.4_store-container-operations` (SQLite container, revision/operation/checkpoint tables, the mutation commit transaction, the idempotency decisions that read the pruning horizon) and `phase1.5_store-planes` (plane versions and chunk bindings that compaction and revert must preserve).
- Followed by the sibling `phase1.7_store-inspect-census`, which measures compaction time and retained-history size with this child's operations.

## Acceptance
- The `09-project-file-format.md` §7 items owned by this child pass: interruption during `VACUUM INTO` leaves the previous file intact; edit → revert → edit → reopen → compact reproduces the exact manifest and raster contents of every retained state, including a protected checkpoint whose chunks were first written outside the retained mutation window; a non-idempotent mutation pruned by compaction cannot be replayed into a second mutation, with or without its original precondition, while a known-key replay inside the window still returns the stored result despite a newer current revision.
- Retention keeps exactly `current`, `previous`, the last 50 mutation revisions and every protected checkpoint; a protected checkpoint is never collapsed or overwritten.
- `needs_saving()` is exact; `save_as` relocates and `save_as_copy` does not; files at rest after `close`, `save_as` and `compact` have no `-wal`/`-shm` companion; a stale lock sidecar is detected and the sidecar is removed on close.

## Impact
- Affected specs: `project-store` (saving semantics, retention, compaction, revert, lock)
- Affected code: `src/store/save.*`, `src/store/compact.*`, `src/store/lock.*`, `tests/store/`
- Breaking change: NO
- User benefit: a project file that stays compact, never loses an approved baseline and can be reverted to any retained state
