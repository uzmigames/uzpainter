#pragma once

// `UzPainter.exe run <script.py> [args...] [--gpu-backend dx12|vulkan]` (docs/architecture/
// 01-overview.md §4, 02-runtime-topology.md §1, 10-python-api.md §2; task
// phase1.22_pyapi-cli-capabilities, decision 111): one process in the worker role hosts the script
// in the embedded interpreter, with `uzpainter` and `substance_painter` importable.
//
// `--gpu-backend <name>` is the process's backend wherever it appears among the arguments before
// `--` (it is not passed to the script; everything after `--` is, as given); dx12 by default. The
// host creates no device: the backend is checked and reported (`gpu_backend`); the first GPU
// operation, a `painter_viewport` capture, creates one for its own use (decisions 111, 148).
//
// Output: one line `UZP_JSON:{...}` on `out`, the report of `RunScript` (script.h) with
// `gpu_backend`: the value assigned to `result`, the script's captured stdout and stderr (with
// those of the events and callbacks delivered after it returned), the revisions it committed and,
// for an uncaught exception, `error: {type, message, traceback}`. The host then closes a project
// left open.
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

/// Runs `args` (the verb first) and returns the exit status. The interpreter stays running and
/// its worker threads may still wait for jobs: the caller ends the process with `std::_Exit`.
int RunRunCommand(const std::vector<std::string>& args, std::FILE* out, std::FILE* err);

}  // namespace uzp::python
