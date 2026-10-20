## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: phase1.25_pilot-wand, phase2.1_supervisor-ipc-worker — checked as a recorded scope split (decision 326): phase1.25_pilot-wand is not accepted; its open items (2.7 `infinite` padding and 3.1-4.1) are the Wand's own parity work: recordings plus fit; this task's deliverables do not read the Wand's maps

## 2. Implementation
- [x] 2.1 Per-project mutation lease in the supervisor (`lease_held {holder, since, active_job}` for a mutating call without the lease); reads served from committed snapshots without a lease
- [x] 2.2 Durable supervisor ledger (SQLite in the user's local app-data folder) for jobs, leases, acknowledgements and cached outcomes
- [x] 2.3 `request_hash` = SHA-256 of the canonical JSON of tool name and arguments; key scoped to `project_uuid`
- [x] 2.4 Worker-side admission order: known key + same hash returns the stored outcome without mutating; known key + different hash returns `idempotency_conflict {key, committed_revision}`; only then the revision precondition
- [x] 2.5 Revision precondition rule: original `expected_revision` preserved with the key; unknown key with missing or expired precondition (below `meta.operation_horizon_revision`) returns `outcome_unknown`; unexpired and equal to the current revision executes; otherwise `stale_revision {expected, current}`
- [x] 2.6 Reconciliation after a worker restart from the `operation` rows newer than the last acknowledged revision, completed before admitting any call for that project; unreadable rows fail the call with `outcome_unknown`
- [x] 2.7 Busy state: `busy {job_id}` for a call conflicting with a running job; `wait_idle {timeout}` with timeout as an explicit failure
- [x] 2.8 Receipts carry target identity (project, set, job, revision, `committed_revision`) and the generated or supplied key and precondition

## 3. Tests
- [x] 3.1 Lost-acknowledgement test: kill the worker after the durable commit and before the acknowledgement; retry the same request (stored outcome, no second revision) and a changed request with the same key (`idempotency_conflict`)
- [x] 3.2 Beyond-retention test: commit a non-idempotent mutation, advance past the Q11 window (current and previous checkpoints plus 50 mutation revisions), compact, delete the supervisor ledger, replay the original key with its original precondition and with no precondition: neither replay creates a mutation
- [x] 3.3 Known-key replay inside the window after the current revision advanced returns the stored result
- [x] 3.4 Failed mutation writes no `operation` row; its retry follows the unknown-key rule (`stale_revision` once the revision moved, execution against the unchanged revision otherwise)
- [x] 3.5 Two writers (`lease_held`), busy (`busy {job_id}`), `wait_idle` timeout failure
- [x] 3.6 Unreadable operation records produce `outcome_unknown` and no execution

## 4. Acceptance
- [x] 4.1 Every §3 test green on the local CPU lane (decision 200 replaces the hosted CPU lane; GPU tests skip there with an explicit reason) and in a local run on the owner's machine (decision 028; the local run report is the evidence); results attached to `phase2.4_supervisor-worker`

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
- [x] 5.2 Write tests covering the new behavior
- [x] 5.3 Run tests and confirm they pass

## 6. Notes (scope splits and evidence)
- 1.1: left open on purpose. phase1.25_pilot-wand is not accepted yet (Phase 1/G1).
- 2.1, 2.7: the lease is keyed by project UUID and held in the ledger. Stdio sessions hold it implicitly; phase2.5 gives HTTP clients explicit owners on the same table. Two writers are tested at the admission component with two owners, because the `.uzp.lock` sidecar already refuses a second worker on the file. `busy {job_id}` refuses a conflicting mutating call instead of queueing it, and the `wait_idle {timeout}` timeout is the error `timeout` (decision 139).
- 2.3-2.5: the decision itself was already in the project store (`DecideStored`, phase1.8). The worker now applies it before any mutating handler runs. A typed tool submits the client's request unchanged (`Session::Submit`). `run_python` is a script, not a transaction (11 §6), so its key gets no row and its retry follows the unknown-key rule. Until phase2.6 delivers typed tools, the Debug-only `test_mutation` stands in for them (decision 138). The omission rule of 11 §4 is implemented (decision 138).
- 2.6: reconciliation runs once per project epoch (each relaunch and each project switch) through `worker/operations`, before the first call of the epoch. The watermark is contiguous, and unreadable rows give `outcome_unknown` (decision 139).
- 2.8: every reply carries `receipt`: project, project UUID, texture set, job, revision, committed revision, and for a mutation the key, its source, the precondition, the request hash and the admission.
- 3.1-3.6, 5.3 (local run 2026-10-12, worktree `wt/p2-admission-ledger`, `UZP_NO_GPU=1`, Vulkan workers without a device): `python -m pytest tests/supervisor` gave 66 passed and 4 skipped (the DX12 GPU tests, skipped under `UZP_NO_GPU`), exit 0, in 61 s. The new files are `test_admission.py` (6), `test_worker_admission.py` (3) and `test_supervisor_admission.py` (3).
- 4.1: open. The local CPU run above is green. Still open: the hosted CPU lane, which runs on the owner's push, and attaching the results to phase2.4_supervisor-worker.
- 4.1 (attachment, 2026-10-12): the local results are attached to phase2.4_supervisor-worker in `parity/reports/phase2/supervisor-settling.md`. The parent's CPU run on the merged tree repeats this task's `tests/supervisor` cases (81 passed, exit 0). The hosted CPU lane is still open.
- 4.1 (Decision 200 (2026-10-13): the owner removed the hosted Parity CI; the local CPU lane on the owner's machine (the coordinator's full gate before the owner pushes) replaces it.): the hosted lane was this item's only open condition. Met by the local CPU-lane runs on the owner's machine (66 passed, 4 skipped, exit 0; the parent's merged-tree run 81 passed, exit 0), attached to phase2.4 in `parity/reports/phase2/supervisor-settling.md`.
