// `uzp-pyapi-tests.exe <script.py> [args...]`: runs one script in the embedded CPython 3.13 with
// the `uzpainter` module (src/python/), the way UzPainter.exe's `run` command will
// (phase1.22_pyapi-cli-capabilities), and prints the report of `uzp::python::RunScript` as one
// line of canonical JSON. Exit status 0 when the script ran to its end, 1 when it raised, 2 for a
// usage or interpreter error. Installed beside UzPainter.exe so the vendored interpreter and
// `assets/` are found (tests/python/conftest.py).

#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <string>
#include <vector>

#include <pybind11/embed.h>

#include "python/dispatcher.h"
#include "python/interpreter.h"
#include "python/script.h"
#include "python/session.h"
#include "uzp_core/manifest/json.h"

int main(int argc, char** argv) {
    if (argc < 2) {
        std::fprintf(stderr, "usage: uzp-pyapi-tests <script.py> [args...]\n");
        return 2;
    }
    const std::string error = uzp::python::Start();
    if (!error.empty()) {
        std::fprintf(stderr, "cannot start the interpreter: %s\n", error.c_str());
        return 2;
    }
    int status = 2;
    {
        pybind11::gil_scoped_acquire gil;
        const uzp::core::json::Object report =
            uzp::python::RunScript(uzp::python::PathFromUtf8(argv[1]), std::vector<std::string>(argv + 2, argv + argc));
        std::printf("%s\n", uzp::core::json::WriteCanonical(report).c_str());
        std::fflush(stdout);
        status = std::get<std::string>(report.at("status").data) == "ok" ? 0 : 1;
        // Events and callbacks of operations the script started are still delivered after it
        // returned (10-python-api.md §4): the process ends once the dispatcher has drained.
        pybind11::gil_scoped_release release;
        uzp::python::Dispatcher::Get().Drain();
    }
    // A project the script left open is closed (its lock released, an untitled folder removed)
    // unless a job still uses it; the process then ends without finalizing the interpreter, whose
    // worker thread may still be waiting for jobs.
    uzp::python::Session& session = uzp::python::Session::Get();
    try {
        if (session.IsOpen()) session.Close();
    } catch (const std::exception& error) {
        std::fprintf(stderr, "the project left open was not closed: %s\n", error.what());
    }
    std::_Exit(status);
}
