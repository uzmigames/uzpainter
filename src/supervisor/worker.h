#pragma once

// The worker role of UzPainter.exe (docs/architecture/02-runtime-topology.md §1, §2, §5; task
// phase2.1_supervisor-ipc-worker, decision 120; `SUPERVISOR.md`):
//
//   UzPainter.exe --worker --pipe \\.\pipe\uzpainter-<supervisor-pid>-<n> --gpu-backend dx12|vulkan
//                 [--allow-python] [--gpu-deadline-ms <ms>] [--output-root <dir>]
//                 [--crash-dir <dir>] [--connect-timeout-ms <ms>] [--test-faults] [--preview]
//
// The worker owns the one open document, the project store, the engine thread with the device of
// the requested backend and the embedded interpreter. It creates the pipe, accepts only its
// supervisor (the process whose id the pipe name carries), sends the handshake and then answers
// one request at a time on the interpreter's thread:
//
// - `tools/list`: its tools with their input schemas and whether each mutates or needs the GPU;
// - `tools/call`: `project_open`, `project_close`, `project_save`, `project_inspect` (GPU-free),
//   `evaluate_channel` (GPU), `run_python` (mutating; refused with `python_disabled` without
//   `--allow-python`) and, in a build with the fault hooks and under `--test-faults`, `test_fault`.
//   With `--preview` the worker hosts the preview window (src/preview/preview.h): every
//   `evaluate_channel` result is published to it without waiting, and `preview_status` is listed.
//   A mutating call needs `idempotency_key` (`invalid_request` otherwise) and is decided against
//   the open project's `operation` rows before it runs (phase2.2, decision 138): a known key with
//   the same request hash returns its stored outcome, with another hash `idempotency_conflict`;
//   an unknown key without a precondition, or with one below the pruning horizon, is
//   `outcome_unknown`, and with another revision than the current one `stale_revision`. A GPU
//   call on a worker without a device fails with `gpu_backend_unavailable {backend, reason}`
//   before anything runs.
//
// Faults: a native fault or `abort()` writes a crash report with a minidump through the vendored
// crash handler (`--crash-dir`, default beside the executable); a `device_removed` or `timeout`
// from the engine fails the call, and the worker exits with `kWorkerExitDeviceFault` after the
// reply. A broken pipe or the end of the supervisor process ends the worker at once, so nothing
// further is committed.

#include <cstdio>
#include <string>
#include <vector>

namespace uzp::supervisor {

inline constexpr int kWorkerExitUsage = 2;
/// The pipe could not be created, the supervisor did not connect, or the interpreter failed.
inline constexpr int kWorkerExitStartFailed = 3;
/// The pipe broke or the supervisor process ended.
inline constexpr int kWorkerExitSupervisorGone = 4;
/// The engine reported `device_removed` or `timeout`: the deliberate exit of 02 §5.
inline constexpr int kWorkerExitDeviceFault = 5;

/// The exception code `abort()` is reported with (STATUS_FATAL_APP_EXIT).
inline constexpr unsigned long kAbortExceptionCode = 0x40000015UL;

/// True for `--worker`.
bool IsWorkerCommand(const std::string& first);

/// Runs the worker. Returns only for a usage error or a failed start; every other end of the
/// worker terminates the process.
int RunWorkerCommand(const std::vector<std::string>& args, std::FILE* err);

/// Whether this build contains the test-only fault hooks (`fault_hooks.h`).
bool FaultHooksCompiled();

}  // namespace uzp::supervisor
