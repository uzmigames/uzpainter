// The `UzPainter.exe selftest` harness: stage runner, report and command line (harness.h).

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include "harness.h"

#include "hardware_slice.h"

#include "log.h"
#include "paths.h"
#include "rhi_device.h"

#include <spdlog/sinks/callback_sink.h>

#include <windows.h>

#include <cstdio>
#include <cstdlib>
#include <ctime>
#include <fstream>
#include <mutex>
#include <sstream>

#ifndef UZP_ZIG_VERSION
#error "UZP_ZIG_VERSION is defined by build.zig"
#endif
#ifndef UZP_BUILD_MODE
#error "UZP_BUILD_MODE is defined by build.zig"
#endif

namespace uzp::selftest {

const char* StatusName(StageStatus status) {
    switch (status) {
        case StageStatus::Passed:  return "passed";
        case StageStatus::Failed:  return "failed";
        case StageStatus::Skipped: return "skipped";
    }
    return "unknown";
}

StageOutcome StageOutcome::Pass(Details details) {
    return {StageStatus::Passed, {}, std::move(details)};
}

StageOutcome StageOutcome::Fail(std::string reason, Details details) {
    return {StageStatus::Failed, std::move(reason), std::move(details)};
}

SelftestContext::SelftestContext(Options opts)
    : options(std::move(opts)), exeDir(uz::GetExeDir()) {}

SelftestContext::~SelftestContext() = default;

// ── Render-core log ──────────────────────────────────────────────────────────

namespace {

std::mutex g_logMutex;
std::vector<std::string> g_logProblems;

std::string Utf8(const std::wstring& wide) {
    if (wide.empty()) return {};
    const int size = WideCharToMultiByte(CP_UTF8, 0, wide.data(), static_cast<int>(wide.size()),
                                         nullptr, 0, nullptr, nullptr);
    std::string out(static_cast<size_t>(size), '\0');
    WideCharToMultiByte(CP_UTF8, 0, wide.data(), static_cast<int>(wide.size()), out.data(), size,
                        nullptr, nullptr);
    return out;
}

/// A REG_SZ or REG_DWORD value under HKLM, as text; empty if absent.
std::string RegistryValue(const wchar_t* key, const wchar_t* name) {
    DWORD type = 0;
    DWORD size = 0;
    if (RegGetValueW(HKEY_LOCAL_MACHINE, key, name, RRF_RT_REG_SZ | RRF_RT_REG_DWORD, &type,
                     nullptr, &size) != ERROR_SUCCESS) {
        return {};
    }
    std::vector<unsigned char> data(size + sizeof(wchar_t));
    if (RegGetValueW(HKEY_LOCAL_MACHINE, key, name, RRF_RT_REG_SZ | RRF_RT_REG_DWORD, &type,
                     data.data(), &size) != ERROR_SUCCESS) {
        return {};
    }
    if (type == REG_DWORD) return std::to_string(*reinterpret_cast<DWORD*>(data.data()));
    std::string text = Utf8(reinterpret_cast<const wchar_t*>(data.data()));
    while (!text.empty() && text.back() == ' ') text.pop_back();
    return text;
}

/// "major.minor.build.ubr" of the running Windows, from RtlGetVersion (not subject to the
/// compatibility shims of GetVersionEx) and the update build revision in the registry.
std::string OsBuild() {
    using RtlGetVersionFn = LONG(WINAPI*)(OSVERSIONINFOW*);
    OSVERSIONINFOW info{};
    info.dwOSVersionInfoSize = sizeof(info);
    HMODULE ntdll = GetModuleHandleW(L"ntdll.dll");
    auto rtlGetVersion =
        ntdll ? reinterpret_cast<RtlGetVersionFn>(
                    reinterpret_cast<void*>(GetProcAddress(ntdll, "RtlGetVersion")))
              : nullptr;
    if (!rtlGetVersion || rtlGetVersion(&info) != 0) return "unknown";
    std::string build = std::to_string(info.dwMajorVersion) + "." +
                        std::to_string(info.dwMinorVersion) + "." +
                        std::to_string(info.dwBuildNumber);
    const std::string ubr =
        RegistryValue(L"SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion", L"UBR");
    return ubr.empty() ? build : build + "." + ubr;
}

std::string UtcNow() {
    const std::time_t now = std::time(nullptr);
    std::tm utc{};
    gmtime_s(&utc, &now);
    char buf[32];
    std::strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%SZ", &utc);
    return buf;
}

std::string JsonString(const std::string& text) {
    std::string out = "\"";
    for (const unsigned char c : text) {
        switch (c) {
            case '"':  out += "\\\""; break;
            case '\\': out += "\\\\"; break;
            case '\n': out += "\\n"; break;
            case '\r': out += "\\r"; break;
            case '\t': out += "\\t"; break;
            default:
                if (c < 0x20) {
                    char buf[8];
                    std::snprintf(buf, sizeof(buf), "\\u%04x", c);
                    out += buf;
                } else {
                    out += static_cast<char>(c);
                }
        }
    }
    return out + "\"";
}

void WriteDetails(std::ostream& out, const Details& details, const char* indent) {
    out << "{";
    for (size_t i = 0; i < details.size(); ++i) {
        out << (i ? "," : "") << "\n" << indent << "  " << JsonString(details[i].first) << ": "
            << JsonString(details[i].second);
    }
    out << (details.empty() ? "}" : std::string("\n") + indent + "}");
}

}  // namespace

std::vector<std::string> DrainLogProblems() {
    std::lock_guard<std::mutex> lock(g_logMutex);
    return std::exchange(g_logProblems, {});
}

Details EnvironmentFacts(const SelftestContext& context) {
    wchar_t exePath[MAX_PATH] = {};
    GetModuleFileNameW(nullptr, exePath, MAX_PATH);
    Details facts = {
        {"os_build", OsBuild()},
        {"os_display_version",
         RegistryValue(L"SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion", L"DisplayVersion")},
        {"os_product",
         RegistryValue(L"SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion", L"ProductName")},
        {"cpu", RegistryValue(L"HARDWARE\\DESCRIPTION\\System\\CentralProcessor\\0",
                              L"ProcessorNameString")},
        {"zig", UZP_ZIG_VERSION},
        {"build_mode", UZP_BUILD_MODE},
        {"exe", Utf8(exePath)},
        {"gpu_stages", context.options.noGpu ? "skipped" : "run"},
    };
    if (context.options.noGpu) facts.emplace_back("gpu_stages_reason", context.options.noGpuReason);
    return facts;
}

// ── Stage runner ─────────────────────────────────────────────────────────────

void Selftest::Add(StageSpec stage) { m_stages.push_back(std::move(stage)); }

int Selftest::Run(SelftestContext& context) {
    const Details environment = EnvironmentFacts(context);
    const std::string started = UtcNow();
    m_records.clear();

    for (const StageSpec& spec : m_stages) {
        StageRecord record{spec, {}, 0.0};
        std::string unmet;
        for (const std::string& dependency : spec.dependsOn) {
            for (const StageRecord& done : m_records) {
                if (done.spec.name == dependency && done.outcome.status != StageStatus::Passed) {
                    unmet = "needs stage " + dependency + ", which " +
                            (done.outcome.status == StageStatus::Failed ? "failed" : "was skipped");
                }
            }
            if (!unmet.empty()) break;
        }
        if (spec.needsGpu && context.options.noGpu) {
            record.outcome = {StageStatus::Skipped, "no GPU: " + context.options.noGpuReason, {}};
        } else if (!unmet.empty()) {
            record.outcome = {StageStatus::Skipped, unmet, {}};
        } else {
            DrainLogProblems();
            const auto start = std::chrono::steady_clock::now();
            try {
                record.outcome = spec.run(context);
            } catch (const std::exception& error) {
                record.outcome = StageOutcome::Fail(std::string("exception: ") + error.what());
            }
            record.durationMs = std::chrono::duration<double, std::milli>(
                                    std::chrono::steady_clock::now() - start)
                                    .count();
            if (record.outcome.status == StageStatus::Failed) {
                for (const std::string& line : DrainLogProblems()) {
                    record.outcome.details.emplace_back("render_core_log", line);
                }
            }
        }
        std::printf("%s %s%s%s\n",
                    record.outcome.status == StageStatus::Passed   ? "PASS"
                    : record.outcome.status == StageStatus::Failed ? "FAIL"
                                                                   : "SKIP",
                    spec.name.c_str(), record.outcome.reason.empty() ? "" : ": ",
                    record.outcome.reason.c_str());
        std::fflush(stdout);
        m_records.push_back(std::move(record));
    }

    bool failed = false;
    bool sliceFailed = false;
    bool sliceSkipped = false;
    for (const StageRecord& r : m_records) {
        if (r.spec.mandatory && r.outcome.status == StageStatus::Failed) failed = true;
        if (r.spec.hardwareSlice && r.outcome.status == StageStatus::Failed) sliceFailed = true;
        if (r.spec.hardwareSlice && r.outcome.status == StageStatus::Skipped) sliceSkipped = true;
    }
    const char* slice = sliceFailed ? "failed" : sliceSkipped ? "skipped" : "passed";
    const int exitCode = failed ? kExitFailed : kExitPassed;

    std::ostringstream out;
    out << "{\n  \"schema\": \"uzpainter.selftest/1\",\n";
    out << "  \"command\": \"UzPainter.exe selftest\",\n";
    out << "  \"started_utc\": " << JsonString(started) << ",\n";
    out << "  \"environment\": ";
    WriteDetails(out, environment, "  ");
    out << ",\n  \"stages\": [";
    for (size_t i = 0; i < m_records.size(); ++i) {
        const StageRecord& r = m_records[i];
        char duration[32];
        std::snprintf(duration, sizeof(duration), "%.3f", r.durationMs);
        out << (i ? "," : "") << "\n    {\n";
        out << "      \"name\": " << JsonString(r.spec.name) << ",\n";
        out << "      \"mandatory\": " << (r.spec.mandatory ? "true" : "false") << ",\n";
        out << "      \"needs_gpu\": " << (r.spec.needsGpu ? "true" : "false") << ",\n";
        out << "      \"hardware_slice\": " << (r.spec.hardwareSlice ? "true" : "false") << ",\n";
        out << "      \"status\": " << JsonString(StatusName(r.outcome.status)) << ",\n";
        out << "      \"reason\": " << JsonString(r.outcome.reason) << ",\n";
        out << "      \"duration_ms\": " << duration << ",\n";
        out << "      \"details\": ";
        WriteDetails(out, r.outcome.details, "      ");
        out << "\n    }";
    }
    out << "\n  ],\n";
    out << "  \"hardware_slice\": " << JsonString(slice) << ",\n";
    out << "  \"result\": " << JsonString(failed ? "failed" : "passed") << ",\n";
    out << "  \"exit_code\": " << exitCode << "\n}\n";

    std::error_code ec;
    std::filesystem::create_directories(context.options.reportPath.parent_path(), ec);
    std::ofstream file(context.options.reportPath, std::ios::binary);
    file << out.str();
    file.close();
    if (!file) {
        std::fprintf(stderr, "selftest: cannot write the report %s\n",
                     context.options.reportPath.string().c_str());
        return kExitFailed;
    }
    std::printf("selftest: %s; DX12 hardware slice %s; report %s\n", failed ? "failed" : "passed",
                slice, context.options.reportPath.string().c_str());
    std::fflush(stdout);
    return exitCode;
}

// ── Command line ─────────────────────────────────────────────────────────────

namespace {

void Usage() {
    std::fprintf(stderr,
                 "usage: UzPainter.exe selftest [--out-dir <dir>] [--report <file>] [--no-gpu]\n"
                 "  --out-dir  folder for the report, the log and the 16-bit PNG\n"
                 "             (default %%LOCALAPPDATA%%\\UzPainter\\selftest)\n"
                 "  --report   report path (default <out-dir>\\selftest-report.json)\n"
                 "  --no-gpu   skip the stages that need a GPU (also UZP_NO_GPU=1)\n");
}

std::filesystem::path DefaultOutDir() {
    const wchar_t* local = _wgetenv(L"LOCALAPPDATA");
    if (local && *local) return std::filesystem::path(local) / L"UzPainter" / L"selftest";
    return std::filesystem::current_path() / L"uzpainter-selftest";
}

/// spdlog sink keeping the render core's warnings and errors for stage failure reasons.
void InstallLogTap() {
    auto sink = std::make_shared<spdlog::sinks::callback_sink_mt>(
        [](const spdlog::details::log_msg& msg) {
            if (msg.level < spdlog::level::warn) return;
            std::lock_guard<std::mutex> lock(g_logMutex);
            if (g_logProblems.size() < 32) {
                g_logProblems.emplace_back(msg.payload.data(), msg.payload.size());
            }
        });
    uz::LogAddSink(sink);
}

}  // namespace

int RunSelftestCommand(const std::vector<std::string>& args) {
    Options options;
    for (size_t i = 0; i < args.size(); ++i) {
        const std::string& arg = args[i];
        if (arg == "--no-gpu") {
            options.noGpu = true;
            options.noGpuReason = "--no-gpu on the command line";
        } else if ((arg == "--out-dir" || arg == "--report") && i + 1 < args.size()) {
            (arg == "--out-dir" ? options.outDir : options.reportPath) =
                std::filesystem::u8path(args[++i]);
        } else {
            Usage();
            return kExitUsage;
        }
    }
    const char* envNoGpu = std::getenv("UZP_NO_GPU");
    if (!options.noGpu && envNoGpu && std::string(envNoGpu) == "1") {
        options.noGpu = true;
        options.noGpuReason =
            "UZP_NO_GPU=1 (hosted CI has no GPU, decision 028; the hardware slice runs on the "
            "owner's machine)";
    }
    if (options.outDir.empty()) options.outDir = DefaultOutDir();
    if (options.reportPath.empty()) options.reportPath = options.outDir / "selftest-report.json";
    std::error_code ec;
    std::filesystem::create_directories(options.outDir, ec);
    if (ec) {
        std::fprintf(stderr, "selftest: cannot create %s: %s\n", options.outDir.string().c_str(),
                     ec.message().c_str());
        return kExitFailed;
    }

    uz::LogInit((options.outDir / "selftest.log").string().c_str());
    uz::LogSuppressConsole();
    uz::LogSetLevel(uz::LogLevel::Info);
    InstallLogTap();

    SelftestContext context(std::move(options));
    Selftest selftest;
    RegisterHardwareSlice(selftest);
    const int code = selftest.Run(context);
    uz::LogFlushAll();
    if (context.gpuUnrecoverable) {
        // The device's teardown waits for the GPU without a deadline; the report is written,
        // so end the process here instead of hanging in that wait.
        std::fflush(nullptr);
        TerminateProcess(GetCurrentProcess(), static_cast<UINT>(code));
    }
    TeardownHardwareSlice(context);
    uz::LogShutdown();
    return code;
}

}  // namespace uzp::selftest
