// The CPython stages of `selftest` (cpython_stages.h).
//
// The checks that are naturally Python run as short scripts in the embedded interpreter: each
// fills a `facts` dict (recorded as the stage's details) and a `problems` list (the stage fails
// with them). The C++ side of the boundary (buffer comparison, exceptions caught in C++) is
// checked here directly.

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include "cpython_stages.h"

#include "python/interpreter.h"

#include <pybind11/embed.h>

#include <windows.h>

#include <filesystem>
#include <string>
#include <utility>
#include <vector>

namespace py = pybind11;

namespace uzp::selftest {

namespace {

constexpr const char* kStart = "cpython-start";

std::string Utf8(const std::wstring& wide) {
    if (wide.empty()) return {};
    const int size = WideCharToMultiByte(CP_UTF8, 0, wide.data(), static_cast<int>(wide.size()),
                                         nullptr, 0, nullptr, nullptr);
    std::string out(static_cast<size_t>(size), '\0');
    WideCharToMultiByte(CP_UTF8, 0, wide.data(), static_cast<int>(wide.size()), out.data(), size,
                        nullptr, nullptr);
    return out;
}

/// "<type name>: <message>" of a Python exception; for an exception group, followed by its
/// sub-exceptions (recursively) in brackets.
std::string DescribeException(const py::handle& value) {
    std::string text = py::str(py::type::handle_of(value).attr("__name__"));
    text += ": " + std::string(py::str(value));
    if (py::hasattr(value, "exceptions")) {
        std::string inner;
        for (const py::handle sub : value.attr("exceptions")) {
            inner += (inner.empty() ? "" : "; ") + DescribeException(sub);
        }
        text += " [" + inner + "]";
    }
    return text;
}

std::string Describe(const py::error_already_set& error) {
    try {
        return DescribeException(error.value());
    } catch (const std::exception&) {
        return error.what();
    }
}

/// Runs `code` in `globals` with `exe_dir` (the executable's folder), `facts` (dict) and
/// `problems` (list) added; copies `facts` into `details` and returns `problems`.
std::vector<std::string> RunScript(const SelftestContext& context, const std::string& code,
                                   Details& details, py::dict& globals) {
    globals["__builtins__"] = py::module_::import("builtins");
    globals["__name__"] = "__uzpainter_selftest__";
    globals["exe_dir"] = Utf8(context.exeDir.wstring());
    globals["facts"] = py::dict();
    globals["problems"] = py::list();
    std::vector<std::string> problems;
    try {
        py::exec(code, globals);
    } catch (const py::error_already_set& error) {
        problems.push_back("Python raised " + Describe(error));
    }
    for (const auto& item : py::dict(globals["facts"])) {
        details.emplace_back(py::str(item.first), py::str(item.second));
    }
    for (const auto& problem : py::list(globals["problems"])) problems.push_back(py::str(problem));
    return problems;
}

std::vector<std::string> RunScript(const SelftestContext& context, const std::string& code,
                                   Details& details) {
    py::dict globals;
    return RunScript(context, code, details, globals);
}

StageOutcome Outcome(std::vector<std::string> problems, Details details) {
    if (problems.empty()) return StageOutcome::Pass(std::move(details));
    std::string reason = problems.front();
    if (problems.size() > 1) reason += " (and " + std::to_string(problems.size() - 1) + " more)";
    for (size_t i = 0; i < problems.size(); ++i) {
        details.emplace_back("problem_" + std::to_string(i + 1), std::move(problems[i]));
    }
    return StageOutcome::Fail(std::move(reason), std::move(details));
}

/// Shared helpers of the scripts: path normalisation and containment in the install folder.
constexpr const char* kPrelude = R"PY(
import os, sys

def norm(path):
    return os.path.normcase(os.path.abspath(path))

def inside(path, folder):
    path = norm(path)
    return path == folder or path.startswith(folder + os.sep)

root = norm(exe_dir)
stdlib_zip = os.path.join(root, 'python313.zip')
site_packages = os.path.join(root, os.path.normcase('Lib'), 'site-packages')
# UzPainter's own pure-Python packages (the substance_painter facade), installed with the app.
facade = os.path.join(root, 'python')
)PY";

std::string WithPrelude(const char* body) { return std::string(kPrelude) + body; }

constexpr const char* kStartScript = R"PY(
import site

facts['version'] = sys.version
facts['version_info'] = '.'.join(map(str, sys.version_info[:3]))
facts['prefix'] = sys.prefix
facts['sys_path'] = ' ; '.join(sys.path)
for flag in ('isolated', 'ignore_environment', 'no_user_site', 'safe_path', 'dont_write_bytecode'):
    facts['flag_' + flag] = str(getattr(sys.flags, flag))
    if not getattr(sys.flags, flag):
        problems.append(f'sys.flags.{flag} is not set')
facts['user_site_enabled'] = str(site.ENABLE_USER_SITE)
if site.ENABLE_USER_SITE:
    problems.append('the user site-packages is enabled')
if norm(sys.prefix) != root:
    problems.append(f'sys.prefix is {sys.prefix}, not the install folder')
for entry in sys.path:
    if norm(entry) not in (stdlib_zip, root, facade) and not inside(entry, site_packages):
        problems.append(f'sys.path entry outside the installed interpreter: {entry}')
for required in (stdlib_zip, root, site_packages, facade):
    if required not in [norm(entry) for entry in sys.path]:
        problems.append(f'{required} is not on sys.path')
for name, module in sorted(sys.modules.items()):
    path = getattr(module, '__file__', None)
    if path and not inside(path, root):
        problems.append(f'module {name} loaded from outside the install folder: {path}')
)PY";

