#pragma once

// Test-only fault hooks of the worker (docs/architecture/02-runtime-topology.md §5, §7; task
// phase2.1_supervisor-ipc-worker item 2.11, decision 120). Everything here exists only when
// `UZP_WORKER_FAULT_HOOKS` is defined, which build.zig does for Debug builds only: a release
// build (`-Doptimize=ReleaseFast`, `ReleaseSafe`, `ReleaseSmall`) contains none of it and refuses
// `--test-faults`. Even in a Debug build the hooks are inert unless the worker was launched with
// `--test-faults` (the supervisor passes it on when it was started with it).
//
// The worker's `test_fault {fault}` tool arms or triggers them:
// - `kill`: the worker terminates itself at once (a kill point; exit code `kKillExitCode`);
// - `abort`: `std::abort()`, which the worker's SIGABRT handler turns into a crash report;
// - `seh`: a write through a null pointer (an access violation the crash handler reports);
// - `remove_device`: the next GPU request first calls `ID3D12Device5::RemoveDevice` on the engine
//   thread, so it fails with `device_removed {backend, reason}`;
// - `gpu_stall`: the next GPU request first makes the direct queue wait on a fence nothing ever
//   signals, so its deadline wait returns `timeout`;
// - `kill_before_reply`: the next call runs to its end, then the worker terminates before the
//   reply is written (the call's commit is durable, its acknowledgement is lost).
//
// `UZP_TEST_HANDSHAKE`, a JSON object in the worker's environment, replaces fields of the
// handshake frame (the supervisor's mismatch tests).
//
// `UZP_TEST_KILL_ON_OPEN`, a file path in the worker's environment: while that file holds a
// count above zero, `worker/reopen` (the supervisor's recovery) decrements it and terminates the
// worker before opening (a worker dying while the supervisor reopens the project).

#if defined(UZP_WORKER_FAULT_HOOKS)

#include <optional>
#include <string>
#include <string_view>

#include "render/engine_thread.h"
#include "uzp_core/manifest/json.h"

namespace uzp::supervisor::fault {

enum class Fault { kill, abort, seh, remove_device, gpu_stall, kill_before_reply };

/// Exit code of a worker terminated by `kill` or `kill_before_reply`.
inline constexpr unsigned kKillExitCode = 77;

[[nodiscard]] std::optional<Fault> Parse(std::string_view name);

/// Acts on `fault`: `kill`, `abort` and `seh` end the process here; the others are armed and
/// this returns.
void Trigger(Fault fault);

/// Whether a GPU fault is armed for the next GPU request.
[[nodiscard]] bool GpuFaultArmed();
/// On the engine thread, before a GPU request: performs the armed GPU fault (then disarmed) and
/// returns the error the request fails with.
[[nodiscard]] render::Result<void> InjectGpuFault(render::EngineContext& context);

/// Whether `kill_before_reply` is armed (and disarms it).
[[nodiscard]] bool TakeKillBeforeReply();
/// Terminates the process with `kKillExitCode`.
[[noreturn]] void KillNow();

/// Under `UZP_TEST_KILL_ON_OPEN` (above): decrements the count and terminates the process.
void MaybeKillOnOpen();

/// The handshake with the fields of `UZP_TEST_HANDSHAKE` replaced; unchanged without it.
[[nodiscard]] core::json::Object OverrideHandshake(core::json::Object handshake);

}  // namespace uzp::supervisor::fault

#endif
