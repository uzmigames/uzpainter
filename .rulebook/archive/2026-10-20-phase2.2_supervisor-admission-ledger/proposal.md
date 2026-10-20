# Proposal: phase2.2_supervisor-admission-ledger

## Why
Child of `phase2.4_supervisor-worker` (P2-SUPERVISOR in `docs/dag.md`), implementing the command-admission part of D1: `docs/architecture/02-runtime-topology.md` §3 and §5, with the persisted operation record of `docs/architecture/09-project-file-format.md` §4 and the boundary rules of `docs/architecture/11-mcp-server.md` §4 (decisions 003, 024, 025). Agents retry calls after lost acknowledgements and worker restarts; without a single writer per project, idempotency keys bound to the persisted revision and a ledger reconciled from the project store, a retry could create a second mutation or replay silently. Requirements: ARC-02, INT-04, INT-05, INT-07, NFR-06 (`docs/prd.md`).

## What Changes
- One mutation lease per open project held by the supervisor; a mutating call without the lease returns `lease_held {holder, since, active_job}`; reads need no lease and use committed snapshots.
- Durable supervisor ledger (SQLite file in the user's local app-data folder) as a control-plane record of jobs, leases, acknowledgements and cached outcomes; never a second editable document.
- Idempotency bound to the project store: the worker's `operation` row `{project_uuid, idempotency_key, request_hash, outcome, committed_revision}`, written in the same SQLite transaction as the revision, is the authority; `request_hash` = SHA-256 of the canonical JSON of the tool name and arguments; a known key with the same hash returns the stored outcome without mutating even when the current revision is newer; the same key with a different hash returns `idempotency_conflict {key, committed_revision}`.
- Revision precondition: the original base revision (`expected_revision`) is captured before first admission and preserved with the key on every retry; the worker checks a known key before the revision; an unknown key with a missing or expired precondition (below `meta.operation_horizon_revision`) returns `outcome_unknown {committed_revision}` and never executes; an unknown key with an unexpired precondition executes only if it equals the current revision, otherwise `stale_revision {expected, current}`.
- Reconciliation after a worker restart: the supervisor reads the `operation` rows newer than the last revision it acknowledged before admitting any call for that project; an unresolved outcome is never treated as a new mutation; if the rows cannot be read the call fails with `outcome_unknown`; absence from the ledger never proves that a mutation did not commit.
- Busy state: a call while a conflicting job runs returns `busy {job_id}` instead of queueing; `wait_idle {timeout}` fails explicitly on timeout (INT-05).
- Target identity on every receipt (project, set, job, revision; INT-07).

## Dependencies
- Parent: `phase2.4_supervisor-worker`.
- Prerequisites: `phase1.25_pilot-wand` (DAG input of P2-SUPERVISOR; the project store's `operation` table, retention and `compact` come from `phase1.8_project-store` through it) and `phase2.1_supervisor-ipc-worker` (pipe, worker relaunch).
- Followed by `phase2.3_supervisor-jobs`, whose terminal states are recorded in this ledger.

## Acceptance
- Lost acknowledgement: a worker killed after the durable commit and before the acknowledgement; the retry of the same request returns the stored outcome with no second revision; a changed request with the same key returns `idempotency_conflict`.
- A non-idempotent mutation committed, the project advanced beyond the retention window and compacted, the supervisor ledger lost: replaying the original key with its original precondition and with no precondition creates no mutation; a known-key replay inside the window after the current revision advanced returns the stored result.
- Two writers: the second gets `lease_held`; a conflicting call gets `busy`; `wait_idle` timeout is a failure.

## Impact
- Affected specs: `supervisor` (admission, idempotency, reconciliation)
- Affected code: supervisor admission and lease, ledger store, worker-side key and precondition checks over the project store `operation` table
- Breaking change: NO
- User benefit: retries after crashes never duplicate or silently replay a mutation
