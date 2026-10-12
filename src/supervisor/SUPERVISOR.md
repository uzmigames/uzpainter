# Supervisor and worker (`src/supervisor/`, `python/uzpainter_supervisor/`)

This folder holds the process boundary of `docs/architecture/02-runtime-topology.md` §1, §2 and §5 (task `phase2.1_supervisor-ipc-worker`, decisions 120 and 121) and the command admission of §3 (task `phase2.2_supervisor-admission-ledger`, decisions 138 and 139). One executable has two roles:

| Role | Command | Code |
|---|---|---|
| Supervisor | `UzPainter.exe --mcp [--gpu-backend dx12\|vulkan] [--allow-python] [--gpu-deadline-ms <ms>] [--output-root <dir>] [--crash-dir <dir>] [--ledger <file>] [--test-faults] [--preview]` | `supervisor.{h,cpp}` starts the embedded interpreter and calls `uzpainter_supervisor.main.main` |
| Worker | `UzPainter.exe --worker --pipe \\.\pipe\uzpainter-<supervisor-pid>-<n> --gpu-backend dx12\|vulkan [--allow-python] [--gpu-deadline-ms <ms>] [--output-root <dir>] [--crash-dir <dir>] [--connect-timeout-ms <ms>] [--test-faults] [--preview]` | `worker.{h,cpp}`, `pipe.{h,cpp}`, `ipc.{h,cpp}`, `fault_hooks.{h,cpp}` |
| Single process | `UzPainter.exe run`, the CLI verbs | hosts the worker's state (the `Session`, the interpreter) directly, `src/python/run.h` |

`--mcp-http` and `--roots` are refused with a usage error that names `phase2.5_mcp-transport-registry`, the task that delivers them.

## Supervisor

`uzpainter_supervisor` runs inside the embedded interpreter, on the pinned MCP SDK (`thirdparty/python-wheels/`):

- **`main.py`** parses the command line and serves the stdio MCP session through the SDK's low-level `Server` and `stdio_server`. While the session runs, stdout carries protocol frames only. Logs go to stderr, and the worker's own stdout is sent to stderr.
  - `tools/list` returns the worker's tools plus `supervisor_status` and `wait_idle`.
  - `tools/call` goes through the admission (below) and is then forwarded to the worker. A mutating call may carry `idempotency_key` and `expected_revision` among its arguments, and the supervisor lifts them into the pipe request.
  - The final MCP contract belongs to phase2.5-phase2.8: the registry, schema validation, roots, HTTP, resources and prompts.
- **`admission.py`** admits every call, and **`ledger.py`** is the durable ledger (see Admission).
- **`worker.py`** owns the worker lifecycle:
  - It launches generation `n` with the same backend, Python policy and deadline every time.
  - It connects with asyncio's overlapped named-pipe client and checks the handshake.
  - It holds new calls while a relaunch is under way.
  - It records each recovery in `supervisor_status`.
- **`ipc.py`** holds the frame codec, the handshake check and the worker's exit codes. It uses the standard library only, so `tests/supervisor/test_ipc_codec.py` imports it directly.

The supervisor never creates a GPU device, never opens a project and never runs user Python.

### Handshake

The worker speaks first: `{"protocol":"uzp-ipc/1","worker_pid","build","gpu_backend","gpu_status":"ready|unavailable","python":"allowed|disabled"}`.

A different protocol, backend or Python policy, or a malformed field, is a fatal supervisor error. There is no fallback. The supervisor logs `fatal supervisor error: worker handshake mismatch: …`, ends the worker and exits with status 4. At start-up this happens before any MCP frame is written. After a relaunch it happens before any further call is admitted.

### Recovery

The supervisor detects a worker's end from the process exit or from a broken pipe. After a broken pipe it gives the worker 10 s to exit, then kills it. The cause comes from the exit code:

