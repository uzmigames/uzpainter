## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase1.25_pilot-wand, phase2.1_supervisor-ipc-worker

## 2. Implementation
- [ ] 2.1 Per-project mutation lease in the supervisor (`lease_held {holder, since, active_job}` for a mutating call without the lease); reads served from committed snapshots without a lease
- [ ] 2.2 Durable supervisor ledger (SQLite in the user's local app-data folder) for jobs, leases, acknowledgements and cached outcomes
- [ ] 2.3 `request_hash` = SHA-256 of the canonical JSON of tool name and arguments; key scoped to `project_uuid`
- [ ] 2.4 Worker-side admission order: known key + same hash returns the stored outcome without mutating; known key + different hash returns `idempotency_conflict {key, committed_revision}`; only then the revision precondition
- [ ] 2.5 Revision precondition rule: original `expected_revision` preserved with the key; unknown key with missing or expired precondition (below `meta.operation_horizon_revision`) returns `outcome_unknown`; unexpired and equal to the current revision executes; otherwise `stale_revision {expected, current}`
- [ ] 2.6 Reconciliation after a worker restart from the `operation` rows newer than the last acknowledged revision, completed before admitting any call for that project; unreadable rows fail the call with `outcome_unknown`
- [ ] 2.7 Busy state: `busy {job_id}` for a call conflicting with a running job; `wait_idle {timeout}` with timeout as an explicit failure
- [ ] 2.8 Receipts carry target identity (project, set, job, revision, `committed_revision`) and the generated or supplied key and precondition

## 3. Tests
- [ ] 3.1 Lost-acknowledgement test: kill the worker after the durable commit and before the acknowledgement; retry the same request (stored outcome, no second revision) and a changed request with the same key (`idempotency_conflict`)
- [ ] 3.2 Beyond-retention test: commit a non-idempotent mutation, advance past the Q11 window (current and previous checkpoints plus 50 mutation revisions), compact, delete the supervisor ledger, replay the original key with its original precondition and with no precondition: neither replay creates a mutation
- [ ] 3.3 Known-key replay inside the window after the current revision advanced returns the stored result
- [ ] 3.4 Failed mutation writes no `operation` row; its retry follows the unknown-key rule (`stale_revision` once the revision moved, execution against the unchanged revision otherwise)
- [ ] 3.5 Two writers (`lease_held`), busy (`busy {job_id}`), `wait_idle` timeout failure
- [ ] 3.6 Unreadable operation records produce `outcome_unknown` and no execution

## 4. Acceptance
- [ ] 4.1 Every §3 test green on the hosted CPU lane and on the self-hosted GPU runner; results attached to `phase2.4_supervisor-worker`

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
