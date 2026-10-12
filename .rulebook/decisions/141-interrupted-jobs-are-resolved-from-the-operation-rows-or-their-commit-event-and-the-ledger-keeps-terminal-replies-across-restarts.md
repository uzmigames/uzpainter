# 141. Interrupted jobs are resolved from the operation rows or their commit event, and the ledger keeps terminal replies across restarts

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase2.3_supervisor-jobs, phase2.4_supervisor-worker, phase2.5_mcp-transport-registry

## Context

phase2.3 asks for two things:

- A job interrupted by a worker death is marked `interrupted`, and its outcome is resolved from the persisted operation records without running it again.
- Terminal states stay readable after a supervisor restart.

The phase2.2 ledger (decision 139) required an idempotency key in its `job` table, and it checked a lease holder's liveness by process id only.

This decision shares its panel round with decision 140:

- C4 (interruption): AGREE ×1 (Grok), PARTLY ×1 (Kimi), DISAGREE ×1 (GPT). Both dissents made the same point. An export's publication is a commit even though it creates no revision, so "no revision, therefore not committed" would be untrue when the worker dies after publishing.
- C5 (durability): PARTLY ×3. All three named process-id reuse, and pointed out that a dead supervisor does not prove a dead worker.

## Decision

1. **Resolution of an interrupted job.** The job is never run again. Its outcome is resolved as follows:

   | Job | Resolution |
   |---|---|
   | mutating, its key has an operation row | `{committed: true, committed_revision, source: operation_row}` |
   | mutating, its key has no row | `{committed: false, source: operation_row}` |
   | mutating, the rows are unreadable or another project is held | `{committed: null, source: operation_rows_unreadable}` |
   | long, its commit point reported (a `job_progress` event) | `{committed: true, what, source: job_event}` |
   | long, no commit point | `{committed: false, source: no_commit_point}` |
   | long, commit point not reported | `{committed: null, source: no_commit_event, commit_point}` |

   - A mutating job's rows are the ones the relaunched worker's reconciliation reads.
   - The "no row" answer is given only after a reconciliation of the same project in the current epoch has succeeded. The job's revision cannot have been acknowledged before that, because an interrupted call acknowledges nothing (GPT).
   - An export's own record is its publication pointer. An export interrupted before its commit event is reported as unknown, and `uzpainter export --recover` completes or discards its generation (decision 097). This replaces the dossier's `{committed: false, source: no_revision}` (GPT, Kimi).
2. **Ledger.**
   - `job` gains `long`, `supervisor`, `progress`, `message`, `committed`, `cancel_requested`, `reply` (the terminal reply with its receipt) and `resolution`.
   - Its key and key source become nullable, because a long read has neither.
   - The file is versioned with `PRAGMA user_version` (1). A version 0 file is migrated in place in one transaction: the table is rebuilt and its rows kept.
3. **Restart.**
   - Each job row names its supervisor as `<pid>:<process creation time>`, so a reused process id is not taken for it (all three).
   - When a supervisor starts, it durably marks the running jobs of supervisors that have ended as `interrupted`, with `{committed: null, source: supervisor_ended}`. This state is written, not made up when a query reads the row (GPT).
   - The worker of a dead supervisor cannot outlive it. It waits on the supervisor's process and terminates itself, committing nothing further (02 §5). The existing design therefore already covers the panel's concern that the worker may still be running.
   - When the next reconciliation of the project finds such a job's key in the operation rows, it resolves the job as committed. The "no row" answer is not given here, because the acknowledgement may already have passed the job's revision.
   - `job_status`, `job_result` and `job_list` read finished jobs from the ledger.

## Alternatives Considered

- **Write an operation row for an export's publication.** Rejected: an export changes no project revision, and an operation row is defined as atomic with one.
- **Probe for an orphaned worker before marking its jobs.** Rejected: by construction, the worker ends with its supervisor.

## Consequences

- phase2.5's HTTP clients reuse the same rows, and their reconnects read the same terminal replies.
- An interrupted export may stay `committed: null` until `export --recover`, or a look at its pointer, settles it.
