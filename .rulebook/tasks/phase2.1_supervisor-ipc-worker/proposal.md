# Proposal: phase2.1_supervisor-ipc-worker

## Why
Child of `phase2.4_supervisor-worker` (P2-SUPERVISOR in `docs/dag.md`), implementing D1 as specified in `docs/architecture/02-runtime-topology.md` §1, §2 and §5 (decision 003, with decisions 021, 022 and 025). In stdio MCP the AI client launches the server process and owns its pipes, so the launched process must be the one that survives faults: the vendored DX12 command list aborts the process after repeated RHI errors, device removal (DX12) or device loss (Vulkan) needs device re-creation, and GPU waits need a deadline. A worker death must not end the agent's MCP session. Requirements: ARC-01, INT-01, NFR-01, NFR-06 (`docs/prd.md`). This child delivers the process boundary: the two roles of one executable, the private pipe protocol and the worker lifecycle (launch, fault detection, relaunch).

## What Changes
- Role dispatch in `UzPainter.exe`: supervisor `--mcp [--mcp-http 127.0.0.1:<port>] [--roots …] [--allow-python] [--gpu-backend dx12|vulkan]`, which never initialises a GPU device, never holds an editable document and never executes user Python; worker `--worker --pipe \\.\pipe\uzpainter-<supervisor-pid>-<n> --gpu-backend dx12|vulkan [--allow-python]`, which accepts connections only from its supervisor; the single-process role (`run`, CLI verbs, `--preview`) hosts the worker role directly (02 §1).
- The supervisor hosts the stdio MCP session in its embedded CPython through the pinned official Python MCP SDK (stdout carries protocol frames only, logs go to stderr) and forwards `tools/call` frames to the worker; the tool registry, typed families, HTTP mode, roots, resources and prompts are delivered by `phase2.8_mcp-server`.
- Windows named-pipe transport with newline-delimited UTF-8 JSON frames and the handshake `{"protocol":"uzp-ipc/1","worker_pid","build","gpu_backend","gpu_status":"ready|unavailable","python":"allowed|disabled"}`; a mismatch with what the supervisor requested is a fatal supervisor error, never a silent fallback (02 §2).
- The request/reply/notification vocabulary of 02 §2: `tools/call` requests (mutating requests carry `idempotency_key` and `expected_revision`), replies with `committed_revision` or `error {code, message, details}`, job and revision notifications; images, maps and dumps travel as path + SHA-256 under an allowlisted root, never inline.
- GPU backend policy: one backend for the life of the supervisor; the worker still starts when no device of the requested backend can be created, and GPU operations then fail with `gpu_backend_unavailable {backend, reason}` before mutating anything while GPU-free operations stay available.
- Python policy at the pipe: a worker launched without `--allow-python` rejects `run_python` with `python_disabled`.
- Fault handling of 02 §5: minidump through the vendored crash handler (`thirdparty/uzengine-render-core/platform/windows/crash_handler.h`); worker death detected; relaunch on the project's last committed revision with the same backend and Python policy; `device_removed {backend, reason}` and the deadline wait's `timeout` (configurable, default 60 s per evaluation request) make the worker exit deliberately; on supervisor death the worker exits after committing nothing further.
- Test-only fault hooks (kill points, DX12 `ID3D12Device5::RemoveDevice`, Vulkan device-loss hook, GPU stall), excluded from release builds.
- Source files live in the layout fixed by `phase0.8_toolchain-slice` (`build.zig`).

## Dependencies
- Parent: `phase2.4_supervisor-worker` (integration and acceptance of P2-SUPERVISOR).
- Prerequisite: `phase1.25_pilot-wand` (the DAG input of P2-SUPERVISOR; through it the worker-side document, the project store with its `operation` table, the engine thread and the `run` path exist).
- Followed by the siblings `phase2.2_supervisor-admission-ledger` and `phase2.3_supervisor-jobs`, which build on this pipe and lifecycle.

## Acceptance
- Frame and handshake tests pass; every handshake mismatch (protocol, backend, Python policy) is a fatal supervisor error.
- Worker kill, native abort or SEH fault, DX12 device removal, Vulkan device loss and a GPU stall each leave the supervisor (and the MCP session it serves) alive, write the expected diagnostics, relaunch the worker on the last committed revision with the same backend and Python policy, and record the recovery time. The Vulkan device-loss case needs a Vulkan device and is settled by `phase3.1_vulkan-compute-parity` items 3.4 and 4.1 (decisions 121, 221); this task's acceptance covers the DX12 cases and the GPU-free cases on both backends.
- Without `--allow-python`, `run_python` is rejected at the IPC boundary with `python_disabled`.
- With an unavailable backend, GPU operations return `gpu_backend_unavailable` before mutating while GPU-free operations still run.

## Impact
- Affected specs: `supervisor` (process roles, IPC, fault recovery)
- Affected code: executable entry point and role dispatch, IPC module, worker lifecycle, engine-thread fault reporting, test fault hooks
- Breaking change: NO
- User benefit: an agent's MCP session survives GPU and native faults in the worker
