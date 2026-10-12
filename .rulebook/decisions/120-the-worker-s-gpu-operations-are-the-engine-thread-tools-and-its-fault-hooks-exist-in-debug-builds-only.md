# 120. The worker's GPU operations are the engine-thread tools, and its fault hooks exist in Debug builds only

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase2.1_supervisor-ipc-worker, phase2.4_supervisor-worker, phase2.2_supervisor-admission-ledger, phase2.6_mcp-typed-tool-families

## Context

phase2.1 builds the supervisor/worker boundary of `docs/architecture/02-runtime-topology.md` §1, §2 and §5. Four choices were open:

- **Which tools are GPU operations.** The spec's example has an export refused with `gpu_backend_unavailable` on a worker without a device. The Phase 1 export computes on the CPU evaluator (decision 111). The GPU evaluator (`evaluator::Evaluator` on the engine thread) exists, but no user-facing operation used it.
- **Where the test-only fault hooks live.** The task requires them to be excluded from release builds, and the architecture docs define the release build as `-Doptimize=ReleaseFast`. The store keeps its hooks in dedicated test executables. The supervisor, however, launches *itself* as the worker, so a hooked copy would have to be the whole `UzPainter.exe`, built and installed a second time.
- **Which tools the worker serves before the typed families exist.** phase2.6 delivers those.
- **How a call in flight is answered** when its worker dies.

The model panel (one round):
- **C1, the GPU operation set.** AGREE ×2, PARTLY ×1. GPT asked for an explicit spec amendment and for the classification to follow device dependency.
- **C2, the hooks in Debug builds only.** AGREE ×3. GPT: every release mode must exclude them and refuse the flag.
- **C3, the Vulkan split.** AGREE ×3; recorded in decision 121.
- **C4, the vocabulary, the precondition and `interrupted`.** AGREE ×1, PARTLY ×2.
  - GPT: report `committed_revision` from the durable store. Done: the relaunched worker reopens the file before in-flight calls are answered.
  - Kimi: the supervisor could write a minidump of a worker killed from outside. Rejected: once `TerminateProcess` completes the address space is gone, and `MiniDumpWriteDump` needs a live process.

## Decision

1. **GPU operations are the tools that use the device.** In phase2.1 that is `evaluate_channel`: one channel of one stack on the GPU evaluator, with the texels written under the output root and returned as path + SHA-256.
   - On a worker without a device, it fails with `gpu_backend_unavailable {backend, reason}` before it runs.
   - The Phase 1 export stays GPU-free and is not refused. It joins the GPU set when it moves to the GPU evaluator.
   - The task spec's scenario is amended to use `evaluate_channel`.
2. **Hooks in Debug builds only.** `build.zig` defines `UZP_WORKER_FAULT_HOOKS` only when `optimize == .Debug`.
   - Without the define, `fault_hooks.cpp` compiles to nothing, and both roles refuse `--test-faults` with a usage error.
   - In a Debug build the hooks are inert unless the supervisor (and so its workers) was started with `--test-faults`.
   - The hooks are `kill`, `abort`, `seh`, `remove_device` (`ID3D12Device5::RemoveDevice` on the engine thread), `gpu_stall` (a direct-queue wait on a fence nothing signals) and `kill_before_reply`, plus `UZP_TEST_HANDSHAKE` for the mismatch tests.
3. **Worker vocabulary.**
   - GPU-free tools: `project_open`, `project_close`, `project_save` and `project_inspect`.
   - GPU tool: `evaluate_channel`.
   - Mutating tool: `run_python`, only with `--allow-python`.
   - Hook builds under `--test-faults` add `test_fault`.
   - A mutating call without `idempotency_key` or `expected_revision` returns `invalid_request`. A precondition that differs from the open project's revision returns `stale_revision {expected, current}` before the call runs. phase2.2 puts the known-key lookup in front of that check.
4. **Interrupted calls.**
   - A call in flight when its worker dies is answered `interrupted {cause, exit_code, fault_code, committed_revision}` after the relaunched worker has reopened the project, and is never re-sent.
   - Calls that arrive meanwhile are held and forwarded to the new worker.
   - A worker killed from outside has `minidump: null`. `abort()` (through a SIGABRT handler) and SEH faults write one through the vendored crash handler.

## Alternatives Considered

- **Refusing the CPU export without a device.** Rejected: it removes a working capability and misreports the cause.
- **A second, hooked copy of the whole application.** Rejected: it doubles the app build, and the copy would have to act as the supervisor too.
- **Re-sending the interrupted call.** Rejected: recovery is never a silent replay (02 §5). Retries belong to phase2.2's idempotency rules.

## Consequences

- `src/supervisor/SUPERVISOR.md` documents the tools, the checks and the hooks.
- phase2.6's typed families replace the phase2.1 vocabulary at the MCP surface; the pipe and the gates stay.
- The DX12 device-fault, stall and evaluation tests (`tests/supervisor/test_supervisor_gpu.py`) skip under `UZP_NO_GPU=1` and run in a local GPU run (decision 028).
