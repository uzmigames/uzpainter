#pragma once

// `UzPainter.exe assets list [--parity] [--library <dir>]` (docs/architecture/01-overview.md
// command line, 05-procedural-content.md §3, §6; decision 324): the assets of UzPainter's own
// library (asset_library.h), printed as one line `UZP_JSON:{...}`:
//
//   {"status": "ok", "library": <root>, "assets": [{"asset", "name", "usage"}, ...]}
//
// sorted by URL. `--parity` adds each asset's parity status (`exact`, `calibrated` with its
// residuals per unit and corpus ids, or `unavailable` with the reason), the report that gives it
// and its certified editable domain. The internal alias table is not listed: Painter names are
// compatibility aliases only (CLR-06). `--library` reads another library directory (the default
// is `bin/assets/procedural`, or `UZP_ASSET_LIBRARY`).
//
// Exit status: 0 listed, 2 usage error, 3 the library does not load (`{"status": "host_error",
// "error": {type, message}}`).

#include <cstdio>
#include <string>
#include <string_view>
#include <vector>

namespace uzp::procedural {

/// True for `assets`.
bool IsAssetsCommand(std::string_view verb);

/// Runs `args` (the verb first) and returns the exit status.
int RunAssetsCommand(const std::vector<std::string>& args, std::FILE* out, std::FILE* err);

}  // namespace uzp::procedural
