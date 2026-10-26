// UzPainter.exe entry point (docs/architecture/01-overview.md, command line). Phase 0 provides the
// `selftest` command (docs/architecture/13-engine-integration.md §4.2); the project store adds
// `inspect` (with the recipe dump, src/python/recipe.h), `export-bundle` and `store-census`
// (src/store/cli.h), the export of a project and
// its publication's recovery `export` (src/export/cli.h), the Python API the script host `run`
// (src/python/run.h) and `capabilities` (src/python/capabilities.h), the supervisor and worker
// roles `--mcp` and `--worker` (src/supervisor/), the preview window `--preview` (src/preview/cli.h),
// the asset library's `assets list` (src/procedural/cli.h);
// the other commands are added by their phases. Every verb reads its arguments in UTF-8, decoded
// from the wide command line. `--help` prints the usage on stdout (exit status 0); a usage error
// prints it on stderr (exit status 2). The persistent caches (src/render/disk_cache.h, decision 253)
// are on for every verb unless `--no-cache` (anywhere before a `--`) or `UZP_NO_CACHE` turns them
// off; `cache` reports and clears them. A leading `--headless` (decision 252) sets `UZP_HEADLESS=1`
// for the process and its children before the command runs.

#include "export/cli.h"
#include "preview/cli.h"
#include "procedural/cli.h"
#include "procedural/snapshot_cli.h"
#include "procedural/filter_import_cli.h"
#include "python/capabilities.h"
#include "python/recipe.h"
#include "python/run.h"
#include "render/disk_cache.h"
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
#include <werapi.h>

namespace {

/// No Windows dialog in any role (decision 252): a critical error, a fault or a file that cannot
/// be opened fails instead of waiting for a click (the launcher's other error-mode bits are kept,
/// and children inherit the mode), Windows Error Reporting shows no UI, and `abort()` without a
/// SIGABRT handler exits with status 3 instead of reaching it. `assert` already writes to stderr
/// in a console program. The worker then installs its crash handler and its SIGABRT handler
/// (src/supervisor/worker.cpp), which write the minidump. A DLL that fails to load before main()
/// is the launcher's error mode to silence (adapters/assets3d/client.py does).
void SuppressErrorDialogs() {
    SetErrorMode(GetErrorMode() | SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX);
    WerSetFlags(WER_FAULT_REPORTING_NO_UI);
    _set_abort_behavior(0, _CALL_REPORTFAULT);
}

constexpr const char* kUsage =
    "usage: UzPainter.exe selftest [--out-dir <dir>] [--report <file>] [--no-gpu]\n"
    "       UzPainter.exe inspect <file.uzp> [--revision N] [--verify | --recipe]\n"
    "       UzPainter.exe export-bundle <file.uzp> <dir|file.zip> [--revision N]\n"
    "       UzPainter.exe store-census --inputs <inputs.json> --assets-root <dir> --work <dir> --out <report.json>\n"
    "                                  [--edits N]\n"
    "       UzPainter.exe export <file.uzp> --config <config.json> --app-version <version> --build <id>\n"
    "       UzPainter.exe export --recover <exportPath> [--fixed-names <dir>]...\n"
    "       UzPainter.exe run <script.py> [args...] [--gpu-backend dx12|vulkan] [-- args...]\n"
    "                         [--diagnostic-measure-export]   (non-conformant, decision 286)\n"
    "                         [--test-gpu-unavailable]       (Debug-only device failure fixture)\n"
    "                         [--assets3d-production-required] (Assets3D production guard, decision 360)\n"
    "       UzPainter.exe capabilities [--runtime]\n"
    "       UzPainter.exe assets list [--parity] [--library <dir>]\n"
    "       UzPainter.exe assets snapshot <file.uzp> --request <request.json>\n"
    "       UzPainter.exe assets bind-snapshot <file.uzp> --request <bind.json>\n"
    "       UzPainter.exe assets import-filter-observation <h-store.uzp> --oracle-store <root> --manifest <public-manifest.json> --request <import.json>\n"
    "       UzPainter.exe cache info | clear\n"
    "       UzPainter.exe --preview <file.uzp> [--gpu-backend dx12|vulkan] [--headless]\n"
    "       UzPainter.exe --mcp [--mcp-http <host>:<port> [--token <token>] [--allow-remote]]\n"
    "                           [--roots <kind>=<dir>;...] [--gpu-backend dx12|vulkan] [--allow-python]\n"
    "                           [--gpu-deadline-ms <ms>] [--output-root <dir>] [--crash-dir <dir>]\n"
    "                           [--ledger <file>] [--test-faults] [--test-gpu-unavailable] [--preview] [--headless]\n"
    "       UzPainter.exe --worker --pipe \\\\.\\pipe\\uzpainter-<supervisor-pid>-<n> --gpu-backend dx12|vulkan\n"
    "                              [--allow-python] [--gpu-deadline-ms <ms>] [--output-root <dir>]\n"
    "                              [--crash-dir <dir>] [--connect-timeout-ms <ms>] [--test-faults]\n"
    "                              [--test-gpu-unavailable] [--preview]\n"
    "       UzPainter.exe --headless <command> ...  (no window: sets UZP_HEADLESS=1, which refuses --preview)\n"
    "       UzPainter.exe --help\n"
    "Any verb also takes --no-cache (before a --): no persistent cache is read or written, here or in\n"
    "the processes it starts; UZP_NO_CACHE=1 does the same.\n";

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

/// Removes every `--no-cache` before a `--` from `args`; true when there was one.
bool TakeNoCache(std::vector<std::string>& args) {
    bool found = false;
    for (auto it = args.begin(); it != args.end() && *it != "--";) {
        if (*it == "--no-cache") {
            found = true;
            it = args.erase(it);
        } else {
            ++it;
        }
    }
    return found;
}

}  // namespace

int main() {
    SuppressErrorDialogs();
    std::optional<std::vector<std::string>> arguments = Utf8Arguments();
    if (!arguments) {
        std::fprintf(stderr, "UzPainter.exe: the command line is not valid UTF-16\n");
        return uzp::selftest::kExitUsage;
    }
    std::vector<std::string>& args = *arguments;
    // The variable carries `--no-cache` to the processes this one starts (the MCP worker).
    if (TakeNoCache(args)) _wputenv(L"UZP_NO_CACHE=1");
    if (!uzp::render::CachesDisabledByEnvironment()) uzp::render::EnableCaches(uzp::render::DefaultCacheRoot());
    if (!args.empty() && args.front() == uzp::preview::kHeadlessOption) {
        uzp::preview::SetHeadless();
        args.erase(args.begin());
    }
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
    if (!args.empty() && uzp::procedural::IsAssetsCommand(args.front())) {
        if (args.size() > 1 && args[1] == "snapshot") {
            return uzp::procedural::RunSnapshotCommand(args, stdout, stderr);
        }
        if (args.size() > 1 && args[1] == "bind-snapshot") {
            return uzp::procedural::RunBindSnapshotCommand(args, stdout, stderr);
        }
        if (args.size() >= 2 && args[1] == "import-filter-observation") {
            return uzp::procedural::RunFilterImportCommand(args, stdout, stderr);
        }
        return uzp::procedural::RunAssetsCommand(args, stdout, stderr);
    }
    if (!args.empty() && uzp::render::IsCacheCommand(args.front())) {
        return uzp::render::RunCacheCommand(args, stdout, stderr);
    }
    std::fputs(kUsage, stderr);
    return uzp::selftest::kExitUsage;
}
