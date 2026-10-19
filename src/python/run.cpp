// `UzPainter.exe run` (run.h).

#include "python/run.h"

#include <exception>
#include <filesystem>
#include <optional>

#include <pybind11/embed.h>

#include "export/receipt.h"
#include "python/capture.h"
#include "python/interpreter.h"
#include "python/script.h"
#include "python/session.h"
#include "render/backend.h"
#include "uzp_core/manifest/json.h"

namespace uzp::python {

namespace {

namespace json = core::json;

constexpr const char* kUsage =
    "usage: UzPainter.exe run <script.py> [args...] [--gpu-backend dx12|vulkan] [--diagnostic-measure-export] "
    "[-- args...]\n";
constexpr std::string_view kDiagnosticFlag = "--diagnostic-measure-export";

/// Set once, before the script runs, by `--diagnostic-measure-export` (decision 286).
bool g_diagnosticMeasureExport = false;

void PrintJson(std::FILE* out, const json::Object& object) {
    std::fprintf(out, "%.*s%s\n", static_cast<int>(kJsonPrefix.size()), kJsonPrefix.data(),
                 json::WriteCanonical(object).c_str());
    std::fflush(out);
}

/// Ctrl+C and Ctrl+Break raise KeyboardInterrupt in the script, a structured failure, after which
/// the host closes the project it left open as after any run. Without a handler the console's
/// default ends the process at once (exit status 0xC000013A). Requires the GIL.
void InterruptOnConsoleBreak() {
    const pybind11::module_ signal = pybind11::module_::import("signal");
    for (const char* name : {"SIGINT", "SIGBREAK"}) {
        signal.attr("signal")(signal.attr(name), signal.attr("default_int_handler"));
    }
}

}  // namespace

bool IsRunCommand(std::string_view verb) { return verb == "run"; }

bool DiagnosticMeasureExport() { return g_diagnosticMeasureExport; }

int RunRunCommand(const std::vector<std::string>& args, std::FILE* out, std::FILE* err) {
    std::optional<render::Backend> backend;
    bool diagnostic = false;
    std::vector<std::string> positional;
    for (size_t i = 1; i < args.size(); ++i) {
        if (args[i] == "--") {  // the rest goes to the script as given
            positional.insert(positional.end(), args.begin() + static_cast<std::ptrdiff_t>(i) + 1, args.end());
            break;
        }
        if (args[i] == kDiagnosticFlag) {
            if (diagnostic) {
                std::fprintf(err, "%s", kUsage);
                return kRunUsage;
            }
            diagnostic = true;
            continue;
        }
        if (args[i] != "--gpu-backend") {
            positional.push_back(args[i]);
            continue;
        }
        const std::optional<render::Backend> parsed =
            i + 1 < args.size() ? render::ParseBackend(args[i + 1]) : std::nullopt;
        if (backend || !parsed) {
            std::fprintf(err, "%s", kUsage);
            return kRunUsage;
        }
        backend = parsed;
        ++i;
    }
    if (positional.empty()) {
        std::fprintf(err, "%s", kUsage);
        return kRunUsage;
    }
    g_diagnosticMeasureExport = diagnostic;
    const std::string backend_name(render::BackendName(backend.value_or(render::Backend::Dx12)));
    // The first GPU operation (a painter_viewport capture) creates its device on this backend.
    SetCaptureGpu(backend.value_or(render::Backend::Dx12), nullptr);

    const std::string error = Start();
    if (!error.empty()) {
        PrintJson(out, json::Object{{"status", "host_error"},
                                    {"gpu_backend", backend_name},
                                    {"error", json::Object{{"type", "InterpreterError"},
                                                           {"message", "cannot start the interpreter: " + error}}}});
        return kRunHostError;
    }
    int status = kRunHostError;
    {
        pybind11::gil_scoped_acquire gil;
        json::Object report;
        try {
            InterruptOnConsoleBreak();
            report = RunScript(PathFromUtf8(positional.front()),
                               std::vector<std::string>(positional.begin() + 1, positional.end()));
            status = std::get<std::string>(report.at("status").data) == "ok" ? kRunOk : kRunFailed;
        } catch (const std::exception& error) {
            // The host failed around the script (a value it could not hand over or report): never
            // an uncaught exception, which would end the process without a report.
            report = json::Object{{"status", "host_error"},
                                  {"error", json::Object{{"type", "HostError"}, {"message", error.what()}}}};
        }
        report["gpu_backend"] = backend_name;
        if (diagnostic) report["diagnostic"] = std::string(exporter::kDiagnosticMeasureMode);
        PrintJson(out, report);
    }
    // A project the script left open is closed (its lock released, an untitled folder removed)
    // unless a job still uses it.
    Session& session = Session::Get();
    try {
        if (session.IsOpen()) session.Close();
    } catch (const std::exception& e) {
        std::fprintf(err, "UzPainter.exe run: the project left open was not closed: %s\n", e.what());
    }
    std::fflush(err);
    return status;
}

}  // namespace uzp::python