constexpr const char* kUzpainterScript = R"PY(
import importlib.util
import uzpainter

facts['builtin'] = str('uzpainter' in sys.builtin_module_names)
facts['origin'] = str(importlib.util.find_spec('uzpainter').origin)
facts['doc'] = str(uzpainter.__doc__)
facts['selftest_functions'] = ', '.join(
    sorted(n for n in dir(uzpainter._selftest) if not n.startswith('__')))
if 'uzpainter' not in sys.builtin_module_names:
    problems.append('uzpainter is not a built-in module')
if hasattr(uzpainter, '__file__'):
    problems.append(f'uzpainter was loaded from a file: {uzpainter.__file__}')
)PY";

constexpr const char* kBufferScript = R"PY(
import array
import uzpainter

boundary = uzpainter._selftest
view = boundary.ramp16()  # C++ memory, exported through the buffer protocol
facts['cpp_buffer_format'] = view.format
facts['cpp_buffer_itemsize'] = str(view.itemsize)
facts['cpp_buffer_length'] = str(len(view))
facts['cpp_buffer_readonly'] = str(view.readonly)
if (view.format, view.itemsize, view.ndim, len(view)) != ('H', 2, 1, 65536):
    problems.append(f'ramp16() exports format {view.format!r}, itemsize {view.itemsize}, '
                    f'ndim {view.ndim}, length {len(view)}')
result = array.array('H')
# A Python-owned copy of the raw bytes, read through the buffer protocol (frombytes takes a
# byte buffer, so the 'H' view is reinterpreted as unsigned bytes without copying).
result.frombytes(view.cast('B'))
python_mismatches = sum(1 for i, value in enumerate(result) if value != i)
facts['python_values'] = str(len(result))
facts['python_mismatches'] = str(python_mismatches)
if len(result) != 65536 or python_mismatches:
    problems.append(f'Python read {len(result)} values, {python_mismatches} differ from 0..65535')
bound_mismatches = boundary.count_ramp16_mismatches(result)  # back to C++ through a bound call
facts['bound_function_mismatches'] = str(bound_mismatches)
if bound_mismatches:
    problems.append(f'the bound function found {bound_mismatches} differing values')
)PY";

constexpr const char* kExceptionScript = R"PY(
import uzpainter

boundary = uzpainter._selftest
cases = [
    ('invalid_argument', ValueError),
    ('out_of_range', IndexError),
    ('runtime_error', RuntimeError),
    ('boundary_error', boundary.BoundaryError),
]
for kind, expected in cases:
    message = f'uzpainter selftest: C++ {kind} to Python'
    try:
        boundary.throw_cpp(kind, message)
    except Exception as error:
        facts['cpp_' + kind] = f'{type(error).__module__}.{type(error).__name__}: {error}'
        if type(error) is not expected:
            problems.append(f'C++ {kind} arrived as {type(error).__name__}, '
                            f'expected {expected.__name__}')
        elif str(error) != message:
            problems.append(f'C++ {kind} arrived with message {str(error)!r}')
    else:
        problems.append(f'C++ {kind} raised nothing in Python')
)PY";

constexpr const char* kMcpScript = R"PY(
import asyncio
import importlib.metadata

