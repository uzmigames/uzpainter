// UzPainter.exe entry point (docs/architecture/01-overview.md, command line). Phase 0 provides the
// `selftest` command (docs/architecture/13-engine-integration.md §4.2); the other commands are
// added by their phases.

#include "selftest/harness.h"

#include <cstdio>
#include <string>
#include <vector>

int main(int argc, char** argv) {
    const std::vector<std::string> args(argv + (argc > 0 ? 1 : 0), argv + argc);
    if (!args.empty() && args.front() == "selftest") {
        return uzp::selftest::RunSelftestCommand({args.begin() + 1, args.end()});
    }
    std::fprintf(stderr, "usage: UzPainter.exe selftest [--out-dir <dir>] [--report <file>] "
                         "[--no-gpu]\n");
    return uzp::selftest::kExitUsage;
}
