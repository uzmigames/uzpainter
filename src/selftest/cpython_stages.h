#pragma once

// The CPython stages of `selftest` (docs/architecture/13-engine-integration.md §4.2; task
// phase0.7_toolchain-cpython), in run order:
//
//   cpython-start       the embedded interpreter starts from python313.dll beside the executable,
//                       is release 3.13.16 and isolated: sys.path holds only python313.zip, the
//                       install folder (the package's *.pyd) and Lib\site-packages\
//   cpython-uzpainter   the statically linked `uzpainter` module imports as a built-in module
//   cpython-buffer16    every 16-bit value 0..65535 goes from C++ to Python and back through the
//                       buffer protocol and is compared byte for byte
//   cpython-exceptions  a Python exception is caught in C++ with its type and message; C++
//                       exceptions thrown by bound functions are caught in Python as the mapped
//                       exception types with their messages; the interpreter stays usable
//   cpython-mcp-sdk     the vendored MCP SDK and its native wheels import from Lib\site-packages\
//                       and an in-process MCP client lists and calls a tool of an MCP server
//
// Every stage is mandatory and needs no GPU; the stages after `cpython-start` depend on it.

#include "harness.h"

namespace uzp::selftest {

void RegisterCpythonStages(Selftest& selftest);

/// Finalizes the interpreter if a stage started it.
void TeardownCpython();

StageOutcome RunCpythonStart(SelftestContext& context);
StageOutcome RunCpythonUzpainter(SelftestContext& context);
StageOutcome RunCpythonBuffer16(SelftestContext& context);
StageOutcome RunCpythonExceptions(SelftestContext& context);
StageOutcome RunCpythonMcpSdk(SelftestContext& context);

}  // namespace uzp::selftest