| Exit | Cause |
|---|---|
| `0x40000015` (`abort()` through the SIGABRT handler) | `abort` |
| `0xC…` NTSTATUS (an SEH exception the crash handler reported) | `native_fault` |
| 5 | `device_fault` (`fault_code` names the `device_removed` or `timeout` reply that preceded it) |
| 4 | `supervisor_gone` |
| 2, 3 | `start_failed` |
| anything else | `terminated` (killed from outside) |

The supervisor then:

1. Takes the minidump from `<crash-dir>/<supervisor-pid>-<n>/crashes/<time>/crash.dmp`, if there is one. A process terminated from outside writes none, and its record says `minidump: null`.
2. Launches generation `n+1` with the same backend and Python policy.
3. Reopens the store the worker held with the pipe method `worker/reopen {path, untitled}` (not a tool). That is the saved file, or an untitled project's temporary store, which is reopened as untitled. Because every commit is a durable revision, the store holds the last committed revision. The reopen is raced against the new worker's end. A worker that dies during the reopen is replaced, up to three launches; after that the supervisor stops with the fatal error `recovery failed` (exit 4).
4. Answers every call that was in flight with `interrupted {cause, exit_code, fault_code, committed_revision}`. Such a call is never re-sent: recovery is never a silent replay. The client retries it with the key and precondition its receipt names (see Admission).
5. Records `{generation, cause, exit_code, fault_code, minidump, old_pid, new_pid, project, revision, recovery_ms, attempts, failed_attempts}`. `recovery_ms` runs from the detected death to the reopened project.

