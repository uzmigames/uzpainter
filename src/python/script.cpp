// Running one script file in the embedded interpreter (script.h).

#include "python/script.h"

#include <fstream>
#include <iterator>

#include <pybind11/embed.h>
#include <pybind11/stl.h>

#include "python/dispatcher.h"
#include "python/errors.h"
#include "python/session.h"

namespace py = pybind11;

namespace uzp::python {

namespace {

constexpr const char* kRunner = R"PY(
import io, sys, traceback

_capture = {}


def run(path, argv, source):
    """Runs the script with its output captured; the capture stays on until finish()."""
    out, err = io.StringIO(), io.StringIO()
    _capture.update(saved=(sys.stdout, sys.stderr, sys.argv), out=out, err=err)
    sys.stdout, sys.stderr, sys.argv = out, err, [path, *argv]
    namespace = {"__name__": "__main__", "__file__": path, "__builtins__": __builtins__}
    error = None
    try:
        exec(compile(source, path, "exec"), namespace)
    except BaseException as exc:
        error = {"type": type(exc).__name__, "message": str(exc),
                 "traceback": "".join(traceback.format_exception(exc))}
    return namespace.get("result"), error


def finish():
    """Restores the process's streams; the script's captured output."""
    sys.stdout, sys.stderr, sys.argv = _capture["saved"]
    return _capture["out"].getvalue(), _capture["err"].getvalue()
)PY";

core::json::Object ResultJson(const CallResult& result) {
    core::json::Object o = result.changes.ToJson();
    o["status"] = result.status;
    o["revision"] = result.revision;
    o["returned"] = result.returned;
    return o;
}

}  // namespace

core::json::Object RunScript(const std::filesystem::path& script, const std::vector<std::string>& args) {
    const std::u8string u8 = script.generic_u8string();
    const std::string path(u8.begin(), u8.end());
    std::ifstream file(script, std::ios::binary);
    if (!file) {
        return {{"status", "failed"},
                {"error", core::json::Object{{"type", "FileNotFoundError"}, {"message", "cannot read " + path}, {"traceback", ""}}}};
    }
    const std::string source{std::istreambuf_iterator<char>(file), std::istreambuf_iterator<char>()};

    py::dict scope;
    py::exec(kRunner, scope);
    Session& session = Session::Get();
    session.BeginScriptLog();
    py::tuple outcome = scope["run"](path, args, py::bytes(source)).cast<py::tuple>();
    {
        // Events and callbacks of operations the script started are delivered after it returned
        // (10-python-api.md §4): their output and commits belong to the run.
        py::gil_scoped_release release;
        Dispatcher::Get().Drain();
    }
    const py::tuple output = scope["finish"]().cast<py::tuple>();
    if (session.TransactionOpen()) session.RollbackTransaction();
    const ScriptLog log = session.EndScriptLog();

    core::json::Object report{{"stdout", output[0].cast<std::string>()}, {"stderr", output[1].cast<std::string>()}};
    core::json::Array committed;
    for (const CallResult& result : log.committed) committed.push_back(ResultJson(result));
    report["committed"] = std::move(committed);
    report["last_committed_revision"] =
        log.last_committed_revision ? core::json::Value(*log.last_committed_revision) : core::json::Value(nullptr);
    if (!outcome[1].is_none()) {
        report["status"] = "failed";
        report["error"] = ToJson(outcome[1]);
        report["result"] = nullptr;
        return report;
    }
    report["status"] = "ok";
    try {
        report["result"] = ToJson(outcome[0]);
    } catch (const ApiError& error) {
        report["status"] = "failed";
        report["result"] = nullptr;
        report["error"] = core::json::Object{
            {"type", "TypeError"}, {"message", std::string("result is not JSON: ") + error.what()}, {"traceback", ""}};
    }
    return report;
}

}  // namespace uzp::python