import mcp
from mcp import Client
from mcp.server.mcpserver import MCPServer
import pydantic, pydantic_core, rpds, _cffi_backend, pywintypes
from cryptography.hazmat.bindings import _rust

facts['mcp_version'] = importlib.metadata.version('mcp')
facts['mcp_file'] = mcp.__file__
if not inside(mcp.__file__, site_packages):
    problems.append(f'mcp was imported from {mcp.__file__}, not from Lib\\site-packages')
facts['pydantic_version'] = pydantic.VERSION
native = {
    'pydantic_core': pydantic_core._pydantic_core,
    'rpds': rpds.rpds,
    'cffi': _cffi_backend,
    'cryptography': _rust,
    'pywin32': pywintypes,
}
for wheel, module in native.items():
    path = module.__file__
    facts['native_' + wheel] = os.path.relpath(path, exe_dir)
    if not inside(path, site_packages) or not path.lower().endswith(('.pyd', '.dll')):
        problems.append(f'native module of {wheel} is not a binary in Lib\\site-packages: {path}')
facts['distributions'] = ', '.join(sorted(
    f"{d.metadata['Name']} {d.version}" for d in importlib.metadata.distributions()))

server = MCPServer('uzpainter-selftest', log_level='ERROR')

@server.tool()
def repeat(text: str, count: int) -> str:
    """Repeat a text."""
    return text * count

async def round_trip():
    async with Client(server) as client:
        listed = await client.list_tools()
        called = await client.call_tool('repeat', {'text': 'uz', 'count': 3})
        return [tool.name for tool in listed.tools], called

names, called = asyncio.run(round_trip())
facts['mcp_tools'] = ', '.join(names)
facts['mcp_call'] = repr(called.structured_content)
if names != ['repeat'] or called.is_error or called.structured_content != {'result': 'uzuzuz'}:
    problems.append(f'in-process MCP round trip returned tools {names} and {called!r}')
for name, module in sorted(sys.modules.items()):
    path = getattr(module, '__file__', None)
    if path and not inside(path, root):
        problems.append(f'module {name} loaded from outside the install folder: {path}')
)PY";

}  // namespace

StageOutcome RunCpythonStart(SelftestContext& context) {
    HMODULE dll = GetModuleHandleW(L"python313.dll");
    wchar_t dllPath[MAX_PATH] = {};
    if (dll) GetModuleFileNameW(dll, dllPath, MAX_PATH);
    Details details = {{"python313_dll", Utf8(dllPath)}};
    const std::filesystem::path expected = context.exeDir / L"python313.dll";
    std::error_code ec;
    if (!dll || !std::filesystem::equivalent(dllPath, expected, ec)) {
        return StageOutcome::Fail("python313.dll is not loaded from " + expected.string(),
                                  details);
    }
    const std::string startError = python::Start();
    if (!startError.empty()) {
        return StageOutcome::Fail("the interpreter did not start: " + startError, details);
    }
    std::vector<std::string> problems =
        RunScript(context, WithPrelude(kStartScript), details);
    for (const auto& [key, value] : details) {
        if (key == "version_info" && value != python::kPinnedVersion) {
            problems.push_back("CPython " + value + " runs, the vendored package pins " +
                               python::kPinnedVersion);
        }
    }
    return Outcome(std::move(problems), std::move(details));
}

StageOutcome RunCpythonUzpainter(SelftestContext& context) {
    Details details;
    return Outcome(RunScript(context, WithPrelude(kUzpainterScript), details),
                   std::move(details));
}

StageOutcome RunCpythonBuffer16(SelftestContext& context) {
    Details details;
    py::dict globals;
    std::vector<std::string> problems =
        RunScript(context, WithPrelude(kBufferScript), details, globals);
    if (!globals.contains("result")) return Outcome(std::move(problems), std::move(details));

    // The Python-owned copy back in C++ through the buffer protocol, compared byte for byte.
    const py::buffer_info info = py::buffer(globals["result"]).request();
    const auto& ramp = python::Ramp16();
    const size_t bytes = ramp.size() * sizeof(uint16_t);
    details.emplace_back("cpp_received_format", info.format);
    details.emplace_back("cpp_received_bytes", std::to_string(info.size * info.itemsize));
    if (info.ndim != 1 || info.itemsize != 2 || info.format != "H" ||
        static_cast<size_t>(info.size) != ramp.size()) {
        problems.push_back("the buffer returned to C++ has format '" + info.format +
                           "', itemsize " + std::to_string(info.itemsize) + ", " +
                           std::to_string(info.size) + " values");
    } else {
        const auto* got = static_cast<const unsigned char*>(info.ptr);
        const auto* want = reinterpret_cast<const unsigned char*>(ramp.data());
        size_t mismatches = 0;
        size_t first = bytes;
        for (size_t i = 0; i < bytes; ++i) {
            if (got[i] != want[i]) {
                ++mismatches;
                if (first == bytes) first = i;
            }
        }
        details.emplace_back("cpp_byte_mismatches", std::to_string(mismatches));
        if (mismatches) {
            problems.push_back(std::to_string(mismatches) + " of " + std::to_string(bytes) +
                               " bytes differ after the round trip, first at byte " +
                               std::to_string(first));
        }
    }
    return Outcome(std::move(problems), std::move(details));
}

