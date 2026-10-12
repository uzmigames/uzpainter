# 140. Long tools run as native jobs on the worker, with a commit point and a receipt that says where they stopped

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase2.3_supervisor-jobs, phase2.6_mcp-typed-tool-families, phase2.8_mcp-server, phase2.4_supervisor-worker

## Context

phase2.3 asks for:

- jobs with unique ids, returning `{job_id, status}` at once, or with `wait=true` streaming progress notifications;
- cancellation at tile and file boundaries, with a receipt that says whether work stopped before or after its commit;
- job queries in the supervisor, and `uzpainter.jobs` over the same model;
- a result schema with no success on partial results and no-op distinct from failure.

Facts measured before deciding:

- The worker answers one request at a time on its command thread. Its pipe writes are thread-safe, and its reader thread is separate.
- `uzpainter.jobs` already runs the export on a native job-pool thread with checkpoints and the statuses `queued | running | succeeded | failed | cancelled`.
- The worker had no export tool and no long typed tool. phase2.6 owns the typed families (`export`, `bake_start`, `mesh_reload`, `capture`, `project_create`, the `job_*` and `lease_*` groups).

The model panel (one round: GPT-6 Astra, Kimi K3, Grok 4.5) voted on seven claims:

| Claim | Vote |
|---|---|
| C1 (surface) | AGREE ×2, PARTLY ×1 |
| C2 (execution) | AGREE ×1, PARTLY ×2 |
| C3 (cancellation) | AGREE ×2, PARTLY ×1 |
| C6 (native) | AGREE ×2, PARTLY ×1 |
| C7 (result schema) | AGREE ×2, PARTLY ×1 |

The refinements adopted are named below. This decision records C1, C2, C3, C6 and C7; decision 141 records C4 and C5.

## Decision

1. **Surface.**
   - The worker lists a tool as `long`, with its `commit_point` (`revision`, `publication` or none). There are three such tools:
     - `project_open`, with no commit point;
     - a minimal `export {config, fixed_names?}`, whose commit point is `publication`;
     - the Debug-only `test_job {name, steps, step_ms?, commit_at?}`, whose commit point is `revision`. It stands in for phase2.6's long typed tools, in the pattern of decision 138's `test_mutation`.
   - A long call returns `{job_id, status: "running"}` at once. With `wait: true` it returns the terminal reply.
   - Progress goes out as standard `notifications/progress`, and only on the request's progress token (Kimi). Each one carries `{job_id, status, progress, message}` under `_meta["uzpainter/job"]`.
   - When the client cancels a waiting request, the job is cancelled too (Kimi).
   - The supervisor serves `job_status`, `job_result`, `job_cancel` and `job_list` now. phase2.6 registers them in its family registry and adds `lease_*`. It also extends `export` with presets, overrides and the dry run.
2. **Execution.**
   - The worker runs a long tool's body as a native `uzpainter.jobs` job on the job pool while its command thread waits. It still serves one call at a time, so a read sent during a long job is answered after it (documented; Kimi).
   - The job's progress and its commit point reach the supervisor as `job_progress` events.
   - A long job holds its project's running slot like a mutating call: another mutating call or long job meanwhile gets `busy {job_id}`. Reads are forwarded. `wait_idle` waits for long jobs too.
3. **Cancellation.**
   - `job_cancel` records the request and sends `worker/cancel {job_id}`.
   - The worker's pipe reader thread answers at once with `state: running | pending`. The answer means the request was accepted, not that the job stopped (GPT).
   - A cancel that arrives before the job starts is kept, and the job stops at its first checkpoint.
   - The checkpoints are:
     - every tile the CPU evaluator allocates during an export (a tile-store wrapper refuses the next tile);
     - before every export file;
     - before every fixed-name folder;
     - every `test_job` step.
   - No checkpoint lies between a commit and the record of its commit point (GPT).
   - The native job records its commit point with `JobContext::Commit(what)` the moment the change is durable: an export's generation after its publication, a mutation's revision.
4. **Receipt and result schema.**
   - The worker's job receipt is `{id, kind, status, progress, message, committed, stopped, cancel_requested, no_op}`. The supervisor's terminal receipt adds `status` and this `job`.
   - `stopped` is null for a success that no cancel was asked of. Otherwise it is `after_commit` when the job committed and `before_commit` when it did not. A job without a commit point is never labelled `after_commit` (GPT).
   - A job is `succeeded` only when its body ran to the end.
   - A job that committed and then failed or was cancelled is `failed` or `cancelled`, with `committed` naming what stayed durable.
   - A cancel that arrives after the last checkpoint leaves the job `succeeded`, with `cancel_requested: true` and `stopped: after_commit` (Kimi).
   - `no_op: true` appears only on a success that committed nothing and whose body said so explicitly (`JobContext::NoOp`). It is never inferred from a missing revision (GPT, Kimi).
5. **Single process.**
   - `uzpainter.jobs.Job` gains `message` and `receipt()`, with the same fields.
   - There is no `interrupted` in one process, because the process dies with its job.

## Alternatives Considered

- **Reply `running` from the worker at once and send the terminal state as an event** (Grok's alternative), so reads are served during a long job. Rejected for now: it lets the job thread and the command thread touch the session at the same time. phase2.4 can revisit it with the preview thread.
- **Wait for phase2.6 before adding any long tool.** Rejected: the acceptance needs a long export and a project open, and the job path is the same for every long tool.
- **Report a cancel after commit as `succeeded`.** Rejected: the remaining work did not run, so the result is partial.

## Consequences

- phase2.6's long typed tools declare `long` and a commit point, and need no further job plumbing.
- A slow export blocks reads until it ends. Clients poll `job_status`, which never reaches the worker.
- Tile cancellation covers the CPU evaluator. GPU evaluation and bakes add their own checkpoints when they become long jobs.
