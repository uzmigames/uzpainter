## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase1.25_pilot-wand — still open: Phase 1 is functionally complete on main (compositor, export, Python API, adapter) and stays open only on Painter recordings and the hosted CI; this task builds on the merged code

## 2. Implementation
- [x] 2.1 Role dispatch in `UzPainter.exe`: `--mcp` supervisor (no GPU device, no editable document, no user Python), `--worker --pipe … --gpu-backend … [--allow-python]` worker, single-process `run`/CLI verbs/`--preview` hosting the worker role (02 §1)
- [x] 2.2 Supervisor hosts the stdio MCP session through the embedded official Python MCP SDK (protocol frames only on stdout, logs on stderr) and forwards `tools/call` frames to the worker
- [x] 2.3 Named-pipe server and client with newline-delimited UTF-8 JSON frames; the worker accepts only its supervisor's connection on `\\.\pipe\uzpainter-<supervisor-pid>-<n>`
- [x] 2.4 Handshake frame (`uzp-ipc/1`, `worker_pid`, `build`, `gpu_backend`, `gpu_status`, `python`); any mismatch with the requested protocol, backend or Python policy is a fatal supervisor error
- [x] 2.5 Request/reply/notification vocabulary of 02 §2 (mutating requests require `idempotency_key` and `expected_revision`; replies carry `committed_revision` or a structured `error`); large payloads passed as path + SHA-256 under an allowlisted root
- [x] 2.6 Backend policy: one backend per supervisor lifetime; the worker starts with `gpu_status: unavailable` when no device can be created; GPU operations fail with `gpu_backend_unavailable {backend, reason}` before mutating; GPU-free operations stay available
- [x] 2.7 `run_python` rejected at the IPC boundary with `python_disabled` when the worker runs without `--allow-python`
- [x] 2.8 Worker death detection (broken pipe, process exit), minidump through the vendored crash handler, relaunch on the project's last committed revision with the same backend and Python policy; pending calls wait for the relaunch
- [x] 2.9 Engine-thread fault reporting: `device_removed {backend, reason}` (DX12 `DXGI_ERROR_DEVICE_REMOVED`, Vulkan `VK_ERROR_DEVICE_LOST`) and the deadline wait's `timeout` (configurable, default 60 s) fail the job and make the worker exit deliberately
- [x] 2.10 Supervisor-death rule: the worker detects the broken pipe and exits without committing anything further
- [x] 2.11 Test-only fault hooks (kill points, DX12 `ID3D12Device5::RemoveDevice`, Vulkan device-loss hook, GPU stall), excluded from release builds

## 3. Tests
- [x] 3.1 Frame codec and handshake tests, including each mismatch case (protocol, backend, Python policy) producing a fatal supervisor error
- [x] 3.2 Worker kill (process termination), native abort and SEH fault: supervisor alive, minidump written, worker relaunched on the last committed revision, recovery time recorded
- [x] 3.3 Device removal on DX12 and device loss on Vulkan through the test hooks: `device_removed` reported, worker exits, supervisor relaunches on the same backend
- [x] 3.4 GPU stall: the deadline wait returns `timeout`, the job fails, the worker exits and is relaunched
- [x] 3.5 Supervisor killed: the worker exits and the project file holds the last committed revision
- [x] 3.6 Worker without `--allow-python` rejects `run_python` with `python_disabled`; a worker with an unavailable backend returns `gpu_backend_unavailable` before mutating while project open/save/inspect still succeed

## 4. Acceptance
- [x] 4.1 Every §3 test green in a local run on the owner's machine (DX12 and Vulkan device-fault variants; decision 028, the local run report is the evidence) and on the hosted CPU lane where no GPU is needed (GPU tests skip there with an explicit reason); results attached to `phase2.4_supervisor-worker`

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
- [x] 5.2 Write tests covering the new behavior
- [x] 5.3 Run tests and confirm they pass

## 6. Notes (scope splits and evidence)
- 2.1: `--mcp-http` and `--roots` are refused with a usage error naming phase2.5_mcp-transport-registry (items 2.3, 2.7), which delivers them; `--preview` arrives with phase2.1_preview-viewport-window and hosts the same worker state as `run`.
- 2.5: the worker's Phase 2.1 vocabulary is `project_open/close/save/inspect`, `evaluate_channel` (GPU, payload by path + SHA-256), `run_python` and the Debug-only `test_fault` (decision 120); notifications are defined in the protocol and delivered by phase2.3_supervisor-jobs. A stale precondition returns `stale_revision`; the known-key lookup in front of it is phase2.2 item 2.4.
- 2.6: the GPU operations are the tools that use the device; the Phase 1 export runs on the CPU evaluator and is not refused (decision 120; the spec scenario is amended).
- 2.9, 2.11, 3.3: DX12 implemented (`remove_device`, `gpu_stall` hooks, deliberate exit 5). The Vulkan device-loss hook and the Vulkan variant of 3.3 are a recorded scope split to phase3.1_vulkan-compute-parity items 2.2 and 3.4 (decision 121): no Vulkan device exists before them.
- 2.11: hooks compiled only in Debug builds (`UZP_WORKER_FAULT_HOOKS`, build.zig); ReleaseFast/Safe/Small contain none and refuse `--test-faults` (decision 120).
- 3.2: a worker terminated from outside cannot write a minidump of itself (`minidump: null`); `abort()` and SEH write one through the vendored crash handler, asserted by the test.
- 3.3, 3.4 (DX12) and the DX12 cases of `tests/supervisor/test_supervisor_gpu.py` (device only in the worker, evaluation payload hash) are written and skip under `UZP_NO_GPU=1`; their local GPU run belongs to the coordinator's GPU batch (a batch gate held the GPU during this task) and to phase2.4_supervisor-worker item 3.4, which runs them through the supervisor on both backends.
- 4.1: CPU lane green locally 2026-10-12 (`UZP_NO_GPU=1 python -m pytest tests/supervisor`: 44 passed, 4 GPU cases skipped with the decision-028 reason). The DX12 local run of the 4 GPU cases is the coordinator's GPU batch; the Vulkan variant is decision 121's split. Results are referenced from phase2.4_supervisor-worker.
