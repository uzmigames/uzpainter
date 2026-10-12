#pragma once

// The export verbs of `UzPainter.exe` (docs/architecture/08-export.md §5; tasks
// phase1.17_export-publication-receipts and phase1.18_export-engine, publish.h, fixed_names.h,
// project_export.h). They use no GPU:
//
//   export <file.uzp> --config <config.json> --app-version <version> --build <id>
//       (decision 104) exports the project's current revision with the Painter-compatible
//       configuration (`ExportProject`): the files, plan and receipt published as a new generation
//       under the configuration's exportPath; the receipt carries the given version and build
//       (ARC-11). Prints {generation, receipt, receipt_sha256, files: [{root_path, path, size,
//       sha256}]} as canonical JSON; a refusal prints "ValueError: ..." or "NotYetSupported: ..."
//       (nothing written), a failure its reason (the previous generation still selected).
//   export --recover <exportPath> [--fixed-names <dir>]...
//       (no project) under the publication lock: publishes the newest complete generation newer than the
//       selected one, removes the incomplete generations (`RecoverExport`), and completes an
//       interrupted fixed-name copy into each `--fixed-names` directory (`RecoverFixedNames`);
//       prints the report as canonical JSON: {current_before, current_after, published, removed:
//       [{generation, problem}], damaged: {generation, problem} | null, removed_staging_pointer,
//       fixed_names: [{directory, rolled_forward}]}
//
// Exit status: 0 success (a damaged selected generation is reported, exit 1), 1 failure or
// refusal (the message names it), 2 usage error.

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
