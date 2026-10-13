// UzPainter.exe entry point (docs/architecture/01-overview.md, command line). Phase 0 provides the
// `selftest` command (docs/architecture/13-engine-integration.md §4.2); the project store adds
// `inspect` (with the recipe dump, src/python/recipe.h), `export-bundle` and `store-census`
// (src/store/cli.h), the export of a project and
// its publication's recovery `export` (src/export/cli.h), the Python API the script host `run`
// (src/python/run.h) and `capabilities` (src/python/capabilities.h), the supervisor and worker
// roles `--mcp` and `--worker` (src/supervisor/), the preview window `--preview` (src/preview/cli.h);
// the other commands are added by their phases.

#include "prof_scratch.h"
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#define NOMINMAX
#include <windows.h>
#include "export/cli.h"
#include "preview/cli.h"
#include "python/capabilities.h"
#include "python/recipe.h"
#include "python/run.h"
#include "selftest/harness.h"
#include "store/cli.h"
#include "supervisor/supervisor.h"
#include "supervisor/worker.h"

#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>

int main(int argc, char** argv) {
    if (uzp_prof::Dir()) {
        FILETIME c, e, k, u;
        GetProcessTimes(GetCurrentProcess(), &c, &e, &k, &u);
        ULARGE_INTEGER v;
        v.LowPart = c.dwLowDateTime;
        v.HighPart = c.dwHighDateTime;
        // FILETIME epoch 1601 -> Unix epoch.
        const double created = static_cast<double>(v.QuadPart) / 1e4 - 11644473600000.0;
        uzp_prof::Line("process.created", created, 0.0);
        uzp_prof::Mark("main.entry");
        std::string verb = argc > 1 ? argv[1] : "";
        uzp_prof::Mark("verb:" + verb);
    }
    const std::vector<std::string> args(argv + (argc > 0 ? 1 : 0), argv + argc);
    if (!args.empty() && uzp::supervisor::IsWorkerCommand(args.front())) {
        const int status = uzp::supervisor::RunWorkerCommand(args, stderr);
        std::fflush(stderr);
        std::_Exit(status);
    }
    if (!args.empty() && uzp::supervisor::IsSupervisorCommand(args.front())) {
        const int status = uzp::supervisor::RunSupervisorCommand(args, stderr);
        // The interpreter is not finalized: the MCP SDK's threads may still be blocked on stdin.
        std::fflush(stdout);
        std::fflush(stderr);
        std::_Exit(status);
    }
    if (!args.empty() && uzp::preview::IsPreviewCommand(args.front())) {
        const int status = uzp::preview::RunPreviewCommand(args, stdout, stderr);
        std::fflush(stdout);
        std::fflush(stderr);
        std::_Exit(status);
    }
    if (!args.empty() && args.front() == "selftest") {
        return uzp::selftest::RunSelftestCommand({args.begin() + 1, args.end()});
    }
    if (!args.empty() && uzp::store::IsStoreCommand(args.front())) {
        const uzp::core::RecipeHost recipe = uzp::python::HostRecipe();
        return uzp::store::RunStoreCommand(args, stdout, stderr, &recipe);
    }
    if (!args.empty() && uzp::exporter::IsExportCommand(args.front())) {
        return uzp::exporter::RunExportCommand(args, stdout, stderr);
    }
    if (!args.empty() && uzp::python::IsRunCommand(args.front())) {
        const int status = uzp::python::RunRunCommand(args, stdout, stderr);
        // The interpreter is not finalized: its worker threads may still wait for jobs.
        std::fflush(stdout);
        std::fflush(stderr);
        std::_Exit(status);
    }
    if (!args.empty() && uzp::python::IsCapabilitiesCommand(args.front())) {
        return uzp::python::RunCapabilitiesCommand(args, stdout, stderr);
    }
    std::fprintf(stderr, "usage: UzPainter.exe selftest [--out-dir <dir>] [--report <file>] "
                         "[--no-gpu]\n"
                         "       UzPainter.exe inspect | export-bundle | store-census ... (src/store/cli.h)\n"
                         "       UzPainter.exe export <file.uzp> --config <config.json> --app-version <version> "
                         "--build <id>\n"
                         "       UzPainter.exe export --recover <exportPath> [--fixed-names <dir>]...\n"
                         "       UzPainter.exe run <script.py> [args...] [--gpu-backend dx12|vulkan]\n"
                         "       UzPainter.exe capabilities\n"
                         "       UzPainter.exe --mcp [--gpu-backend dx12|vulkan] [--allow-python] ... "
                         "(src/supervisor/supervisor.h)\n"
                         "       UzPainter.exe --worker --pipe <pipe> --gpu-backend dx12|vulkan ... "
                         "(src/supervisor/worker.h)\n");
    return uzp::selftest::kExitUsage;
}
