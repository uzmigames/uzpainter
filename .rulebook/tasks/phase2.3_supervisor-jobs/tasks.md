## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase1.25_pilot-wand, phase2.1_supervisor-ipc-worker, phase2.2_supervisor-admission-ledger

## 2. Implementation
- [ ] 2.1 Job registry in the supervisor: unique job ids, `{job_id, status}` returned immediately, `wait=true` blocking with progress notifications
- [ ] 2.2 Terminal states `succeeded | failed | cancelled | interrupted` persisted in the supervisor ledger
- [ ] 2.3 Worker job pool cancellation checks at tile and file boundaries; cancel acknowledgement and a final receipt stating stop before or after commit
- [ ] 2.4 `interrupted` resolution through reconciliation from the operation rows (outcome reported, never re-run)
- [ ] 2.5 Job status, result, cancel and list queries in the supervisor API; native `uzpainter.jobs` (`Job.id/status/progress/wait/cancel`, `list()`) over the same model in the single-process path
- [ ] 2.6 Result schema: no success on partial results; no-op distinguished from failure

## 3. Tests
- [ ] 3.1 Job id uniqueness and progress stream with `wait=true` on a long export and a project open
- [ ] 3.2 Cancel before commit and after commit: receipts state which happened; no partial result reported as success
- [ ] 3.3 Worker killed during a long job: job marked `interrupted`, outcome resolved by reconciliation, no re-execution
- [ ] 3.4 Supervisor restarted: terminal states of finished jobs readable from the ledger
- [ ] 3.5 `uzpainter.jobs` tests in the single-process `run` path

## 4. Acceptance
- [ ] 4.1 Every §3 test green; results attached to `phase2.4_supervisor-worker`

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
