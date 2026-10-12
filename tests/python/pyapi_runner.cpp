// `uzp-pyapi-tests.exe <script.py> [args...] [--gpu-backend dx12|vulkan]`: the script host of
// UzPainter.exe's `run` command (src/python/run.h, phase1.22_pyapi-cli-capabilities) without the
// rest of UzPainter.exe, for the native Python API and facade tests. It runs one script in the
// embedded CPython 3.13 with `uzpainter` and `substance_painter` importable and prints the report
// of `uzp::python::RunScript` as one `UZP_JSON:` line; exit status 0 when the script ran to its end,
// 1 when it failed, 2 for a usage error, 3 when the interpreter did not start. Installed beside the
// vendored interpreter and `assets/` (tests/python/conftest.py).

#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>

#include "python/run.h"

int main(int argc, char** argv) {
    std::vector<std::string> args{"run"};
    args.insert(args.end(), argv + (argc > 0 ? 1 : 0), argv + argc);
    const int status = uzp::python::RunRunCommand(args, stdout, stderr);
    // The interpreter is not finalized: its worker thread may still wait for jobs.
    std::fflush(stdout);
    std::fflush(stderr);
    std::_Exit(status);
}
