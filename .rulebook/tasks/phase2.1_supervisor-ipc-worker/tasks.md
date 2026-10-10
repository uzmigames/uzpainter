## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase1.25_pilot-wand

## 2. Implementation
- [ ] 2.1 Role dispatch in `UzPainter.exe`: `--mcp` supervisor (no GPU device, no editable document, no user Python), `--worker --pipe … --gpu-backend … [--allow-python]` worker, single-process `run`/CLI verbs/`--preview` hosting the worker role (02 §1)
- [ ] 2.2 Supervisor hosts the stdio MCP session through the embedded official Python MCP SDK (protocol frames only on stdout, logs on stderr) and forwards `tools/call` frames to the worker
- [ ] 2.3 Named-pipe server and client with newline-delimited UTF-8 JSON frames; the worker accepts only its supervisor's connection on `\\.\pipe\uzpainter-<supervisor-pid>-<n>`
- [ ] 2.4 Handshake frame (`uzp-ipc/1`, `worker_pid`, `build`, `gpu_backend`, `gpu_status`, `python`); any mismatch with the requested protocol, backend or Python policy is a fatal supervisor error
- [ ] 2.5 Request/reply/notification vocabulary of 02 §2 (mutating requests require `idempotency_key` and `expected_revision`; replies carry `committed_revision` or a structured `error`); large payloads passed as path + SHA-256 under an allowlisted root
- [ ] 2.6 Backend policy: one backend per supervisor lifetime; the worker starts with `gpu_status: unavailable` when no device can be created; GPU operations fail with `gpu_backend_unavailable {backend, reason}` before mutating; GPU-free operations stay available
- [ ] 2.7 `run_python` rejected at the IPC boundary with `python_disabled` when the worker runs without `--allow-python`
- [ ] 2.8 Worker death detection (broken pipe, process exit), minidump through the vendored crash handler, relaunch on the project's last committed revision with the same backend and Python policy; pending calls wait for the relaunch
- [ ] 2.9 Engine-thread fault reporting: `device_removed {backend, reason}` (DX12 `DXGI_ERROR_DEVICE_REMOVED`, Vulkan `VK_ERROR_DEVICE_LOST`) and the deadline wait's `timeout` (configurable, default 60 s) fail the job and make the worker exit deliberately
- [ ] 2.10 Supervisor-death rule: the worker detects the broken pipe and exits without committing anything further
- [ ] 2.11 Test-only fault hooks (kill points, DX12 `ID3D12Device5::RemoveDevice`, Vulkan device-loss hook, GPU stall), excluded from release builds

## 3. Tests
- [ ] 3.1 Frame codec and handshake tests, including each mismatch case (protocol, backend, Python policy) producing a fatal supervisor error
- [ ] 3.2 Worker kill (process termination), native abort and SEH fault: supervisor alive, minidump written, worker relaunched on the last committed revision, recovery time recorded
- [ ] 3.3 Device removal on DX12 and device loss on Vulkan through the test hooks: `device_removed` reported, worker exits, supervisor relaunches on the same backend
- [ ] 3.4 GPU stall: the deadline wait returns `timeout`, the job fails, the worker exits and is relaunched
- [ ] 3.5 Supervisor killed: the worker exits and the project file holds the last committed revision
- [ ] 3.6 Worker without `--allow-python` rejects `run_python` with `python_disabled`; a worker with an unavailable backend returns `gpu_backend_unavailable` before mutating while project open/save/inspect still succeed

## 4. Acceptance
- [ ] 4.1 Every §3 test green in a local run on the owner's machine (DX12 and Vulkan device-fault variants; decision 028, the local run report is the evidence) and on the hosted CPU lane where no GPU is needed (GPU tests skip there with an explicit reason); results attached to `phase2.4_supervisor-worker`

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
