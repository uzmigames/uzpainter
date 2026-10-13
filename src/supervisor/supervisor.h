#pragma once

// The supervisor role of UzPainter.exe (docs/architecture/02-runtime-topology.md §1, §5; task
// phase2.1_supervisor-ipc-worker; `SUPERVISOR.md`):
//
//   UzPainter.exe --mcp [--gpu-backend dx12|vulkan] [--allow-python] [--gpu-deadline-ms <ms>]
//                 [--output-root <dir>] [--crash-dir <dir>] [--test-faults] [--preview]
//
// The supervisor starts the embedded interpreter and hands the process to
// `uzpainter_supervisor.main` (python/uzpainter_supervisor/), UzPainter's own Python code over the
// pinned MCP SDK: it serves the stdio MCP session (protocol frames only on stdout, logs on
// stderr), launches the worker (this executable with `--worker`), checks its handshake and
// forwards `tools/call` over the pipe, relaunching the worker after every fault. The supervisor
// never creates a GPU device, never opens a project and never runs user Python: none of that code
// is reached from here.
//
// Exit status: 0 the MCP client closed the session, or a console Ctrl+C or Ctrl+Break stopped the
// supervisor (either transport: the worker ends, then the ledger closes); 2 a usage error; 3 a host
// failure (the interpreter did not start); 4 a fatal supervisor error (a handshake mismatch, or a
// worker that cannot be started).

#include <cstdio>
#include <string>
#include <vector>

namespace uzp::supervisor {

inline constexpr int kSupervisorExitHostError = 3;

/// True for `--mcp`.
bool IsSupervisorCommand(const std::string& first);

/// Runs the supervisor until the MCP session ends; returns the exit status. The interpreter is
/// left running: the caller ends the process with `std::_Exit`.
int RunSupervisorCommand(const std::vector<std::string>& args, std::FILE* err);

}  // namespace uzp::supervisor
