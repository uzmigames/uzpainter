// UzPainter.exe entry point (docs/architecture/01-overview.md, command line). Phase 0 provides the
// `selftest` command (docs/architecture/13-engine-integration.md §4.2); the project store adds
// `inspect`, `export-bundle` and `store-census` (src/store/cli.h), the export of a project and
// its publication's recovery `export` (src/export/cli.h); the other commands are added by their
// phases.

#include "export/cli.h"
#include "selftest/harness.h"
#include "store/cli.h"

#include <cstdio>
#include <string>
#include <vector>

int main(int argc, char** argv) {
    const std::vector<std::string> args(argv + (argc > 0 ? 1 : 0), argv + argc);
    if (!args.empty() && args.front() == "selftest") {
        return uzp::selftest::RunSelftestCommand({args.begin() + 1, args.end()});
    }
    if (!args.empty() && uzp::store::IsStoreCommand(args.front())) {
        return uzp::store::RunStoreCommand(args, stdout, stderr);
    }
    if (!args.empty() && uzp::exporter::IsExportCommand(args.front())) {
        return uzp::exporter::RunExportCommand(args, stdout, stderr);
    }
    std::fprintf(stderr, "usage: UzPainter.exe selftest [--out-dir <dir>] [--report <file>] "
                         "[--no-gpu]\n"
                         "       UzPainter.exe inspect | export-bundle | store-census ... (src/store/cli.h)\n"
                         "       UzPainter.exe export <file.uzp> --config <config.json> --app-version <version> "
                         "--build <id>\n"
                         "       UzPainter.exe export --recover <exportPath> [--fixed-names <dir>]...\n");
    return uzp::selftest::kExitUsage;
}
