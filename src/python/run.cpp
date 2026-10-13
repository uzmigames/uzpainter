// `UzPainter.exe run` (run.h).

#include "python/run.h"

#include <exception>
#include <filesystem>
#include <optional>

#include <pybind11/embed.h>

#include "prof_scratch.h"
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
    "usage: UzPainter.exe run <script.py> [args...] [--gpu-backend dx12|vulkan] [-- args...]\n";

void PrintJson(std::FILE* out, const json::Object& object) {
    std::fprintf(out, "%.*s%s\n", static_cast<int>(kJsonPrefix.size()), kJsonPrefix.data(),
                 json::WriteCanonical(object).c_str());
    std::fflush(out);
}

}  // namespace

bool IsRunCommand(std::string_view verb) { return verb == "run"; }

int RunRunCommand(const std::vector<std::string>& args, std::FILE* out, std::FILE* err) {
    std::optional<render::Backend> backend;
    std::vector<std::string> positional;
    for (size_t i = 1; i < args.size(); ++i) {
        if (args[i] == "--") {  // the rest goes to the script as given
            positional.insert(positional.end(), args.begin() + static_cast<std::ptrdiff_t>(i) + 1, args.end());
            break;
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
    int status = kRunFailed;
    {
        pybind11::gil_scoped_acquire gil;
        UZP_PROF("run.script");
        json::Object report = RunScript(std::filesystem::path(positional.front()),
                                        std::vector<std::string>(positional.begin() + 1, positional.end()));
        report["gpu_backend"] = backend_name;
        status = std::get<std::string>(report.at("status").data) == "ok" ? kRunOk : kRunFailed;
        PrintJson(out, report);
    }
    // A project the script left open is closed (its lock released, an untitled folder removed)
    // unless a job still uses it.
    Session& session = Session::Get();
    try {
        UZP_PROF("run.close");
        if (session.IsOpen()) session.Close();
    } catch (const std::exception& e) {
        std::fprintf(err, "UzPainter.exe run: the project left open was not closed: %s\n", e.what());
    }
    std::fflush(err);
    return status;
}

}  // namespace uzp::python
