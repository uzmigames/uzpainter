## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase1.25_pilot-wand — still open, with implementation items of its own outstanding (among them 2.6, the 16-bit export of the sRGB8 material channels, and 2.7, `infinite` padding on UV-islanded texture sets; both refused before writing until fitted). This task builds on the compositor, export, Python API and adapter code merged on main

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
- [x] 3.3 Device removal on DX12 through the test hook: `device_removed` reported, worker exits, supervisor relaunches on the same backend. The Vulkan device-loss variant is an acceptance obligation of `phase3.1_vulkan-compute-parity` item 3.4 (decisions 121, 221), not waived
- [x] 3.4 GPU stall: the deadline wait returns `timeout`, the job fails, the worker exits and is relaunched
- [x] 3.5 Supervisor killed: the worker exits and the project file holds the last committed revision
- [x] 3.6 Worker without `--allow-python` rejects `run_python` with `python_disabled`; a worker with an unavailable backend returns `gpu_backend_unavailable` before mutating while project open/save/inspect still succeed

## 4. Acceptance
- [ ] 4.1 Every §3 test green in a local run on the owner's machine (DX12 device-fault variants; decision 028, the local run report is the evidence; the Vulkan device-fault variant is settled by `phase3.1_vulkan-compute-parity` 4.1, decision 221) and on the local CPU lane where no GPU is needed (decision 200 replaces the hosted CPU lane; GPU tests skip there with an explicit reason); results attached to `phase2.4_supervisor-worker`

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
- [x] 5.2 Write tests covering the new behavior
- [x] 5.3 Run tests and confirm they pass

## 6. Notes (scope splits and evidence)
- 2.1: `--mcp-http` and `--roots` are refused with a usage error naming phase2.5_mcp-transport-registry (items 2.3, 2.7), which delivers them; `--preview` arrives with phase2.1_preview-viewport-window and hosts the same worker state as `run`.
- 2.5: the worker's Phase 2.1 vocabulary is `project_open/close/save/inspect`, `evaluate_channel` (GPU, payload by path + SHA-256), `run_python` and the Debug-only `test_fault` (decision 120); notifications are defined in the protocol and delivered by phase2.3_supervisor-jobs. A stale precondition returns `stale_revision`; the known-key lookup in front of it is phase2.2 item 2.4.
- 2.6: the GPU operations are the tools that use the device; the Phase 1 export runs on the CPU evaluator and is not refused (decision 120; the spec scenario is amended).
- 2.9, 2.11: DX12 implemented (`remove_device`, `gpu_stall` hooks, deliberate exit 5). The Vulkan device-loss hook is a recorded scope split to phase3.1_vulkan-compute-parity items 2.2 and 3.4 (decision 121): no Vulkan device exists before them.
- 2.11: hooks compiled only in Debug builds (`UZP_WORKER_FAULT_HOOKS`, build.zig); ReleaseFast/Safe/Small contain none and refuse `--test-faults` (decision 120).
- 2.8: the worker reports `{"event": "revision", "revision", "project"}` after every commit and project switch, before the call's reply, so a lost reply after `save_as` or close/open still recovers the project the worker really held. The reopen after a relaunch is raced against the new worker's end, with at most three launches before the fatal `recovery failed` (exit 4).
- 2.5: the MCP schema of a mutating tool requires `idempotency_key` and `expected_revision`, which the supervisor lifts into the pipe request.
- 3.2: a worker terminated from outside cannot write a minidump of itself (`minidump: null`); `abort()` and SEH write one through the vendored crash handler, asserted by the test.
- 3.3, 3.4 (DX12 run 2026-10-12): first run on main `ad945b0` gave 2 passed, 2 failed (`remove_device` reported `resource_creation_failed`; a call right after `gpu_stall` went to the exiting worker). Fixed in `be67f28` (engine `RequestError` classifies device loss before publishing; supervisor holds new calls after a fatal reply). Affected rerun on `be67f28`: both fault nodes plus `test_stalled_fence_times_out`, `test_device_removal_reported`, `test_failure_never_returns_stale_data`, 5 passed in 33.84 s, exit 0; `UzPainter.exe` SHA-256 bf830725b3e87fc5ad136be9b89781c23bdfb3423d0daf8bbdff320a80d93e85, `uzp-render-tests.exe` SHA-256 7a46b27ccbada63ade34bf526afb054f8a7c1e814d3eca43cfd49e1189341b82. The other two DX12 tests (device only in the worker, evaluation payload hash) passed on `ad945b0`. 3.4 is checked on this DX12 evidence. 3.3 was left open on its Vulkan device-loss variant (decision 121) until decision 221 (below).
- 4.1: open. CPU lane green locally 2026-10-12; the 4 DX12 cases now pass locally (see 3.3, 3.4); the Vulkan variant (decision 121) and the hosted CPU lane, which runs on the owner's push, were still open then.
- 4.1 (attachment, 2026-10-12): the local results are attached to phase2.4_supervisor-worker in `parity/reports/phase2/supervisor-settling.md`. The parent's CPU run on the merged tree repeats this task's `tests/supervisor` cases (81 passed, exit 0). The hosted CPU lane is still open.
- 4.1 (Decision 200 (2026-10-13): the owner removed the hosted Parity CI; the local CPU lane on the owner's machine (the coordinator's full gate before the owner pushes) replaces it.): its CPU-lane part is met by the local runs above (81 passed, exit 0). 4.1 stays open only on the Vulkan device-fault variant (decision 121).
- 3.3, 4.1 (decision 221, 2026-10-13): sequencing split, nothing waived. This task's acceptance is the DX12 device-fault cases plus every GPU-free case on both backends (the Vulkan worker has no device, `gpu_status: unavailable`). The Vulkan device-loss variant through the supervisor (hook in `src/supervisor/fault_hooks.h`, `device_removed`, relaunch on Vulkan at the last committed revision) is an acceptance obligation of `phase3.1_vulkan-compute-parity` items 3.4 and 4.1, and stays `pending` in `parity/reports/phase2/supervisor-settling.json` until that task settles it. Waiting here closed an acceptance cycle (phase3.1 → phase2.10 → phase2.8 → phase2.4 → this task → phase3.1; `python -m tools.planning.acceptance_graph`). 3.3 is checked on its DX12 evidence above, as decision 121 §3 directed. 4.1 now waits on nothing outside this task except 1.1 (phase1.25_pilot-wand); it is not checked here.
