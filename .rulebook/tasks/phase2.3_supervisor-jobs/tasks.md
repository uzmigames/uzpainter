## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase1.25_pilot-wand, phase2.1_supervisor-ipc-worker, phase2.2_supervisor-admission-ledger

## 2. Implementation
- [x] 2.1 Job registry in the supervisor: unique job ids, `{job_id, status}` returned immediately, `wait=true` blocking with progress notifications
- [x] 2.2 Terminal states `succeeded | failed | cancelled | interrupted` persisted in the supervisor ledger
- [x] 2.3 Worker job pool cancellation checks at tile and file boundaries; cancel acknowledgement and a final receipt stating stop before or after commit
- [x] 2.4 `interrupted` resolution through reconciliation from the operation rows (outcome reported, never re-run)
- [x] 2.5 Job status, result, cancel and list queries in the supervisor API; native `uzpainter.jobs` (`Job.id/status/progress/wait/cancel`, `list()`) over the same model in the single-process path
- [x] 2.6 Result schema: no success on partial results; no-op distinguished from failure

## 3. Tests
- [x] 3.1 Job id uniqueness and progress stream with `wait=true` on a long export and a project open
- [x] 3.2 Cancel before commit and after commit: receipts state which happened; no partial result reported as success
- [x] 3.3 Worker killed during a long job: job marked `interrupted`, outcome resolved by reconciliation, no re-execution
- [x] 3.4 Supervisor restarted: terminal states of finished jobs readable from the ledger
- [x] 3.5 `uzpainter.jobs` tests in the single-process `run` path

## 4. Acceptance
- [x] 4.1 Every §3 test green; results attached to `phase2.4_supervisor-worker`

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
- [x] 5.2 Write tests covering the new behavior
- [x] 5.3 Run tests and confirm they pass

## 6. Notes (scope splits and evidence)
- Recordings: none. The task is UzPainter's own control plane; no Painter behaviour is reproduced.
- 1.1: left open on purpose. phase1.25_pilot-wand is not accepted yet (Phase 1/G1).
- 2.1, 2.5: the worker lists `long` tools with their `commit_point`: `project_open` (none), a minimal `export {config, fixed_names?}` (`publication`; phase2.6 adds presets, overrides and the dry run) and the Debug-only `test_job` (`revision`), the stand-in for phase2.6's long typed tools in the pattern of decision 138. A long call returns `{job_id, status: running}` at once, or with `wait: true` the terminal reply, streaming `notifications/progress` on the request's progress token with `{job_id, status, progress, message}` under `_meta["uzpainter/job"]`. The supervisor serves `job_status`, `job_result`, `job_cancel` and `job_list`; phase2.6 registers them in its registry and adds `lease_*`. A long job holds its project's running slot (`busy {job_id}`); the worker runs its body on the native job pool while its command thread waits (decision 140).
- 2.2: the ledger's `job` rows (schema version 1, migrated in place from version 0) keep each job's progress, commit point, cancel request, terminal reply and resolution, and name their supervisor by process id and creation time (decision 141).
- 2.3: `job_cancel` is acknowledged at once by the worker's pipe reader thread (`worker/cancel`). Checkpoints: every tile the CPU evaluator allocates during an export, before every export file and fixed-name folder, every `test_job` step. `JobContext::Commit` records the commit point (an export's publication, a mutation's revision); the receipt's `stopped` says `before_commit` or `after_commit` (decision 140). GPU evaluation and bakes add their own checkpoints when they become long jobs.
- 2.4: a mutating job is resolved from the operation rows the relaunched worker's reconciliation reads; a long read from its reported commit point; an export that died before reporting it stays `committed: null` until `uzpainter export --recover` (decision 141).
- 2.6: `succeeded` only when the body ran to its end; a job that committed and then failed or was cancelled reports `failed`/`cancelled` with `committed`; `no_op` marks an explicit no-op success.
- 3.1-3.5, 5.3 (local run 2026-10-12, worktree `wt/p2-jobs`, `UZP_NO_GPU=1`, Vulkan workers without a device): `python -m pytest tests/supervisor tests/capabilities/test_capabilities.py` gave 101 passed, 1 failed and 4 skipped (the DX12 GPU tests, skipped under `UZP_NO_GPU`), exit 1, in 82 s. The failure was the phase2.2 test's expected `busy` message, which now names long jobs; after the fix, that node with the native export-job tests (`test_pyapi_native.py` export cases) and `tests/python/test_capability_conformance.py` gave 8 passed, exit 0, in 139 s. The new tests are `test_supervisor_jobs.py` (5) and one more case in `test_admission.py`.
- 4.1: open. The local CPU run is green. Still open: the hosted CPU lane, which runs on the owner's push, and attaching the results to phase2.4_supervisor-worker.
- 4.1 (attachment, 2026-10-12): the local results are attached to phase2.4_supervisor-worker in `parity/reports/phase2/supervisor-settling.md`. The parent's CPU run on the merged tree repeats this task's `tests/supervisor` cases (81 passed, exit 0). The hosted CPU lane is still open.
- 4.1 (Decision 200 (2026-10-13): the owner removed the hosted Parity CI; the local CPU lane on the owner's machine (the coordinator's full gate before the owner pushes) replaces it.): the hosted lane was this item's only open condition. Met by the local CPU-lane runs on the owner's machine (the run above, then 8 passed, exit 0, after the message fix; the parent's merged-tree run 81 passed, exit 0), attached to phase2.4 in `parity/reports/phase2/supervisor-settling.md`.
