#pragma once

// The capability manifest at run time (docs/architecture/10-python-api.md §1, §3; task
// phase1.22_pyapi-cli-capabilities, decision 112): `capabilities.json`, generated at build time by
// `tools/capabilities/generate_capabilities.py` and installed beside the executable.
//
//   UzPainter.exe capabilities
//       prints the shipped manifest as one line `UZP_JSON:{...}` (01-overview.md §4). Exit status:
//       0 printed, 2 usage error, 3 the shipped file is missing or unreadable (a broken install,
//       reported as `UZP_JSON:{"status": "host_error", "error": {type, message}}`).
//
// `uzpainter.capabilities` (BindCapabilities): `profile()` is the compatibility profile
// "painter-12.1-api-0.3.7"; `manifest()` the parsed document; `entry(symbol, context="any")` the
// entry of a symbol in an operation context, or None.

#include <cstdio>
#include <filesystem>
#include <string>
#include <string_view>
#include <vector>

#include <pybind11/pybind11.h>

namespace uzp::python {

/// The compatibility profile UzPainter reproduces (10-python-api.md §1).
inline constexpr const char* kCompatProfile = "painter-12.1-api-0.3.7";

/// `capabilities.json` beside the executable.
std::filesystem::path CapabilitiesPath();

/// True for `capabilities`.
bool IsCapabilitiesCommand(std::string_view verb);

/// Runs `args` (the verb first) and returns the exit status.
int RunCapabilitiesCommand(const std::vector<std::string>& args, std::FILE* out, std::FILE* err);

/// Defines `uzpainter.capabilities` in `m`.
void BindCapabilities(pybind11::module_& m);

}  // namespace uzp::python
