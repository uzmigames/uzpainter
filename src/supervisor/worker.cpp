// The worker role (worker.h).

#include "supervisor/worker.h"

#include <algorithm>
#include <atomic>
#include <charconv>
#include <chrono>
#include <condition_variable>
#include <csignal>
#include <cstdlib>
#include <deque>
#include <filesystem>
#include <fstream>
#include <functional>
#include <map>
#include <memory>
#include <mutex>
#include <optional>
#include <string_view>
#include <thread>
#include <utility>

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>

#include <pybind11/embed.h>

#include "crash_handler.h"
#include "evaluator/evaluator.h"
#include "evaluator/geometry_mask.h"
#include "evaluator/sources.h"
#include "evaluator/templates.h"
#include "mesh/reload.h"
#include "python/display.h"
#include "python/errors.h"
#include "python/interpreter.h"
#include "python/script.h"
#include "python/session.h"
#include "render/backend.h"
#include "render/engine_thread.h"
#include "store/container.h"
#include "supervisor/fault_hooks.h"
#include "supervisor/ipc.h"
#include "supervisor/pipe.h"
#include "uzp_core/manifest/sha256.h"
#include "uzp_core/types/enums.h"

namespace uzp::supervisor {

namespace {

namespace json = core::json;

constexpr const char* kUsage =
    "usage: UzPainter.exe --worker --pipe \\\\.\\pipe\\uzpainter-<supervisor-pid>-<n> --gpu-backend dx12|vulkan\n"
    "                     [--allow-python] [--gpu-deadline-ms <ms>] [--output-root <dir>] [--crash-dir <dir>]\n"
    "                     [--connect-timeout-ms <ms>] [--test-faults]\n";

constexpr std::string_view kPipePrefix = "\\\\.\\pipe\\uzpainter-";

struct Options {
    std::string pipe;
    std::uint32_t supervisor_pid = 0;
    render::Backend backend = render::Backend::Dx12;
    bool allow_python = false;
    std::chrono::milliseconds gpu_deadline{60'000};
    std::chrono::milliseconds connect_timeout{30'000};
    std::filesystem::path output_root;
    std::filesystem::path crash_dir;
    bool test_faults = false;
};

std::optional<std::uint64_t> Digits(std::string_view text) {
    std::uint64_t value = 0;
    const auto [end, ec] = std::from_chars(text.data(), text.data() + text.size(), value);
    if (ec != std::errc() || end != text.data() + text.size() || text.empty()) return std::nullopt;
    return value;
}

/// The supervisor's process id from `\\.\pipe\uzpainter-<pid>-<n>`.
std::optional<std::uint32_t> SupervisorPid(std::string_view pipe) {
    if (!pipe.starts_with(kPipePrefix)) return std::nullopt;
    const std::string_view rest = pipe.substr(kPipePrefix.size());
    const std::size_t dash = rest.find('-');
    if (dash == std::string_view::npos) return std::nullopt;
    const std::optional<std::uint64_t> pid = Digits(rest.substr(0, dash));
    if (!pid || *pid == 0 || *pid > 0xFFFFFFFFull || !Digits(rest.substr(dash + 1))) return std::nullopt;
    return static_cast<std::uint32_t>(*pid);
}

std::optional<Options> Parse(const std::vector<std::string>& args, std::string& error) {
    Options options;
    bool backend_given = false;
    for (std::size_t i = 1; i < args.size(); ++i) {
        const std::string& arg = args[i];
        const auto value = [&]() -> const std::string* { return i + 1 < args.size() ? &args[++i] : nullptr; };
        if (arg == "--allow-python") {
            options.allow_python = true;
        } else if (arg == "--test-faults") {
            options.test_faults = true;
        } else if (arg == "--pipe" || arg == "--gpu-backend" || arg == "--gpu-deadline-ms" || arg == "--output-root" ||
                   arg == "--crash-dir" || arg == "--connect-timeout-ms") {
            const std::string* v = value();
            if (!v) {
                error = arg + " needs a value";
                return std::nullopt;
            }
            if (arg == "--pipe") {
                const std::optional<std::uint32_t> pid = SupervisorPid(*v);
                if (!pid) {
                    error = "--pipe must be \\\\.\\pipe\\uzpainter-<supervisor-pid>-<n>";
                    return std::nullopt;
                }
                options.pipe = *v;
                options.supervisor_pid = *pid;
            } else if (arg == "--gpu-backend") {
                const std::optional<render::Backend> backend = render::ParseBackend(*v);
                if (!backend) {
                    error = "--gpu-backend must be dx12 or vulkan";
                    return std::nullopt;
                }
                options.backend = *backend;
                backend_given = true;
            } else if (arg == "--gpu-deadline-ms" || arg == "--connect-timeout-ms") {
                const std::optional<std::uint64_t> ms = Digits(*v);
                if (!ms || *ms == 0 || *ms > 86'400'000) {
                    error = arg + " must be a whole number of milliseconds between 1 and 86400000";
                    return std::nullopt;
                }
                (arg == "--gpu-deadline-ms" ? options.gpu_deadline : options.connect_timeout) =
                    std::chrono::milliseconds(*ms);
            } else if (arg == "--output-root") {
                options.output_root = python::PathFromUtf8(*v);
            } else {
                options.crash_dir = python::PathFromUtf8(*v);
            }
        } else {
            error = "unknown argument " + arg;
            return std::nullopt;
        }
    }
    if (options.pipe.empty() || !backend_given) {
        error = "--pipe and --gpu-backend are required";
        return std::nullopt;
    }
    if (options.output_root.empty()) {
        options.output_root = std::filesystem::temp_directory_path() /
                              ("uzpainter-" + std::to_string(options.supervisor_pid)) / "outputs";
    }
    return options;
}

// ── Crash reports ──────────────────────────────────────────────────────────────────────────────

/// `abort()` (an assertion, `std::terminate`, the vendored command list's `FatalErrorLoop`)
/// becomes an exception the crash handler reports with a minidump.
void AbortToCrashReport(int) { RaiseException(kAbortExceptionCode, EXCEPTION_NONCONTINUABLE, 0, nullptr); }

void InstallCrashReporting(const std::filesystem::path& crash_dir) {
    // No Windows error dialogs: a fault ends the worker, and the supervisor relaunches it.
    SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX);
    if (!crash_dir.empty()) {
        std::error_code ignored;
        std::filesystem::create_directories(crash_dir, ignored);
        // The handler keeps its own copy of the ANSI path.
        uz::CrashHandler_SetCrashDir(crash_dir.string().c_str());
    }
    uz::InstallCrashHandler();
    std::signal(SIGABRT, AbortToCrashReport);
}

[[noreturn]] void Exit(int code) {
    std::fflush(stdout);
    std::fflush(stderr);
    TerminateProcess(GetCurrentProcess(), static_cast<UINT>(code));
    std::_Exit(code);
}

// ── Tools ──────────────────────────────────────────────────────────────────────────────────────

/// A failed call: the reply's `error`.
struct CallError {
    std::string code;
    std::string message;
    json::Object details;
};

struct Tool {
    std::string name;
    std::string description;
    json::Object input_schema;
    bool mutating = false;
    bool gpu = false;
};

json::Object Schema(json::Object properties, json::Array required) {
    return {{"type", "object"},
            {"properties", std::move(properties)},
            {"required", std::move(required)},
            {"additionalProperties", false}};
}

json::Object StringProperty(const char* description) { return {{"type", "string"}, {"description", description}}; }

const json::Value* Field(const json::Object& object, std::string_view key) {
    const auto it = object.find(key);
    return it == object.end() ? nullptr : &it->second;
}

std::optional<std::string> StringField(const json::Object& object, std::string_view key) {
    const json::Value* value = Field(object, key);
    if (!value || !value->IsString()) return std::nullopt;
    return std::get<std::string>(value->data);
}

/// The absolute path of the store that durably holds `open`: the file a saved project was
/// opened or saved as (resolved when that call ran), or the temporary store of an untitled one.
std::string DurableStore(const python::OpenProject& open) {
    return python::Utf8(open.untitled_dir.empty() ? open.project_source : std::filesystem::absolute(open.store->path()));
}

/// `{"event": "revision", "revision", "project", "untitled"}`: the open project's revision and
/// durable store (null, null and false when none is open).
json::Object RevisionEvent() {
    python::Session& session = python::Session::Get();
    json::Object event{{"event", "revision"}, {"revision", nullptr}, {"project", nullptr}, {"untitled", false}};
    if (const std::shared_ptr<python::OpenProject> open = session.IsOpen() ? session.Current() : nullptr) {
        event["revision"] = open->document->revision();
        event["project"] = DurableStore(*open);
        event["untitled"] = !open->untitled_dir.empty();
    }
    return event;
}

class Worker {
public:
    Worker(const Options& options, render::Engine& engine) : m_options(options), m_engine(engine) { DefineTools(); }