The supervisor learns which project to reopen from the worker's `revision` events: `{"event": "revision", "revision", "project", "project_uuid", "untitled"}`. `project` is the absolute durable store: for a saved project the native `Session`'s effective identity (`OpenProject::project_source`, the absolute store file after open or `save_as`, so a bundle directory's imported `<dir>.uzp`), and for an untitled project its temporary store. It is null when no project is open, and so is `project_uuid`, the scope of the project's idempotency keys. The worker sends one after every committed call and every project switch (create, open, close, `save_as`), from `Session::on_durable_change`, before the call that caused it returns. So a script that switches projects and commits, then loses its reply to a crash, is recovered on the project it really holds.

## Admission

`admission.Admission` runs for every `tools/call` (02 §3, 11 §4; decisions 138 and 139).

1. **Reconciliation.** The supervisor counts project epochs. A new one starts with every relaunch and with every change of the project the worker holds.
   - Before the first call of an epoch, the supervisor sends the pipe method `worker/operations {after}`. `after` is the revision it last acknowledged for that project.
   - The reply is `{project_uuid, current_revision, horizon_revision, operations, unreadable}`. The supervisor records the rows in the ledger and acknowledges the current revision.
   - Each committed reply in the same epoch then moves the acknowledgement forward.
   - If the rows cannot be read, every mutating call for the project fails with `outcome_unknown {committed_revision}` until a later reconciliation succeeds. Reads are still forwarded.
   - A key whose own row does not decode is `outcome_unknown`.
2. **Key and precondition (the omission rule):**

   | The client sends | The supervisor |
   |---|---|
   | neither | generates `sup-<uuid>` and resolves the precondition once from the reconciled revision (0 with no project open) |
   | a precondition only | generates the key |
   | a key only | forwards it without a precondition: the worker returns its stored outcome or `outcome_unknown`, and never runs it |

3. **Lease.** There is one mutation lease per project UUID, held in the ledger.
   - The stdio session takes it implicitly (`stdio:<supervisor pid>`) at its first mutating call, and releases it on exit.
   - A lease whose holder process has ended is taken over.
   - A mutating call from another owner returns `lease_held {holder, since, active_job}`. Reads need no lease.
   - phase2.5 gives HTTP clients their own owners.
4. **Busy.** A mutating call while another mutating call of the same project runs returns `busy {job_id}`; it is not queued. `wait_idle {timeout}` (seconds) waits until no mutating call runs, and a timeout is the error `timeout`.
5. **Job.** Each admitted mutating call is a ledger job: `running`, then `succeeded`, `failed` or `interrupted`.
6. **Receipt.** Every reply carries `receipt`:
   - always: `tool`, `project` and `project_uuid` (what the worker holds afterwards), `texture_set` (named in the arguments or returned), `job_id`, `revision` (the revision the call was admitted on) and `committed_revision`;
   - for a mutating call, also: `idempotency_key`, `key_source` (`client` or `supervisor`), `expected_revision`, `request_hash` and `admission` (`executed` or `stored_outcome`).

**Ledger.** The ledger is a SQLite file in WAL mode: `%LOCALAPPDATA%\UzPainter\supervisor\ledger.sqlite3`, or `--ledger <file>`. It has four tables: `lease`, `job`, `acknowledgement` and `outcome`.

- It is a control-plane record. The project store's `operation` rows are the authority on what committed.
- Absence from the ledger never proves that a mutation did not commit.
- Deleting the ledger loses no project state.

`supervisor_status` reports the ledger path, the project's lease, the running calls and the acknowledged revision.

## Worker

The worker starts in this order:

1. It installs the crash reporting:
   - the vendored crash handler (`thirdparty/uzengine-render-core/platform/windows/crash_handler.h`), with its directory set by `--crash-dir`;
   - a SIGABRT handler that turns `abort()` into the exception `0x40000015`, so the handler writes a minidump for it;
   - no Windows error dialogs.
2. It opens a handle on its supervisor's process.
3. It creates the pipe (`pipe.h`): the first and only instance of its name, remote clients refused, a DACL for the current user only, overlapped I/O.
4. It starts the engine thread for the requested backend. Without a device it still starts, with `gpu_status: unavailable`.
5. It starts the embedded interpreter.
6. It accepts only the client whose process id the pipe name carries. Any other client is disconnected. The connect deadline and the supervisor's process are checked before every attempt.
7. It sends the handshake.

It then answers one request at a time on the interpreter's thread. The GIL is held only while `run_python` runs.

| Tool | Kind | Result |
|---|---|---|
| `project_open {path}` | GPU-free | `{path, revision}` |
| `project_close` | GPU-free | `{}` |
| `project_save {mode?: incremental\|full}` | GPU-free, names a checkpoint | `{current, named, previous}` |
| `project_inspect` | GPU-free | `{open, path, revision, texture_sets: [{name, stacks}]}` |
| `evaluate_channel {channel, texture_set?, stack?}` | GPU (the GPU evaluator on the engine thread) | `{revision, texture_set, stack, channel, format, width, height, tiles, payload: {path, sha256, size}}`; the texels go to a file under `--output-root` |
| `snapshot_layer_tree` | GPU-free | the layer-tree snapshot of the committed revision (`uzp_core/document/layer_tree.h`) |
| `diff_snapshots {before, after}` | GPU-free | the nodes and stacks added, removed and modified between two snapshots |
| `isolate_layer {uid, channels, path}` | GPU-free (CPU evaluator, as the export) | `{revision, uid, was_visible, export}`: the sources `isolated/<channel>/<uid>` published as an export generation (OpenEXR 32f, padding `passthrough`) under `path` |
| `material_views {mask, path}` | GPU-free | `{revision, material, inside, views: {view: {leak_count, modal_id}}, missing, refused, export}`: the material's mask and each view with its leaks published the same way |
| `region_stats {mask, map}` | GPU-free | `{source, revision, stats}`: the statistics the export writes for `regionStats/<map>/<mask>` |
| `display_get` | GPU-free | `render.display.state()`: the preset's fields, `parity` and the shader (`src/python/display.h`, decision 132) |
| `display_set {preset?, environment?, exposure?, rotation?, opacity?, blur?, shadows?, background?, color_lut?}` | mutating: the lease, key and precondition; one transaction (the preset first) | the transaction result, stored for the key (`display_get` reads the state); a value outside the fixed pipeline fails `call_failed` (`UnsupportedInUzPainter`, decision 038) with nothing committed |
| `shader_get` / `shader_set {parameters}` | read / mutating (lease, key, precondition) | `shader_get`: `{shader, parameters}`, the setters return the transaction result; the default `open-pbr` instance; other values are refused (decision 042) |
| `camera_get` / `camera_set {camera \| blender}` | read / mutating (lease, key, precondition) | `camera_get`: `{camera, blender}`, the default camera in Painter's and Blender's conventions, null when none is set |
| `capture {mode, path, camera?, size?, samples?, seed?, preset?, texture_set?, stack?}` | non-mutating; listed `gpu: true`, but only `painter_viewport` needs the device (`gpu_backend_unavailable` otherwise), so the CPU modes run without one | the capture receipt with `files` (`src/python/capture.h`, decision 148). `path` is the PNG and lies inside `--output-root` (relative paths are taken under it); the OpenEXR and the receipt go beside it. `painter_iray` is `call_failed` with `details.type` `PathTracerUnavailable`, decided before the path is looked at. `texture_set` and `stack` apply to `base_color` and `channel:<name>` only |
| `run_python {code, args?}` | mutating; listed and run only with `--allow-python`; its MCP schema also takes `idempotency_key` and `expected_revision` | the `RunScript` report; a raising script is `script_failed`, with the calls it committed in `details` |
| `preview_status` | GPU-free; listed only with `--preview` | `{window_open, stalled, frames_published, frames_taken, frames_rendered, revision_shown, last_error}` of the attached preview (`src/preview/PREVIEW.md`) |
| `test_fault {fault}` | Debug builds under `--test-faults` only; `preview_stall` and `preview_resume` only with `--preview` (the stall hook of the preview thread) | `{armed}` |
| `test_mutation {name, fail?}` | mutating and typed (one transaction); Debug builds under `--test-faults` only (decision 138) | the committed `TransactionResult` (`{status, revision, committed_revision, created, ...}`). It inserts the fill layer `name` on the active stack. With `fail`, the call fails after its edit (`call_failed`) and commits nothing. |

The checks run in this order, and every refusal comes before the call runs:

1. `run_python` without `--allow-python` returns `python_disabled`.
2. An unknown tool returns `unknown_tool`.
3. A mutating call without a non-empty `idempotency_key`, or with an `expected_revision` that is not an integer, returns `invalid_request`.
4. A mutating call is decided against the open project's `operation` rows (`ProjectStore::Decide`, in the `DecideAdmission` order of `09-project-file-format.md` §4). The precondition is optional here; it is decided with the key.

   | Case | Reply |
   |---|---|
   | known key, same request hash | the stored outcome, with `admission: stored_outcome`, and nothing is mutated, even when the revision has moved on |
   | known key, another hash | `idempotency_conflict {key, committed_revision}` |
   | unknown key with a missing precondition or one below `meta.operation_horizon_revision`, or an unreadable row | `outcome_unknown {key, committed_revision}` |
   | unknown key, a revision other than the current one | `stale_revision {expected, current}` |

   - With no project open, a call without a precondition is `outcome_unknown`.
   - A typed tool then submits the same request through `Session::Submit`. Its operation row `{project_uuid, idempotency_key, request_hash, outcome, committed_revision}` is written in the transaction of its revision. `request_hash` is the SHA-256 of the canonical JSON of `{arguments, tool}`.
   - `run_python` is a script, not a transaction (11 §6). Each API call in it commits with its own key, so the script's key gets no row. A retry after the script committed is `stale_revision` (decision 138).
   - The reply of an executed mutating call carries `admission: executed` and its `request_hash`.
5. A GPU call on a worker without a device returns `gpu_backend_unavailable {backend, reason}`.

Replies carry `committed_revision` while a project is open. A bad frame gets `{"id": null, "error": {"code": "invalid_frame"}}`, and the worker keeps serving.

The Diagnostics tools (task phase2.1_recipe-diagnostic-views, decision 136) read the committed revision through `python::DiagnosticRun` (`src/python/diagnostics.h`), the code behind `uzpainter.diagnostics`. They are listed with `mutating: false`, so admission forwards them as reads: no lease, key, precondition or operation row. Their `path` must lie inside `--output-root`; a relative path is taken under it, and anything else is `invalid_arguments` until MCP roots exist (phase2.5). Each export is an ordinary generation with its plan and receipt, so a call never overwrites an earlier one.

In this task the GPU operations are exactly the tools that run on the engine thread (decision 120). The Phase 1 export computes on the CPU evaluator (decision 111), so it is not refused on a worker without a device. It joins the GPU set when it moves to the GPU evaluator.

The worker ends in four ways:

- **Device fault.** After a `device_removed` or `timeout` reply it exits with status 5.
- **Supervisor gone.** A broken pipe, or the end of the supervisor's process, terminates it at once with status 4, so nothing further is committed. SQLite's rollback journal keeps an interrupted commit atomic.
- **Start failure.** A pipe it cannot create, a supervisor that never connects or an interpreter that fails gives status 3.
- **Usage error.** Status 2.

## Test-only fault hooks (`fault_hooks.h`)

The hooks are compiled only when `UZP_WORKER_FAULT_HOOKS` is defined. `build.zig` defines it for Debug builds only. ReleaseFast, ReleaseSafe and ReleaseSmall contain none of the hook code and refuse `--test-faults` (decision 120). Even in a Debug build the hooks are inert unless the worker was launched with `--test-faults`.

| Fault | Effect |
|---|---|
| `kill` | The worker terminates itself (exit 77). |
| `abort` | `std::abort()`. |
| `seh` | A write through a null pointer. |
| `remove_device` | The next GPU call first runs `ID3D12Device5::RemoveDevice` on the engine thread and fails with `device_removed`. |
| `gpu_stall` | The next GPU call first makes the direct queue wait on a fence nothing signals, so the deadline wait returns `timeout`. |
| `kill_before_reply` | The next call runs and commits, then the worker dies before its reply. |

`UZP_TEST_HANDSHAKE`, a JSON object in the environment, replaces handshake fields for the mismatch tests. `UZP_TEST_KILL_ON_OPEN`, a file holding a count, makes `worker/reopen` terminate the worker while the count is above zero (decrementing it), so a worker can die while the supervisor reopens the project. The Vulkan device-loss hook waits for the Vulkan device, which phase3.1_vulkan-compute-parity items 2.2 and 3.4 deliver (decision 121).

## Tests

All tests are in `tests/supervisor/`:

- `test_ipc_codec.py` (pure Python) covers the codec, every handshake mismatch and the exit causes.
- `test_worker_pipe.py` runs the worker with the test process as its supervisor, on Vulkan, so no device is created. It covers the handshake, the Python gate, the unavailable backend, the precondition, script failures, protocol errors, refused clients, broken pipes and usage errors.
- `test_supervisor_mcp.py` drives the supervisor over stdio MCP. It covers stdout cleanliness, fatal mismatches, external kill, abort and SEH with their minidumps, a lost acknowledgement, calls held during a relaunch, and a killed supervisor.
- `test_admission.py` is pure Python, with a stand-in worker. It covers:
  - the lease with two owners;
  - busy and `wait_idle`;
  - reconciliation per epoch and unreadable rows;
  - the omission rule and receipts;
  - the durable ledger.
- `test_worker_admission.py` runs the worker through its pipe. It covers:
  - the known-key order, `idempotency_conflict` and `outcome_unknown`;
  - the request hash;
  - a failed mutation, which writes no row;
  - an unreadable row.
- `test_supervisor_admission.py` drives the supervisor over stdio MCP. It covers:
  - a lost acknowledgement answered with the stored outcome;
  - a replay beyond retention after compaction, with the ledger deleted;
  - busy, the lease and `wait_idle`.
- `test_worker_diagnostics.py` drives the Diagnostics tools on a saved project and compares their files and summaries with `uzpainter.diagnostics` on the same project.
- `test_supervisor_gpu.py` runs on DX12 and skips under `UZP_NO_GPU=1`. It checks that the device lives only in the worker, the evaluation payload by path and hash, and device removal and GPU stall with relaunch on the same backend.
