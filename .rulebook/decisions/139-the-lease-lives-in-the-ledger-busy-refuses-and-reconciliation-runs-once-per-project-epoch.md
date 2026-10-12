# 139. The lease lives in the ledger, busy refuses, and reconciliation runs once per project epoch

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase2.2_supervisor-admission-ledger, phase2.3_supervisor-jobs, phase2.5_mcp-transport-registry, phase2.4_supervisor-worker

## Context

phase2.2 asks for four things:

- a mutation lease per project (`lease_held {holder, since, active_job}`);
- a durable supervisor ledger;
- `busy {job_id}` and `wait_idle {timeout}`;
- reconciliation from the operation rows newer than the last acknowledged revision before any call is admitted.

Stdio mode has exactly one client. The multi-client HTTP mode is phase2.5. The `.uzp.lock` sidecar already keeps a second worker off the same file. Panel round shared with decision 138: AGREE ×3 on C3 and C5. On C6, PARTLY ×2 (GPT, Kimi) and AGREE ×1 (Grok). GPT and Kimi each named one refinement, adopted in item 3 below.

## Decision

1. **Ledger.**
   - The ledger is one SQLite file, `%LOCALAPPDATA%\UzPainter\supervisor\ledger.sqlite3`, or `--ledger <file>`. It runs in WAL mode, and several supervisors may share it.
   - It has four tables: `lease`, `job`, `acknowledgement` and `outcome`. They are keyed by the project UUID, the scope of its keys.
   - It is a control-plane record. The operation rows stay the authority. Deleting the ledger loses no project state, and the next reconciliation refills it.
2. **Lease.**
   - There is one lease per project UUID. The stdio session holds it implicitly (`stdio:<supervisor pid>`) from its first mutating call, and gives it up when it closes.
   - A lease whose holder process has ended is taken over.
   - Another owner's mutating call is refused with `lease_held {holder, since, active_job}` before it reaches the worker. Reads need no lease.
   - Two writers are tested at the admission component with two owners, not through two supervisor processes. phase2.5's HTTP clients reuse that component.
3. **Reconciliation.**
   - The supervisor counts project epochs. A new epoch starts with every worker relaunch and every change of the project the worker holds.
   - Before the first call of an epoch, it reads `worker/operations {after: <acknowledged revision>}` and records the rows as outcomes. It then sets the acknowledgement to the current revision the same read returned. That makes the watermark contiguous: GPT's refinement.
   - After that, every reply committed in the same epoch moves the acknowledgement forward, because every commit in the epoch passed through this supervisor.
   - If the rows cannot be read, mutating calls for the project fail with `outcome_unknown {committed_revision}` until a reconciliation succeeds. `committed_revision` is the revision the worker last reported, not a guess about the call: Kimi's refinement.
   - A key whose own row does not decode is `outcome_unknown`. Other keys are still admitted.
   - A call admitted before a worker death and held through the relaunch is still decided by the worker against the rows.
4. **Busy.**
   - A mutating call while another mutating call of the same project runs returns `busy {job_id}` and is not queued. Reads are not refused.
   - `wait_idle {timeout}` (seconds) waits until no mutating call runs. A timeout is the error `timeout`.
   - Each admitted mutating call is a ledger job (`running` → `succeeded`, `failed` or `interrupted`). phase2.3 adds long jobs and `cancelled`.
5. **Receipts.** Every forwarded call returns `receipt` with these fields:
   - always: `tool`, `project`, `project_uuid`, `texture_set`, `job_id`, `revision` (the revision the call was admitted on) and `committed_revision`;
   - for a mutating call, also: `idempotency_key`, `key_source`, `expected_revision`, `request_hash` and `admission`.

## Alternatives Considered

- **Two supervisor processes as the two writers.** Rejected: the project lock already refuses the second worker, so the lease would never be reached.
- **Queueing a conflicting call.** Rejected: INT-05 asks for an explicit busy state.
- **Reconciling only after a relaunch.** Rejected: a project opened from a file another supervisor changed has commits this ledger never saw.

## Consequences

- phase2.3 stores its terminal job states in the `job` table.
- phase2.5 gives HTTP clients explicit owners on the same lease table.
- The INT-07 "round" identity belongs to the pilot rounds, not to this receipt.