    /// The reply to one request frame.
    json::Object Handle(const json::Object& request);

    /// Set by a call after which the worker must exit (after its reply).
    std::optional<int> exit_after_reply;

private:
    using Handler = std::function<json::Object(const json::Object& arguments)>;

    void DefineTools();
    json::Object Call(const json::Value& id, const json::Object& request);
    json::Object Reopen(const json::Value& id, const json::Object& request);
    json::Object ListTools() const;
    std::optional<std::int64_t> CommittedRevision() const;

    json::Object ProjectOpen(const json::Object& arguments);
    json::Object ProjectClose(const json::Object& arguments);
    json::Object ProjectSave(const json::Object& arguments);
    json::Object ProjectInspect(const json::Object& arguments);
    json::Object EvaluateChannel(const json::Object& arguments);
    json::Object DisplaySet(const json::Object& arguments);
    json::Object ShaderSet(const json::Object& arguments);
    json::Object CameraGet(const json::Object& arguments);
    json::Object CameraSet(const json::Object& arguments);
    json::Object RunPython(const json::Object& arguments);
#if defined(UZP_WORKER_FAULT_HOOKS)
    json::Object TestFault(const json::Object& arguments);
#endif

    [[noreturn]] void FailRender(const render::Error& error);

    const Options& m_options;
    render::Engine& m_engine;
    std::vector<Tool> m_tools;
    std::map<std::string, Handler, std::less<>> m_handlers;
    std::unique_ptr<evaluator::Evaluator> m_evaluator;
    std::uint64_t m_payloads = 0;
};

void Worker::DefineTools() {
    const auto add = [this](Tool tool, Handler handler) {
        m_handlers.emplace(tool.name, std::move(handler));
        m_tools.push_back(std::move(tool));
    };
    add({"project_open", "Opens a project file in the worker (one project at a time).",
         Schema({{"path", StringProperty("The .uzp file.")}}, {"path"}), false, false},
        [this](const json::Object& a) { return ProjectOpen(a); });
    add({"project_close", "Closes the open project.", Schema({}, {}), false, false},
        [this](const json::Object& a) { return ProjectClose(a); });
    add({"project_save", "Names a checkpoint of the current revision (save; `full` also compacts).",
         Schema({{"mode", json::Object{{"type", "string"}, {"enum", json::Array{"incremental", "full"}}}}}, {}), false,
         false},
        [this](const json::Object& a) { return ProjectSave(a); });
    add({"project_inspect", "The open project: path, revision and texture sets with their stacks.", Schema({}, {}), false,
         false},
        [this](const json::Object& a) { return ProjectInspect(a); });
    add({"evaluate_channel",
         "Evaluates one channel of one stack on the GPU and writes its tiles under the output root "
         "(path + SHA-256).",
         Schema({{"texture_set", StringProperty("Texture set name; the active one when omitted.")},
                 {"stack", StringProperty("Stack name; the texture set's active or first stack when omitted.")},
                 {"channel", StringProperty("Channel type, e.g. BaseColor.")}},
                {"channel"}),
         false, true},
        [this](const json::Object& a) { return EvaluateChannel(a); });
    // The display state of the fixed render pipeline (src/python/display.h; decisions 038, 042, 132).
    add({"display_get", "The display state: the active preset's fields, `parity` and the shader.", Schema({}, {}), false,
         false},
        [](const json::Object&) { return python::display::State(*python::Session::Get().ReadProject()); });
    add({"display_set",
         "Sets display values in one transaction: a whole `preset` first, then any of environment (SHA-256 or null), "
         "exposure, rotation, opacity, blur, shadows, background (sRGB8) and color_lut (null). Values outside the "
         "fixed render pipeline are refused before any change (decision 038).",
         Schema({{"preset", json::Object{{"type", "object"}}},
                 {"environment", json::Object{{"type", json::Array{"string", "null"}}}},
                 {"exposure", json::Object{{"type", "number"}}},
                 {"rotation", json::Object{{"type", "number"}}},
                 {"opacity", json::Object{{"type", "number"}}},
                 {"blur", json::Object{{"type", "number"}}},
                 {"shadows", json::Object{{"type", "boolean"}}},
                 {"background", json::Object{{"type", "array"}, {"items", json::Object{{"type", "integer"}}}}},
                 {"color_lut", json::Object{{"type", "null"}}}},
                {}),
         true, false},
        [this](const json::Object& a) { return DisplaySet(a); });
    add({"shader_get", "The shader and its parameters: the default open-pbr instance (decision 042).", Schema({}, {}),
         false, false},
        [](const json::Object&) { return python::display::Shader(*python::Session::Get().ReadProject()); });
    add({"shader_set", "Accepts only the default open-pbr instance's parameter values (decision 042).",
         Schema({{"parameters", json::Object{{"type", "object"}}}}, {"parameters"}), true, false},
        [this](const json::Object& a) { return ShaderSet(a); });
    add({"camera_get", "The default camera in Painter's convention and in Blender's (null when none is set).",
         Schema({}, {}), false, false},
        [this](const json::Object& a) { return CameraGet(a); });
    add({"camera_set",
         "Sets the default camera from a whole record, in Painter's convention (`camera`) or Blender's (`blender`).",
         Schema({{"camera", json::Object{{"type", "object"}}}, {"blender", json::Object{{"type", "object"}}}}, {}), true,
         false},
        [this](const json::Object& a) { return CameraSet(a); });
    if (m_options.allow_python) {
        add({"run_python", "Runs Python source in the worker's interpreter (only with --allow-python).",
             Schema({{"code", StringProperty("The Python source.")},
                     {"args", json::Object{{"type", "array"}, {"items", json::Object{{"type", "string"}}}}}},
                    {"code"}),
             true, false},
            [this](const json::Object& a) { return RunPython(a); });
    }
#if defined(UZP_WORKER_FAULT_HOOKS)
    if (m_options.test_faults) {
        add({"test_fault", "Test-only fault hook (Debug builds under --test-faults).",
             Schema({{"fault", json::Object{{"type", "string"},
                                            {"enum", json::Array{"kill", "abort", "seh", "remove_device", "gpu_stall",
                                                                 "kill_before_reply"}}}}},
                    {"fault"}),
             false, false},
            [this](const json::Object& a) { return TestFault(a); });
    }
#endif
}

json::Object Worker::ListTools() const {
    json::Array tools;
    for (const Tool& tool : m_tools) {
        tools.push_back(json::Object{{"name", tool.name},
                                     {"description", tool.description},
                                     {"inputSchema", tool.input_schema},
                                     {"mutating", tool.mutating},
                                     {"gpu", tool.gpu}});
    }
    return {{"tools", std::move(tools)}};
}

std::optional<std::int64_t> Worker::CommittedRevision() const {
    python::Session& session = python::Session::Get();
    if (!session.IsOpen()) return std::nullopt;
    return session.Revision();
}

json::Object Worker::Handle(const json::Object& request) {
    const json::Value* id = Field(request, "id");
    if (!id || !id->IsString() || std::get<std::string>(id->data).empty()) {
        return ErrorReply(nullptr, "invalid_request", "a request needs a non-empty string id");
    }
    const std::optional<std::string> method = StringField(request, "method");
    if (method == "tools/list") return ResultReply(*id, ListTools(), CommittedRevision());
    if (method == "tools/call") return Call(*id, request);
    if (method == "worker/reopen") return Reopen(*id, request);
    return ErrorReply(*id, "unknown_method", "unknown method " + method.value_or("(none)"),
                      json::Object{{"method", method ? json::Value(*method) : json::Value(nullptr)}});
}

json::Object Worker::Call(const json::Value& id, const json::Object& request) {
    const std::optional<std::string> name = StringField(request, "name");
    if (!name) return ErrorReply(id, "invalid_request", "tools/call needs a tool name");
    json::Object arguments;
    if (const json::Value* given = Field(request, "arguments"); given && !given->IsNull()) {
        if (!given->IsObject()) return ErrorReply(id, "invalid_request", "arguments must be an object");
        arguments = std::get<json::Object>(given->data);
    }
    // The Python gate comes first: without --allow-python, `run_python` is not a tool of this
    // worker, and no part of the request is looked at further.
    if (*name == "run_python" && !m_options.allow_python) {
        return ErrorReply(id, "python_disabled", "run_python is disabled: the worker runs without --allow-python");
    }
    const auto tool = std::ranges::find(m_tools, *name, &Tool::name);
    if (tool == m_tools.end()) {
        return ErrorReply(id, "unknown_tool", "unknown tool " + *name, json::Object{{"name", *name}});
    }
    if (tool->mutating) {
        const std::optional<std::string> key = StringField(request, "idempotency_key");
        const json::Value* expected = Field(request, "expected_revision");
        if (!key || key->empty() || !expected || !expected->IsInt()) {
            return ErrorReply(id, "invalid_request",
                              "a mutating call needs idempotency_key (string) and expected_revision (integer)");
        }
        const std::optional<std::int64_t> current = CommittedRevision();
        const std::int64_t want = std::get<std::int64_t>(expected->data);
        if (current && *current != want) {
            return ErrorReply(id, "stale_revision", "the project is at another revision than the call expected",
                              json::Object{{"expected", want}, {"current", *current}});
        }
    }
    if (tool->gpu) {
        if (const std::optional<render::Error>& unavailable = m_engine.DeviceError()) {
            return ErrorReply(id, std::string(render::ErrorCodeName(unavailable->code)), unavailable->Describe(),
                              json::Object{{"backend", std::string(render::BackendName(m_options.backend))},
                                           {"reason", unavailable->reason}});
        }
    }
    try {
        json::Object result = m_handlers.at(*name)(arguments);
        return ResultReply(id, std::move(result), CommittedRevision());
    } catch (const CallError& error) {
        return ErrorReply(id, error.code, error.message, error.details);
    } catch (const python::ApiError& error) {
        json::Object details{{"type", error.cls()}};
        std::string code = "call_failed";
        if (error.cls() == "StaleRevisionError") {
            code = "stale_revision";
            details["expected"] = error.expected;
            details["current"] = error.current;
        } else if (error.cls() == "BusyError") {
            code = "busy";
            details["job_id"] = error.job_id;
        } else if (error.cls() == "ProjectError") {
            code = "project_error";
        }
        if (!error.details.empty()) details["details"] = error.details;
        return ErrorReply(id, std::move(code), error.what(), std::move(details));
    } catch (const std::exception& error) {
        return ErrorReply(id, "call_failed", error.what(), json::Object{{"type", "RuntimeError"}});
    }
}

/// `worker/reopen {path, untitled}`: the supervisor's recovery reopens the store the dead worker
/// held (its last `revision` event), an untitled project as untitled. Not a tool.
json::Object Worker::Reopen(const json::Value& id, const json::Object& request) {
    const std::optional<std::string> path = StringField(request, "path");
    const json::Value* untitled = Field(request, "untitled");
    if (!path || !untitled || !untitled->IsBool()) {
        return ErrorReply(id, "invalid_request", "worker/reopen needs path (string) and untitled (boolean)");
    }
    try {
#if defined(UZP_WORKER_FAULT_HOOKS)
        if (m_options.test_faults) fault::MaybeKillOnOpen();
#endif
        python::Session& session = python::Session::Get();
        session.Open(python::PathFromUtf8(*path), std::get<bool>(untitled->data));
        return ResultReply(id, {{"path", DurableStore(*session.Current())}, {"revision", session.Revision()}},
                           CommittedRevision());
    } catch (const std::exception& error) {
        return ErrorReply(id, "reopen_failed", error.what(), json::Object{{"path", *path}});
    }
}

void Worker::FailRender(const render::Error& error) {
    // A removed device or a stalled GPU leaves the engine unusable: the call fails and the worker
    // exits after the reply (02 §5).
    if (error.code == render::ErrorCode::DeviceRemoved || error.code == render::ErrorCode::Timeout) {
        exit_after_reply = kWorkerExitDeviceFault;
    }
    json::Object details{{"reason", error.reason}};
    if (error.backend) details["backend"] = std::string(render::BackendName(*error.backend));
    throw CallError{std::string(render::ErrorCodeName(error.code)), error.Describe(), std::move(details)};
}

json::Object Worker::ProjectOpen(const json::Object& arguments) {
    const std::optional<std::string> path = StringField(arguments, "path");
    if (!path) throw CallError{"invalid_arguments", "project_open needs a path", {}};
    python::Session& session = python::Session::Get();
    session.Open(python::PathFromUtf8(*path));
    return {{"path", DurableStore(*session.Current())}, {"revision", session.Revision()}};
}

json::Object Worker::ProjectClose(const json::Object&) {
    python::Session::Get().Close();
    return {};
}

json::Object Worker::ProjectSave(const json::Object& arguments) {
    const std::string mode = StringField(arguments, "mode").value_or("incremental");
    if (mode != "incremental" && mode != "full") throw CallError{"invalid_arguments", "mode must be incremental or full", {}};
    const core::Checkpoints saved =
        python::Session::Get().Save(mode == "full" ? store::SaveMode::full : store::SaveMode::incremental);
    json::Object result{{"current", saved.current}};
    result["named"] = saved.named ? json::Value(*saved.named) : json::Value(nullptr);
    result["previous"] = saved.previous ? json::Value(*saved.previous) : json::Value(nullptr);
    return result;
}

json::Object Worker::ProjectInspect(const json::Object&) {
    python::Session& session = python::Session::Get();
    if (!session.IsOpen()) return {{"open", false}};
    const std::shared_ptr<const core::Project> project = session.ReadProject();
    json::Array sets;
    for (const core::TextureSet& set : project->texture_sets) {
        json::Array stacks;
        for (const core::Stack& stack : set.stacks) stacks.push_back(stack.name);
        sets.push_back(json::Object{{"name", set.name}, {"stacks", std::move(stacks)}});
    }
    const std::optional<std::filesystem::path> path = session.FilePath();
    return {{"open", true},
            {"path", path ? json::Value(python::Utf8(*path)) : json::Value(nullptr)},
            {"revision", session.Revision()},
            {"texture_sets", std::move(sets)}};
}

json::Object Worker::DisplaySet(const json::Object& arguments) {
    python::Session& session = python::Session::Get();
    session.Mutate("display_set", arguments, [&](core::Edit& edit) {
        if (const json::Value* preset = Field(arguments, "preset")) python::display::ApplyPreset(edit, *preset);
        if (const json::Value* environment = Field(arguments, "environment")) {
            python::display::SetEnvironment(edit, "display_set", *environment);
        }
        for (const char* key : {"exposure", "rotation", "opacity", "blur", "shadows", "background"}) {
            if (const json::Value* value = Field(arguments, key)) python::display::SetValue(edit, "display_set", key, *value);
        }
        if (const json::Value* lut = Field(arguments, "color_lut")) python::display::SetColorLut(edit, "display_set", *lut);
    });
    return python::display::State(*session.ReadProject());
}

json::Object Worker::ShaderSet(const json::Object& arguments) {
    python::Session& session = python::Session::Get();
    const json::Value* parameters = Field(arguments, "parameters");
    if (!parameters) throw CallError{"invalid_arguments", "shader_set needs parameters", {}};
    session.Mutate("shader_set", arguments, [&](core::Edit& edit) {
        python::display::SetShaderParameters(edit, "shader_set", *parameters);
    });
    return python::display::Shader(*session.ReadProject());
}

json::Object Worker::CameraGet(const json::Object&) {
    const json::Value camera = python::display::DefaultCamera(*python::Session::Get().ReadProject());
    if (camera.IsNull()) return {{"camera", nullptr}, {"blender", nullptr}};
    return {{"camera", camera}, {"blender", python::display::CameraToBlender(camera)}};
}

json::Object Worker::CameraSet(const json::Object& arguments) {
    const json::Value* camera = Field(arguments, "camera");
    const json::Value* blender = Field(arguments, "blender");
    if ((camera == nullptr) == (blender == nullptr)) {
        throw CallError{"invalid_arguments", "camera_set needs exactly one of camera and blender", {}};
    }
    const json::Value record = camera ? *camera : json::Value(python::display::CameraFromBlender(*blender));
    python::Session::Get().Mutate("camera_set", arguments,
                                  [&](core::Edit& edit) { python::display::SetCamera(edit, record, "camera_set"); });
    return CameraGet({});
}

json::Object Worker::EvaluateChannel(const json::Object& arguments) {
    const std::optional<std::string> channel_name = StringField(arguments, "channel");
    const std::optional<core::ChannelType> channel =
        channel_name ? core::FromString<core::ChannelType>(*channel_name) : std::nullopt;
    if (!channel) throw CallError{"invalid_arguments", "channel must name a channel type, e.g. BaseColor", {}};
    const std::shared_ptr<python::OpenProject> open = python::Session::Get().Current();
    const core::Snapshot snapshot = open->document->snapshot();
    const core::Project& project = *snapshot.project;

    const core::TextureSet* set = nullptr;
    const std::optional<std::string> set_name = StringField(arguments, "texture_set");
    for (const core::TextureSet& candidate : project.texture_sets) {
        if (set_name ? candidate.name == *set_name : candidate.id == open->active_set) set = &candidate;
    }
    if (!set) throw CallError{"invalid_arguments", "no texture set " + set_name.value_or("(active)"), {}};
    const core::Stack* stack = nullptr;
    const std::optional<std::string> stack_name = StringField(arguments, "stack");
    for (const core::Stack& candidate : set->stacks) {
        if (stack_name ? candidate.name == *stack_name : candidate.id == open->active_stack) stack = &candidate;
    }
    if (!stack && !stack_name && !set->stacks.empty()) stack = &set->stacks.front();
    if (!stack) throw CallError{"invalid_arguments", "no stack " + stack_name.value_or("(active)"), {}};

    store::ProjectStore* store = open->store.get();
    evaluator::EvaluateRequest request;
    request.textureSet = set->id;
    request.stack = stack->id;
    request.channel = *channel;
    request.templateId = project.settings.template_id;
    request.resources = std::make_shared<evaluator::DecodingResourceProvider>(
        [store](std::string_view sha256) -> std::optional<std::string> {
            try {
                return store->ReadResource(sha256);
            } catch (const store::StoreError& error) {
                if (error.code() == store::StoreError::Code::missing_resource) return std::nullopt;
                throw;
            }
        });
    if (project.mesh) {
        mesh::ImportResult mesh =
            mesh::RederiveMesh(project, [store](const std::string& sha256) { return store->ReadResource(sha256); });
        request.geometry = std::make_shared<evaluator::MeshGeometryMasks>(
            std::make_shared<const mesh::TexturingMesh>(std::move(mesh.mesh)));
    }
#if defined(UZP_WORKER_FAULT_HOOKS)
    if (fault::GpuFaultArmed()) {
        render::Result<void> injected =
            m_engine
                .Submit(std::make_shared<const core::Snapshot>(snapshot),
                        [](render::EngineContext& context, const core::Snapshot&) { return fault::InjectGpuFault(context); })
                .get();
        if (!injected) FailRender(injected.error());
    }
#endif
    if (!m_evaluator) {
        m_evaluator = std::make_unique<evaluator::Evaluator>(
            m_engine, std::make_shared<const evaluator::TemplateLibrary>(
                          evaluator::TemplateLibrary::Load(evaluator::TemplateLibrary::DefaultDirectory())));
    }
    render::Result<evaluator::ChannelResult> evaluated = m_evaluator->Evaluate(snapshot, std::move(request)).get();
    if (!evaluated) FailRender(evaluated.error());

    // The texels of every tile in order (constant tiles contribute none), under the output root.
    std::string texels;
    json::Array tiles;
    for (const evaluator::TileResult& tile : evaluated->tiles) {
        json::Object entry{{"x0", static_cast<std::int64_t>(tile.x0)},
                           {"y0", static_cast<std::int64_t>(tile.y0)},
                           {"width", static_cast<std::int64_t>(tile.width)},
                           {"height", static_cast<std::int64_t>(tile.height)}};
        if (tile.constant) {
            entry["constant"] = json::Array{(*tile.constant)[0], (*tile.constant)[1], (*tile.constant)[2]};
        } else {
            entry["offset"] = static_cast<std::int64_t>(texels.size());
            entry["bytes"] = static_cast<std::int64_t>(tile.texels.size());
            texels.append(reinterpret_cast<const char*>(tile.texels.data()), tile.texels.size());
        }
        tiles.push_back(std::move(entry));
    }
    std::filesystem::create_directories(m_options.output_root);
    const std::filesystem::path file =
        m_options.output_root / ("evaluate-r" + std::to_string(snapshot.revision) + "-" + std::to_string(GetCurrentProcessId()) +
                                 "-" + std::to_string(++m_payloads) + "-" + std::string(core::ToString(*channel)) + ".bin");
    {
        std::ofstream out(file, std::ios::binary | std::ios::trunc);
        out.write(texels.data(), static_cast<std::streamsize>(texels.size()));
        if (!out) throw CallError{"call_failed", "cannot write " + python::Utf8(file), {}};
    }
    return {{"revision", snapshot.revision},
            {"texture_set", set->name},
            {"stack", stack->name},
            {"channel", std::string(core::ToString(*channel))},
            {"format", std::string(core::ToString(evaluated->format))},
            {"width", static_cast<std::int64_t>(evaluated->width)},
            {"height", static_cast<std::int64_t>(evaluated->height)},
            {"tiles", std::move(tiles)},
            {"payload", json::Object{{"path", python::Utf8(file)},
                                     {"sha256", core::Sha256Hex(texels)},
                                     {"size", static_cast<std::int64_t>(texels.size())}}}};
}

json::Object Worker::RunPython(const json::Object& arguments) {
    const std::optional<std::string> code = StringField(arguments, "code");
    if (!code) throw CallError{"invalid_arguments", "run_python needs code", {}};
    std::vector<std::string> args;
    if (const json::Value* given = Field(arguments, "args"); given && !given->IsNull()) {
        if (!given->IsArray()) throw CallError{"invalid_arguments", "args must be a list of strings", {}};
        for (const json::Value& arg : std::get<json::Array>(given->data)) {
            if (!arg.IsString()) throw CallError{"invalid_arguments", "args must be a list of strings", {}};
            args.push_back(std::get<std::string>(arg.data));
        }
    }
    json::Object report;
    {
        pybind11::gil_scoped_acquire gil;
        report = python::RunSource("<run_python>", *code, args);
    }
    if (std::get<std::string>(report.at("status").data) != "ok") {
        // A script is not a transaction: the calls it committed before raising stay committed and
        // are named in the details (02 §5).
        std::string message = "the script raised";
        if (const json::Value* error = Field(report, "error"); error && error->IsObject()) {
            message = StringField(std::get<json::Object>(error->data), "message").value_or(message);
        }
        throw CallError{"script_failed", std::move(message), std::move(report)};
    }
    return report;
}

#if defined(UZP_WORKER_FAULT_HOOKS)
json::Object Worker::TestFault(const json::Object& arguments) {
    const std::optional<std::string> name = StringField(arguments, "fault");
    const std::optional<fault::Fault> parsed = name ? fault::Parse(*name) : std::nullopt;
    if (!parsed) throw CallError{"invalid_arguments", "unknown fault", {}};
    fault::Trigger(*parsed);
    return {{"armed", *name}};
}
#endif

// ── The request loop ───────────────────────────────────────────────────────────────────────────

/// Frames read from the pipe, handed to the interpreter's thread.
class Inbox {
public:
    void Push(json::Object frame) {
        {
            std::lock_guard lock(m_mutex);
            m_frames.push_back(std::move(frame));
        }
        m_ready.notify_one();
    }
    json::Object Pop() {
        std::unique_lock lock(m_mutex);
        m_ready.wait(lock, [this] { return !m_frames.empty(); });
        json::Object frame = std::move(m_frames.front());
        m_frames.pop_front();
        return frame;
    }

private:
    std::mutex m_mutex;
    std::condition_variable m_ready;
    std::deque<json::Object> m_frames;
};

}  // namespace

bool IsWorkerCommand(const std::string& first) { return first == "--worker"; }

bool FaultHooksCompiled() {
#if defined(UZP_WORKER_FAULT_HOOKS)
    return true;
#else
    return false;
#endif
}

int RunWorkerCommand(const std::vector<std::string>& args, std::FILE* err) {
    std::string error;
    const std::optional<Options> parsed = Parse(args, error);
    if (!parsed) {
        std::fprintf(err, "UzPainter.exe --worker: %s\n%s", error.c_str(), kUsage);
        return kWorkerExitUsage;
    }
    const Options& options = *parsed;
    if (options.test_faults && !FaultHooksCompiled()) {
        std::fprintf(err, "UzPainter.exe --worker: --test-faults needs a Debug build (the fault hooks are not compiled in)\n");
        return kWorkerExitUsage;
    }
    InstallCrashReporting(options.crash_dir);

    HANDLE supervisor = OpenProcess(SYNCHRONIZE, FALSE, options.supervisor_pid);
    if (!supervisor) {
        std::fprintf(err, "UzPainter.exe --worker: supervisor process %u is not running\n", options.supervisor_pid);
        return kWorkerExitSupervisorGone;
    }
    const std::wstring pipe_path = python::PathFromUtf8(options.pipe).wstring();
    std::unique_ptr<PipeServer> pipe = PipeServer::Create(pipe_path, error);
    if (!pipe) {
        std::fprintf(err, "UzPainter.exe --worker: cannot create %s: %s\n", options.pipe.c_str(), error.c_str());
        return kWorkerExitStartFailed;
    }

    // The engine thread creates the device of the requested backend; without one the worker still
    // serves GPU-free calls.
    render::EngineOptions engine_options;
    engine_options.device.backend = options.backend;
    engine_options.requestDeadline = options.gpu_deadline;
    render::Engine engine(engine_options);
    if (const std::optional<render::Error>& unavailable = engine.DeviceError()) {
        std::fprintf(err, "UzPainter.exe --worker: %s\n", unavailable->Describe().c_str());
    }
    if (const std::string started = python::Start(); !started.empty()) {
        std::fprintf(err, "UzPainter.exe --worker: cannot start the interpreter: %s\n", started.c_str());
        return kWorkerExitStartFailed;
    }

    if (!pipe->Accept(options.supervisor_pid, supervisor, options.connect_timeout, error)) {
        std::fprintf(err, "UzPainter.exe --worker: %s (%d other clients refused)\n", error.c_str(), pipe->RefusedClients());
        return kWorkerExitStartFailed;
    }
    // The supervisor's end: once its process ends, nothing further is committed.
    std::thread([supervisor] {
        WaitForSingleObject(supervisor, INFINITE);
        Exit(kWorkerExitSupervisorGone);
    }).detach();

    json::Object handshake = HandshakeFrame(Handshake{static_cast<std::int64_t>(GetCurrentProcessId()), BuildString(),
                                                      std::string(render::BackendName(options.backend)),
                                                      !engine.DeviceError().has_value(), options.allow_python});
#if defined(UZP_WORKER_FAULT_HOOKS)
    if (options.test_faults) handshake = fault::OverrideHandshake(std::move(handshake));
#endif
    if (!pipe->Write(EncodeFrame(handshake))) Exit(kWorkerExitSupervisorGone);

    Inbox inbox;
    PipeServer* reader_pipe = pipe.get();
    std::thread([reader_pipe, &inbox] {
        FrameDecoder decoder;
        for (;;) {
            const std::optional<std::string> bytes = reader_pipe->Read();
            if (!bytes) Exit(kWorkerExitSupervisorGone);  // broken pipe: commit nothing further
            Decoded decoded = decoder.Feed(*bytes);
            for (const std::string& message : decoded.errors) {
                reader_pipe->Write(EncodeFrame(ErrorReply(nullptr, "invalid_frame", message)));
            }
            for (json::Object& frame : decoded.frames) inbox.Push(std::move(frame));
        }
    }).detach();

    // What the worker durably holds goes to the supervisor after every commit and project switch,
    // before the call that caused it can reply: a reply lost to a crash loses neither.
    python::Session::Get().on_durable_change = [reader_pipe] {
        if (!reader_pipe->Write(EncodeFrame(RevisionEvent()))) Exit(kWorkerExitSupervisorGone);
    };

    Worker worker(options, engine);
    // The interpreter's thread holds the GIL only while Python runs (`run_python`).
    pybind11::gil_scoped_release release;
    for (;;) {
        const json::Object request = inbox.Pop();
        json::Object reply = worker.Handle(request);
#if defined(UZP_WORKER_FAULT_HOOKS)
        if (StringField(request, "name") != "test_fault" && fault::TakeKillBeforeReply()) fault::KillNow();
#endif
        std::string frame;
        try {
            frame = EncodeFrame(reply);
        } catch (const FrameError& e) {
            frame = EncodeFrame(ErrorReply(reply.at("id"), "reply_too_large", e.what()));
        }
        if (!pipe->Write(frame)) Exit(kWorkerExitSupervisorGone);
        if (worker.exit_after_reply) Exit(*worker.exit_after_reply);
    }
}

}  // namespace uzp::supervisor
