// `uzpainter.logging`, `.application` (with the engine-computation state, phase1.21), `.event` (the
// Python dispatcher thread, dispatcher.h), `.properties` and `.baking` (the bake parameters,
// bind_baking.cpp; the bake itself and the link groups are release gaps: every such call raises
// `NotYetSupported` naming its owner task before anything changes, decision 082); `.diagnostics`
// (bind_diagnostics.cpp); `.display`, `render.display` and `render.shader` (bind_display.cpp); and
// `.capabilities` (capabilities.h, phase1.22).

#include "python/bindings.h"
#include "python/capabilities.h"
#include "python/dispatcher.h"
#include "python/errors.h"
#include "python/jobs.h"

namespace uzp::python {

namespace {

constexpr const char* kLogging = R"PY(
import sys as _sys

INFO = 0
WARNING = 1
ERROR = 2
DBG_INFO = 3
DBG_WARNING = 4
DBG_ERROR = 5
_NAMES = {INFO: "INFO", WARNING: "WARNING", ERROR: "ERROR",
          DBG_INFO: "DBG_INFO", DBG_WARNING: "DBG_WARNING", DBG_ERROR: "DBG_ERROR"}


def log(severity, channel, message):
    """Writes `[<severity>] <channel>: <message>` to the script's standard error."""
    if severity not in _NAMES:
        raise ValueError(f"unknown severity {severity!r}")
    _sys.stderr.write(f"[{_NAMES[severity]}] {channel}: {message}\n")


def info(message):
    log(INFO, "Python", message)


def warning(message):
    log(WARNING, "Python", message)


def error(message):
    log(ERROR, "Python", message)
)PY";

constexpr const char* kEngineContext = R"PY(
import contextlib as _contextlib


@_contextlib.contextmanager
def disable_engine_computations():
    """Disables the engine computations for the block, then enables them again."""
    enable_engine_computations(False)
    try:
        yield
    finally:
        enable_engine_computations(True)
)PY";

/// Defines functions `names` in `module` that raise `NotYetSupported` naming `owner`.
void Gaps(py::module_& module, const std::string& qualified, std::initializer_list<const char*> names, const char* owner) {
    py::dict scope;
    scope["NotYetSupported"] = ExceptionClass("NotYetSupported");
    py::exec(R"PY(
def _gap(qualified, name, owner):
    def call(*args, **kwargs):
        raise NotYetSupported(f"{qualified}.{name} is a release gap ({owner})")
    call.__name__ = name
    call.__qualname__ = name
    call.__doc__ = f"Release gap: raises NotYetSupported before any mutation ({owner})."
    return call
)PY",
             scope);
    for (const char* name : names) module.attr(name) = scope["_gap"](qualified, name, owner);
}

}  // namespace

void BindMisc(py::module_& m) {
    py::module_ sys_modules = py::module_::import("sys");
    const auto submodule = [&](py::module_& parent, const char* name, const std::string& qualified, const char* doc) {
        py::module_ child = parent.def_submodule(name, doc);
        sys_modules.attr("modules")[py::str(qualified)] = child;
        return child;
    };

    py::module_ logging = submodule(m, "logging", "uzpainter.logging", "Messages to the script's log (standard error).");
    py::exec(kLogging, logging.attr("__dict__"));

    py::module_ application = submodule(m, "application", "uzpainter.application", "Application-wide information.");
    application.def("version", [] { return std::string(kAppVersion); }, "UzPainter's version string.");
    application.def("version_info", [] {
        const std::string text = kAppVersion;
        const std::size_t a = text.find('.');
        const std::size_t b = text.find('.', a + 1);
        return py::make_tuple(std::stoi(text.substr(0, a)), std::stoi(text.substr(a + 1, b - a - 1)),
                              std::stoi(text.substr(b + 1)));
    });
    application.def(
        "enable_engine_computations", [](bool enable) { JobEngine::Get().SetPaused(!enable); }, py::arg("enable"),
        "Enables or disables the engine computations: while disabled, evaluation jobs (exports) stay queued.");
    application.def("engine_computations_status", [] { return !JobEngine::Get().Paused(); },
                    "Whether the engine computations are enabled.");
    py::exec(kEngineContext, application.attr("__dict__"));

    py::module_ event = submodule(m, "event", "uzpainter.event",
                                  "The Python dispatcher thread: events and callbacks after committed transitions.");
    event.def(
        "post", [](py::object task) { return Dispatcher::Get().Post(std::move(task)); }, py::arg("task"),
        "Queues the callable `task` on the dispatcher thread; returns its sequence number.");
    event.def(
        "flush",
        [] {
            Dispatcher& dispatcher = Dispatcher::Get();
            const std::uint64_t seq = dispatcher.LastPosted();
            if (dispatcher.OnDispatcherThread()) {
                dispatcher.RunInline(seq);
                return;
            }
            py::gil_scoped_release release;
            dispatcher.WaitThrough(seq);
        },
        "Returns once every task queued before the call has run (inline on the dispatcher thread).");
    event.def(
        "drain",
        [] {
            Dispatcher& dispatcher = Dispatcher::Get();
            if (dispatcher.OnDispatcherThread()) throw ApiError("RuntimeError", "drain() on the dispatcher thread");
            py::gil_scoped_release release;
            dispatcher.Drain();
        },
        "Returns once the queue is empty and no asynchronous operation holds the dispatcher.");
    event.def("hold", [] { Dispatcher::Get().Hold(); }, "An asynchronous operation will post later.");
    event.def("release", [] { Dispatcher::Get().Release(); }, "The operation of a `hold()` has posted its last task.");
    event.def("on_dispatcher_thread", [] { return Dispatcher::Get().OnDispatcherThread(); });
    event.def("dispatcher_thread_id", [] { return Dispatcher::Get().ThreadIdent(); },
              "`threading.get_ident()` of the dispatcher thread (0 before its first task).");

    py::module_ properties = submodule(m, "properties", "uzpainter.properties", "Parameters (the bake parameters' keys).");
    py::module_ baking = submodule(m, "baking", "uzpainter.baking", "Mesh-map baking: the bake parameters.");
    BindBaking(baking, properties);
    Gaps(baking, "uzpainter.baking",
         {"bake_async", "bake_selected_textures_async", "set_linked_group",
          "set_linked_group_common_parameters", "unlink_all", "unlink_all_common_parameters", "get_link_group",
          "get_link_group_common_parameters", "get_linked_texture_sets", "get_linked_texture_sets_common_parameters"},
         "phase3.5_embree-bakers");

    py::module_ render = submodule(m, "render", "uzpainter.render", "Renders and captures (phase2.3_realtime-preview).");
    py::module_ shader = submodule(render, "shader", "uzpainter.render.shader",
                                   "Shader parameters: the default open-pbr instance (decision 042).");
    py::module_ render_display = submodule(render, "display", "uzpainter.render.display",
                                           "The fixed pipeline's display values and presets (decisions 038, 042).");
    py::module_ display = submodule(m, "display", "uzpainter.display", "Viewport display state: environment, camera.");
    BindDisplay(display, render_display, shader);
    BindCapture(render);

    py::module_ diagnostics = submodule(m, "diagnostics", "uzpainter.diagnostics",
                                        "Diagnostic views of the stack and layer-tree snapshots (bind_diagnostics.cpp).");
    BindDiagnostics(diagnostics);

    BindCapabilities(m);
}

}  // namespace uzp::python
