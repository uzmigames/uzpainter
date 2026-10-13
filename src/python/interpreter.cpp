// Start and stop of the embedded CPython 3.13 interpreter (interpreter.h).

#include "python/interpreter.h"

#include <pybind11/embed.h>

#include "prof_scratch.h"

#include <exception>

namespace uzp::python {

std::string Start() {
    if (Py_IsInitialized()) return "the interpreter is already running";
    UZP_PROF("python.start");
    PyConfig config;
    // Isolated: no environment variables, no user site-packages, no current directory on the
    // path, no signal handlers. python313._pth beside the DLL then sets the module search path.
    PyConfig_InitIsolatedConfig(&config);
    // The install folder is read-only (13-engine-integration.md §5): no __pycache__ in it.
    config.write_bytecode = 0;
    try {
        // Clears `config` in every case; no program folder is added to sys.path.
        pybind11::initialize_interpreter(&config, 0, nullptr, false);
    } catch (const std::exception& error) {
        return error.what();
    }
    return {};
}

bool IsRunning() { return Py_IsInitialized() != 0; }

void Stop() {
    if (Py_IsInitialized()) pybind11::finalize_interpreter();
}

const std::vector<uint16_t>& Ramp16() {
    static const std::vector<uint16_t> ramp = [] {
        std::vector<uint16_t> values(65536);
        for (size_t i = 0; i < values.size(); ++i) values[i] = static_cast<uint16_t>(i);
        return values;
    }();
    return ramp;
}

}  // namespace uzp::python
