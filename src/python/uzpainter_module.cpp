// The `uzpainter` Python module (docs/architecture/10-python-api.md §1), compiled into
// UzPainter.exe and registered as a built-in module: PYBIND11_EMBEDDED_MODULE adds it to
// CPython's inittab when the executable starts, before the interpreter does, so
// `import uzpainter` never searches sys.path.
//
// Phase 0 holds only `uzpainter._selftest`, the boundary checks the CPython stages of `selftest`
// call (src/selftest/cpython_stages.cpp); the API modules come with phase1.24_python-api-facade.

#include "python/interpreter.h"

#include <pybind11/embed.h>

#include <stdexcept>
#include <string>

namespace py = pybind11;

namespace {

/// A UzPainter C++ exception type with its own Python exception class
/// (`uzpainter._selftest.BoundaryError`), registered through pybind11.
class BoundaryError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

/// Number of values of a 1-D buffer of unsigned 16-bit integers that differ from `Ramp16()`;
/// a buffer of another shape or format raises ValueError.
size_t CountRampMismatches(const py::buffer& buffer) {
    const py::buffer_info info = buffer.request();
    const auto& ramp = uzp::python::Ramp16();
    if (info.ndim != 1 || info.itemsize != sizeof(uint16_t) ||
        info.format != py::format_descriptor<uint16_t>::format() ||
        static_cast<size_t>(info.shape[0]) != ramp.size() || info.strides[0] != 2) {
        throw std::invalid_argument("expected a contiguous 1-D buffer of 65536 unsigned 16-bit "
                                    "values (format 'H'), got format '" +
                                    info.format + "', ndim " + std::to_string(info.ndim));
    }
    const auto* values = static_cast<const uint16_t*>(info.ptr);
    size_t mismatches = 0;
    for (size_t i = 0; i < ramp.size(); ++i) mismatches += values[i] != ramp[i];
    return mismatches;
}

[[noreturn]] void ThrowCpp(const std::string& kind, const std::string& message) {
    if (kind == "invalid_argument") throw std::invalid_argument(message);
    if (kind == "out_of_range") throw std::out_of_range(message);
    if (kind == "runtime_error") throw std::runtime_error(message);
    if (kind == "boundary_error") throw BoundaryError(message);
    throw std::invalid_argument("unknown exception kind: " + kind);
}

}  // namespace

PYBIND11_EMBEDDED_MODULE(uzpainter, m) {
    m.doc() = "UzPainter's native Python API (compiled into UzPainter.exe).";

    py::module_ selftest = m.def_submodule(
        "_selftest", "Boundary checks of `UzPainter.exe selftest` (not a public API).");
    selftest.def(
        "ramp16",
        [] {
            const auto& ramp = uzp::python::Ramp16();
            return py::memoryview::from_buffer(ramp.data(), {static_cast<py::ssize_t>(ramp.size())},
                                               {static_cast<py::ssize_t>(sizeof(uint16_t))});
        },
        "A read-only memoryview (format 'H') of the C++ buffer holding 0..65535.");
    selftest.def("count_ramp16_mismatches", &CountRampMismatches, py::arg("buffer"),
                 "Values of a 65536-element 'H' buffer that differ from ramp16().");
    py::register_exception<BoundaryError>(selftest, "BoundaryError");
    selftest.def("throw_cpp", &ThrowCpp, py::arg("kind"), py::arg("message"),
                 "Throw the C++ exception `kind` (invalid_argument, out_of_range, runtime_error, "
                 "boundary_error) with `message`.");
}