StageOutcome RunCpythonExceptions(SelftestContext& context) {
    Details details;
    std::vector<std::string> problems;

    // Python -> C++: built-in and script-defined exception types, caught as error_already_set.
    struct PythonCase {
        const char* code;
        PyObject* base;
        const char* type;
        const char* message;
    };
    const PythonCase cases[] = {
        {"raise ValueError('uzpainter selftest: Python ValueError to C++')", PyExc_ValueError,
         "ValueError", "uzpainter selftest: Python ValueError to C++"},
        {"class ScriptError(RuntimeError):\n    pass\n"
         "raise ScriptError('uzpainter selftest: Python ScriptError to C++')",
         PyExc_RuntimeError, "ScriptError", "uzpainter selftest: Python ScriptError to C++"},
    };
    for (const PythonCase& c : cases) {
        py::dict globals;
        globals["__builtins__"] = py::module_::import("builtins");
        try {
            py::exec(c.code, globals);
            problems.push_back(std::string("Python ") + c.type + " did not reach C++");
        } catch (const py::error_already_set& error) {
            const std::string type = py::str(error.type().attr("__name__"));
            const std::string message = py::str(error.value());
            details.emplace_back(std::string("python_") + c.type, type + ": " + message);
            if (!error.matches(c.base) || type != c.type) {
                problems.push_back(std::string("Python ") + c.type + " arrived in C++ as " + type);
            } else if (message != c.message) {
                problems.push_back(std::string("Python ") + c.type +
                                   " arrived in C++ with message '" + message + "'");
            }
        }
        if (PyErr_Occurred()) {
            PyErr_Clear();
            problems.push_back("the Python error indicator stayed set after the catch in C++");
        }
    }

    // C++ -> Python: exceptions thrown by bound functions, caught in Python.
    for (std::string& problem :
         RunScript(context, WithPrelude(kExceptionScript), details)) {
        problems.push_back(std::move(problem));
    }

    // The interpreter stays usable: evaluate an expression and call into `uzpainter` again.
    try {
        const int sum = py::eval("sum(range(10))").cast<int>();
        const size_t mismatches = py::module_::import("uzpainter")
                                      .attr("_selftest")
                                      .attr("count_ramp16_mismatches")(
                                          py::module_::import("uzpainter")
                                              .attr("_selftest")
                                              .attr("ramp16")())
                                      .cast<size_t>();
        details.emplace_back("usable_after", "sum(range(10)) = " + std::to_string(sum) +
                                                 ", ramp16 mismatches " +
                                                 std::to_string(mismatches));
        if (sum != 45 || mismatches != 0) problems.push_back("the interpreter misbehaves afterwards");
    } catch (const py::error_already_set& error) {
        problems.push_back("the interpreter is not usable afterwards: " + Describe(error));
    }
    return Outcome(std::move(problems), std::move(details));
}

StageOutcome RunCpythonMcpSdk(SelftestContext& context) {
    Details details;
    return Outcome(RunScript(context, WithPrelude(kMcpScript), details),
                   std::move(details));
}

void RegisterCpythonStages(Selftest& selftest) {
    selftest.Add({kStart, true, false, false, {}, RunCpythonStart});
    selftest.Add({"cpython-uzpainter", true, false, false, {kStart}, RunCpythonUzpainter});
    selftest.Add({"cpython-buffer16", true, false, false, {kStart}, RunCpythonBuffer16});
    selftest.Add({"cpython-exceptions", true, false, false, {kStart}, RunCpythonExceptions});
    selftest.Add({"cpython-mcp-sdk", true, false, false, {kStart}, RunCpythonMcpSdk});
}

void TeardownCpython() { python::Stop(); }

}  // namespace uzp::selftest
