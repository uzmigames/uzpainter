## ADDED Requirements

### Requirement: Named Checkpoints And Exact Dirty Flag
`save()` SHALL mark the current revision as a named checkpoint and move `previous` to the checkpoint before it, and `needs_saving()` MUST return true exactly when the current revision differs from the last named checkpoint.

#### Scenario: Save after an edit
Given an open project whose last named checkpoint is revision 7
When a mutation commits revision 8 and the caller then calls `save()`
Then `needs_saving()` is true before the save, the new checkpoint names revision 8, `previous` names revision 7 and `needs_saving()` is false afterwards

### Requirement: Retention Window
`compact` and `save(Full)` SHALL retain exactly the `current` and `previous` checkpoints, the last 50 mutation revisions and every checkpoint flagged `protected`, and MUST collapse older mutation revisions and older unprotected named checkpoints.

#### Scenario: Compact after 60 mutations
Given a project with 60 committed mutation revisions, two older unprotected named checkpoints and one protected checkpoint
When the caller runs `compact`
Then the retained revisions are `current`, `previous`, the last 50 mutation revisions and the protected checkpoint, and the two older unprotected checkpoints are gone

### Requirement: Protected Checkpoints Are Immutable
A checkpoint flagged `protected` MUST NOT be collapsed by compaction or overwritten by any save operation; an attempt SHALL fail with an explicit error and leave its manifest and raster content unchanged.

#### Scenario: Overwrite attempt on an approved baseline
Given a protected checkpoint named `approved`
When a caller saves a new checkpoint under the name `approved` and then compacts
Then the save is refused with an explicit error and the `approved` manifest and pixels equal their original values after compaction

### Requirement: Compaction Preserves Every Retained State
Compaction SHALL delete only rows unreachable from every retained manifest and MUST preserve every plane version, chunk and blob reachable from a retained manifest, including chunks first written in revisions no longer retained separately.

#### Scenario: Protected checkpoint older than the window
Given a protected checkpoint whose raster chunks were written 80 mutations ago
When the project is edited, reverted, edited again, reopened and compacted
Then every retained state, including that checkpoint, yields the same manifest and the same raster bytes as before compaction

### Requirement: Pruned Operations Cannot Be Replayed
Compaction SHALL delete the `operation` rows of collapsed revisions and record the highest collapsed revision in `meta.operation_horizon_revision`, so that a replay of a pruned key MUST NOT create a mutation.

#### Scenario: Replay after the key left the window
Given a non-idempotent mutation committed under key `k1` with precondition revision 3, followed by 55 mutations and a compaction
When a client replays `k1` once with precondition 3 and once with no precondition
Then both replays return `outcome_unknown` with the current revision and no revision is created

#### Scenario: Known key inside the window
Given a mutation committed under key `k2` that is still inside the retention window and a newer current revision
When a client replays `k2` with the same request hash
Then the stored outcome is returned and no revision is created

### Requirement: Atomic Rewrite Operations
`compact`, `save_as` and `save_as_copy` SHALL write through `VACUUM INTO` and, for compaction, an atomic rename, so that an interruption at any point MUST leave the original project file in its previous state with no partial target.

#### Scenario: Kill during compaction
Given an open project with uncompacted history
When the worker is killed while `VACUUM INTO` writes the temporary file
Then reopening the project yields its previous state and no partial temporary or target file remains

### Requirement: Save As And Save As Copy
`save_as(path)` SHALL produce a closed, portable file at `path` and relocate the open project to it; `save_as_copy(path)` SHALL produce the same file while the open project keeps its location and dirty state.

#### Scenario: Copy keeps the dirty state
Given an open project with `needs_saving()` true
When the caller calls `save_as_copy` with a new path
Then the copy opens as a portable project, the original stays open at its old path and `needs_saving()` is still true

### Requirement: Revert Is Append-Only
Reverting to a retained revision SHALL append a new revision whose manifest copies the selected manifest, including its raster-plane bindings unchanged, and MUST NOT remove any revision.

#### Scenario: Revert to an earlier checkpoint
Given revisions 10 to 15 where checkpoint `a` names revision 12
When the caller reverts to `a`
Then revision 16 is created with the manifest and plane bindings of revision 12, and revisions 10 to 15 remain

### Requirement: Lock Sidecar And Portable Files At Rest
Opening a project SHALL create a `.uzp.lock` sidecar holding the owning worker pid, refuse a second owner while that pid lives and replace a stale lock whose pid is dead, and `close` MUST remove the sidecar and leave no `-wal`/`-shm` companion.

#### Scenario: Stale lock after a crash
Given a `.uzp.lock` written by a worker that was killed
When another worker opens the project
Then the stale lock is detected by pid liveness and replaced, and after `close` neither the lock nor a `-wal`/`-shm` file remains
