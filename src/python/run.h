#pragma once

// `UzPainter.exe run <script.py> [args...] [--gpu-backend dx12|vulkan]` (docs/architecture/
// 01-overview.md §4, 02-runtime-topology.md §1, 10-python-api.md §2; task
// phase1.22_pyapi-cli-capabilities, decision 111): one process in the worker role hosts the script
// in the embedded interpreter, with `uzpainter` and `substance_painter` importable.
//
// `--gpu-backend <name>` is the process's backend wherever it appears among the arguments before
// `--` (it is not passed to the script; everything after `--` is, as given); dx12 by default. The
// host creates no device at startup. Exports acquire an owned engine after plan/source preflight;
// `painter_viewport` captures create one per call. Both use the reported process backend.
// Before returning, run joins active jobs and cancels still-paused queued jobs, while capturing
// callback output; the project is closed only after those jobs and their GPU resources finish.
// `--test-gpu-unavailable` before `--` is a Debug-only fixture: captures use an engine whose
// device factory fails with `gpu_backend_unavailable` before loading any GPU. CPU operations
// still run and `gpu_backend` keeps the requested backend. Release builds reject the flag.
//
// Output: one line `UZP_JSON:{...}` on `out`, the report of `RunScript` (script.h) with
// `gpu_backend`: the value assigned to `result`, the script's captured stdout and stderr (with
// those of the events and callbacks delivered after it returned), the revisions it committed and,
// for an uncaught exception, `error: {type, message, traceback}`. The host then closes a project
// left open.
//
// `--diagnostic-measure-export`, anywhere before `--`, makes every export of this process the
// diagnostic measure export of decision 286 (export/write.h): NOT conformant, it writes what
// production refuses on UV-islanded sets, `InexactPadding::measure` included, and marks the
// generation's receipt `non_conformant`. The report then holds `diagnostic: "diagnostic-measure"`.
// No other verb, no MCP or worker process and no Python call can turn it on.
//
// The arguments are UTF-8 (src/main.cpp): the script's path and `sys.argv` keep every character.
// Ctrl+C or Ctrl+Break raises KeyboardInterrupt in the script, a structured failure; the host then
// reports it and closes a project left open, as after any run.
//
// Exit status: 0 the script ran to its end and `result` is JSON; 1 a structured failure (the
// script raised, could not be read, or `result` is not JSON); 2 a usage error (message on `err`,
// no JSON line); 3 a host failure outside the script (the interpreter did not start, or the host
// failed around the script, such as output it cannot encode as UTF-8), reported as
// `UZP_JSON:{"status": "host_error", "error": {type, message}}`; never an uncaught exception.

#include <cstdio>
#include <string>
#include <string_view>
#include <vector>

namespace uzp::python {

inline constexpr int kRunOk = 0;
inline constexpr int kRunFailed = 1;
inline constexpr int kRunUsage = 2;
inline constexpr int kRunHostError = 3;

/// The prefix of every JSON line a CLI verb prints (01-overview.md §4).
inline constexpr std::string_view kJsonPrefix = "UZP_JSON:";

/// True for `run`.
bool IsRunCommand(std::string_view verb);

/// True only in a `run` process started with `--diagnostic-measure-export` (above, decision 286).
[[nodiscard]] bool DiagnosticMeasureExport();

/// Runs `args` (the verb first) and returns the exit status. The interpreter stays running and
/// its worker threads may still wait for jobs: the caller ends the process with `std::_Exit`.
int RunRunCommand(const std::vector<std::string>& args, std::FILE* out, std::FILE* err);

}  // namespace uzp::python
