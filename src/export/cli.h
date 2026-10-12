#pragma once

// The export verbs of `UzPainter.exe` (docs/architecture/08-export.md §5; task
// phase1.17_export-publication-receipts, publish.h, fixed_names.h). They use no GPU and no
// project:
//
//   export --recover <exportPath> [--fixed-names <dir>]...
//       under the publication lock: publishes the newest complete generation newer than the
//       selected one, removes the incomplete generations (`RecoverExport`), and completes an
//       interrupted fixed-name copy into each `--fixed-names` directory (`RecoverFixedNames`);
//       prints the report as canonical JSON: {current_before, current_after, published, removed:
//       [{generation, problem}], damaged: {generation, problem} | null, removed_staging_pointer,
//       fixed_names: [{directory, rolled_forward}]}
//
// Exit status: 0 success (a damaged selected generation is reported, exit 1), 1 failure (the
// message names it), 2 usage error.

#include <cstdio>
#include <string>
#include <string_view>
#include <vector>

namespace uzp::exporter {

inline constexpr int kCliOk = 0;
inline constexpr int kCliFailed = 1;
inline constexpr int kCliUsage = 2;

/// True for `export`.
bool IsExportCommand(std::string_view verb);

/// Runs `args` (the verb first) and prints to `out` / `err`.
int RunExportCommand(const std::vector<std::string>& args, std::FILE* out, std::FILE* err);

}  // namespace uzp::exporter
