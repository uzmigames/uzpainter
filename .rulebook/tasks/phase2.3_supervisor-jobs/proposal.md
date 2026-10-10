# Proposal: phase2.3_supervisor-jobs

## Why
Child of `phase2.4_supervisor-worker` (P2-SUPERVISOR in `docs/dag.md`), implementing the job model of D1 (`docs/architecture/02-runtime-topology.md` §3, §4, §5) as exposed by D10 (`docs/architecture/11-mcp-server.md` §3) and the native API (`docs/architecture/10-python-api.md` §7). Bakes, exports, captures, mesh reloads and project create/open are long operations; agents need job ids, progress and an unambiguous, durable terminal status, including when the worker dies mid-job. Requirements: BAK-05, INT-05, INT-07, QG-03, NFR-06 (`docs/prd.md`).

## What Changes
- Job model in the supervisor: long operations return `{job_id, status}` immediately, or with `wait=true` block until the terminal state while streaming `{job_id, status, progress 0..1, message}` notifications.
- Terminal states `succeeded | failed | cancelled | interrupted`, durable in the supervisor ledger; `interrupted` (worker died) is resolved by reconciliation from the project store's operation rows.
- Cancellation: `job_cancel` acknowledges intent; the worker's job pool checks cancellation at tile or file boundaries; the final receipt states whether work stopped before or after commit.
- Job queries: status, result, cancel and list at the supervisor (wired to the MCP `job_*` tools by `phase2.8_mcp-server`) and the native `uzpainter.jobs` module (`Job.id/status/progress/wait/cancel`, `list()`) for the single-process path.
- Receipts never report success on partial results and distinguish a no-op from a failure (QG-03).

## Dependencies
- Parent: `phase2.4_supervisor-worker`.
- Prerequisites: `phase1.25_pilot-wand`, `phase2.1_supervisor-ipc-worker` (notifications over the pipe, worker relaunch), `phase2.2_supervisor-admission-ledger` (durable ledger, reconciliation).

## Acceptance
- Unique job ids; `wait=true` streams progress and returns the terminal receipt.
- Cancelling before and after commit yields receipts that say which happened.
- Killing the worker during a long job marks it `interrupted`, and reconciliation resolves its outcome without re-running it.
- Terminal states remain readable after a supervisor restart.

## Impact
- Affected specs: `supervisor` (jobs)
- Affected code: supervisor job registry, worker job pool cancellation points, `uzpainter.jobs`
- Breaking change: NO
- User benefit: agents can track, wait for and cancel long operations with a truthful final status
