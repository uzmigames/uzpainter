#pragma once

// The embedded CPython 3.13 interpreter of UzPainter.exe (docs/architecture/10-python-api.md §1,
// 13-engine-integration.md §4.2 and §5).
//
// UzPainter.exe imports python313.dll of the vendored embeddable package (thirdparty/cpython/),
// installed beside it with python313.zip, the standard extension modules and Lib\site-packages\.
// The interpreter starts from PyConfig's isolated configuration, so environment variables
// (PYTHONPATH, PYTHONHOME, ...), the user site-packages and the registry are ignored, and its
// module search path comes from python313._pth beside the DLL (src/python/python313._pth). The
// built-in module `uzpainter` (uzpainter_module.cpp) is registered before the start.

#include <cstdint>
#include <string>
#include <vector>

namespace uzp::python {

/// The CPython release the vendored package pins (thirdparty/cpython/ORIGIN.md).
inline constexpr const char* kPinnedVersion = "3.13.16";

/// Starts the interpreter on the calling thread, which then holds the GIL. Returns an empty
/// string on success, otherwise why the start failed.
std::string Start();

/// Whether the interpreter is running.
bool IsRunning();

/// Finalizes the interpreter if it is running (on the thread that started it).
void Stop();

/// Every 16-bit value 0…65535 in order: the buffer `uzpainter._selftest.ramp16()` exposes.
const std::vector<uint16_t>& Ramp16();

}  // namespace uzp::python
