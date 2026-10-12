// The supervisor role (supervisor.h).

#include "supervisor/supervisor.h"

#include <exception>

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>

#include <pybind11/embed.h>
#include <pybind11/stl.h>

#include "python/interpreter.h"
#include "supervisor/ipc.h"
#include "supervisor/worker.h"

namespace uzp::supervisor {

namespace {

std::string ExecutablePath() {
    std::wstring buffer(32768, L'\0');
    const DWORD length = GetModuleFileNameW(nullptr, buffer.data(), static_cast<DWORD>(buffer.size()));
    buffer.resize(length);
    const int bytes = WideCharToMultiByte(CP_UTF8, 0, buffer.data(), static_cast<int>(buffer.size()), nullptr, 0, nullptr, nullptr);
    std::string utf8(static_cast<std::size_t>(bytes), '\0');
    WideCharToMultiByte(CP_UTF8, 0, buffer.data(), static_cast<int>(buffer.size()), utf8.data(), bytes, nullptr, nullptr);
    return utf8;
}

}  // namespace

bool IsSupervisorCommand(const std::string& first) { return first == "--mcp"; }

int RunSupervisorCommand(const std::vector<std::string>& args, std::FILE* err) {
    if (const std::string error = python::Start(); !error.empty()) {
        std::fprintf(err, "UzPainter.exe --mcp: cannot start the interpreter: %s\n", error.c_str());
        return kSupervisorExitHostError;
    }
    pybind11::gil_scoped_acquire gil;
    try {
        pybind11::object main = pybind11::module_::import("uzpainter_supervisor.main").attr("main");
        const std::vector<std::string> rest(args.begin() + 1, args.end());
        return main(rest, ExecutablePath(), BuildString(), std::string(kProtocol), FaultHooksCompiled()).cast<int>();
    } catch (const std::exception& error) {
        std::fprintf(err, "UzPainter.exe --mcp: %s\n", error.what());
        return kSupervisorExitHostError;
    }
}

}  // namespace uzp::supervisor
