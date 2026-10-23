// `uzp-pyapi-tests.exe <script.py> [args...] [--gpu-backend dx12|vulkan]`: the script host of
// UzPainter.exe's `run` command (src/python/run.h, phase1.22_pyapi-cli-capabilities) without the
// rest of UzPainter.exe, for the native Python API and facade tests. It runs one script in the
// embedded CPython 3.13 with `uzpainter` and `substance_painter` importable and prints the report
// of `uzp::python::RunScript` as one `UZP_JSON:` line; exit status 0 when the script ran to its end,
// 1 when it failed, 2 for a usage error, 3 when the interpreter did not start. Installed beside the
// vendored interpreter and `assets/` (tests/python/conftest.py).
//
// Test hook `uzp_job_test` (this runner only, never UzPainter.exe): `hold(end="return")` starts a
// job and returns its id once its body runs, held at a barrier until `release()`; released, the
// body returns `{busy}`, what `JobEngine::Busy` answers on the job's own thread (`end="return"`),
// throws `RuntimeError` (`"throw"`) or stops at a checkpoint, so a cancel asked while it was held
// cancels it (`"checkpoint"`). A test can so call the API while another job is executing, or after
// one ended either way, without relying on timing.

#include "python/jobs.h"
#include "python/run.h"
#include "python/session.h"

#include <pybind11/embed.h>
#include <pybind11/stl.h>

#include <condition_variable>
#include <cstdio>
#include <cstdlib>
#include <mutex>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>
#include "../no_error_dialogs.h"

namespace {

std::mutex hold_mutex;
std::condition_variable hold_changed;
bool hold_running = false;
bool hold_released = false;

}  // namespace

PYBIND11_EMBEDDED_MODULE(uzp_job_test, m) {
    m.def("admission_limits", [](std::optional<std::uint64_t> bytes, std::uint64_t tiles) {
        uzp::python::Session::Get().SetAdmissionLimits(
            bytes ? std::optional(uzp::evaluator::AdmissionLimits{*bytes, tiles}) : std::nullopt);
    });
    m.def(
        "hold",
        [](const std::string& end) {
            if (end != "return" && end != "throw" && end != "checkpoint") throw pybind11::value_error("end: " + end);
            {
                std::lock_guard lock(hold_mutex);
                hold_running = false;
                hold_released = false;
            }
            const auto job = uzp::python::JobEngine::Get().Start("test_hold", [end](uzp::python::JobContext& context) {
                {
                    std::unique_lock lock(hold_mutex);
                    hold_running = true;
                    hold_changed.notify_all();
                    hold_changed.wait(lock, [] { return hold_released; });
                }
                if (end == "throw") throw std::runtime_error("the held job failed");
                if (end == "checkpoint") context.Checkpoint();
                const std::optional<std::string> busy = uzp::python::JobEngine::Get().Busy();
                namespace json = uzp::core::json;
                return json::Object{{"busy", busy ? json::Value(*busy) : json::Value(nullptr)}};
            });
            pybind11::gil_scoped_release release;
            std::unique_lock lock(hold_mutex);
            hold_changed.wait(lock, [] { return hold_running; });
            return job->id();
        },
        pybind11::arg("end") = "return");
    m.def("cancel_queued", [](const std::string& id) {
        for (const auto& job : uzp::python::JobEngine::Get().List()) {
            if (job->id() == id) return job->CancelQueued();
        }
        throw pybind11::value_error("unknown job");
    });
    m.def("release", [] {
        std::lock_guard lock(hold_mutex);
        hold_released = true;
        hold_changed.notify_all();
    });
}

int main(int argc, char** argv) {
    std::vector<std::string> args{"run"};
    args.insert(args.end(), argv + (argc > 0 ? 1 : 0), argv + argc);
    const int status = uzp::python::RunRunCommand(args, stdout, stderr);
    // The interpreter is not finalized: its worker thread may still wait for jobs.
    std::fflush(stdout);
    std::fflush(stderr);
    std::_Exit(status);
}
