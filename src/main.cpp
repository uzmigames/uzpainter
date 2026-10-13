// UzPainter.exe entry point (docs/architecture/01-overview.md, command line). Phase 0 provides the
// `selftest` command (docs/architecture/13-engine-integration.md §4.2); the project store adds
// `inspect` (with the recipe dump, src/python/recipe.h), `export-bundle` and `store-census`
// (src/store/cli.h), the export of a project and
// its publication's recovery `export` (src/export/cli.h), the Python API the script host `run`
// (src/python/run.h) and `capabilities` (src/python/capabilities.h), the supervisor and worker
// roles `--mcp` and `--worker` (src/supervisor/), the preview window `--preview` (src/preview/cli.h);
// the other commands are added by their phases. Every verb reads its arguments in UTF-8, decoded
// from the wide command line. `--help` prints the usage on stdout (exit status 0); a usage error
// prints it on stderr (exit status 2).

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
#include <cwchar>
#include <optional>
#include <string>
#include <vector>

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <shellapi.h>

namespace {

constexpr const char* kUsage =
    "usage: UzPainter.exe selftest [--out-dir <dir>] [--report <file>] [--no-gpu]\n"
    "       UzPainter.exe inspect <file.uzp> [--revision N] [--verify | --recipe]\n"
    "       UzPainter.exe export-bundle <file.uzp> <dir|file.zip> [--revision N]\n"
    "       UzPainter.exe store-census --inputs <inputs.json> --assets-root <dir> --work <dir> --out <report.json>\n"
    "                                  [--edits N]\n"
    "       UzPainter.exe export <file.uzp> --config <config.json> --app-version <version> --build <id>\n"
    "       UzPainter.exe export --recover <exportPath> [--fixed-names <dir>]...\n"
    "       UzPainter.exe run <script.py> [args...] [--gpu-backend dx12|vulkan] [-- args...]\n"
    "       UzPainter.exe capabilities\n"
    "       UzPainter.exe --preview <file.uzp> [--gpu-backend dx12|vulkan]\n"
    "       UzPainter.exe --mcp [--mcp-http <host>:<port> [--token <token>] [--allow-remote]]\n"
    "                           [--roots <kind>=<dir>;...] [--gpu-backend dx12|vulkan] [--allow-python]\n"
    "                           [--gpu-deadline-ms <ms>] [--output-root <dir>] [--crash-dir <dir>]\n"
    "                           [--ledger <file>] [--test-faults] [--preview]\n"
    "       UzPainter.exe --worker --pipe \\\\.\\pipe\\uzpainter-<supervisor-pid>-<n> --gpu-backend dx12|vulkan\n"
    "                              [--allow-python] [--gpu-deadline-ms <ms>] [--output-root <dir>]\n"
    "                              [--crash-dir <dir>] [--connect-timeout-ms <ms>] [--test-faults] [--preview]\n"
    "       UzPainter.exe --help\n";

/// The arguments after the program name in UTF-8, as every verb reads them. `main`'s `argv` holds
/// them in the ANSI code page, which loses every character outside it. None when the command line
/// cannot be split or is not valid UTF-16.
std::optional<std::vector<std::string>> Utf8Arguments() {
    int count = 0;
    wchar_t** wide = CommandLineToArgvW(GetCommandLineW(), &count);
    if (wide == nullptr) return std::nullopt;
    std::vector<std::string> args;
    for (int i = 1; i < count; ++i) {
        const int length = static_cast<int>(std::wcslen(wide[i]));
        const int bytes =
            WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, wide[i], length, nullptr, 0, nullptr, nullptr);
        if (bytes == 0 && length != 0) {
            LocalFree(wide);
            return std::nullopt;
        }
        std::string utf8(static_cast<std::size_t>(bytes), '\0');
        WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, wide[i], length, utf8.data(), bytes, nullptr, nullptr);
        args.push_back(std::move(utf8));
    }
    LocalFree(wide);
    return args;
}

}  // namespace

int main() {
    const std::optional<std::vector<std::string>> arguments = Utf8Arguments();
    if (!arguments) {
        std::fprintf(stderr, "UzPainter.exe: the command line is not valid UTF-16\n");
        return uzp::selftest::kExitUsage;
    }
    const std::vector<std::string>& args = *arguments;
    if (args.size() == 1 && args.front() == "--help") {
        std::fputs(kUsage, stdout);
        return 0;
    }
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
    std::fputs(kUsage, stderr);
    return uzp::selftest::kExitUsage;
}
