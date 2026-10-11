#pragma once

// The project-store verbs of `UzPainter.exe` (`docs/architecture/09-project-file-format.md` §3,
// §6). None of them uses a GPU or takes a project's lock:
//
//   inspect <file.uzp> [--revision N] [--verify]
//       prints the inspection report (`inspect.h`) as indented JSON; exit 1 when `--verify`
//       finds a failure
//   export-bundle <file.uzp> <dir|file.zip> [--revision N]
//       writes the bundle (`bundle.h`) and prints its summary
//   store-census --inputs <inputs.json> --assets-root <dir> --work <dir> --out <report.json> [--edits N]
//       runs the size census (`census.h`) and writes its report
//
// Exit status: 0 success, 1 failure (the message names it), 2 usage error.

#include <cstdio>
#include <string>
#include <string_view>
#include <vector>

namespace uzp::store {

inline constexpr int kCliOk = 0;
inline constexpr int kCliFailed = 1;
inline constexpr int kCliUsage = 2;

/// True for `inspect`, `export-bundle` and `store-census`.
bool IsStoreCommand(std::string_view verb);

/// Runs `args` (the verb first) and prints to `out` / `err`.
int RunStoreCommand(const std::vector<std::string>& args, std::FILE* out, std::FILE* err);

}  // namespace uzp::store
