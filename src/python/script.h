#pragma once

// Running one script file in the embedded interpreter (docs/architecture/10-python-api.md §2, §5).
// The `run` command of UzPainter.exe (phase1.22_pyapi-cli-capabilities) and the native API tests
// (`uzp-pyapi-tests.exe`) call it.
//
// The script runs as `__main__` with `sys.argv = [script, *args]`; its standard output and error
// are captured until the event dispatcher has drained after it returned, so the events and
// callbacks of operations it started (10-python-api.md §4) are part of the run: their output and
// commits are in the report. The value it assigns to `result` is returned as JSON. An uncaught
// exception is a structured failure: its class, message and traceback. In both cases the report
// names the last revision the script committed and every committed call result, so a script that
// raises after earlier calls reports what it kept (those calls stay committed); a native
// `Transaction` left open is rolled back.

#include <filesystem>
#include <string>
#include <vector>

#include "uzp_core/manifest/json.h"

namespace uzp::python {

/// `{status: "ok"|"failed", result, stdout, stderr, last_committed_revision, committed,
///   error?: {type, message, traceback}}`. Requires the running interpreter and the GIL.
core::json::Object RunScript(const std::filesystem::path& script, const std::vector<std::string>& args);

}  // namespace uzp::python
