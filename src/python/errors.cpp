// The error classes of `uzpainter.exception` and the C++ error translation (errors.h).

#include "python/errors.h"

#include <cmath>
#include <string_view>

#include "mesh/import_error.h"
#include "store/container.h"
#include "uzp_core/naming/naming.h"
#include "uzp_core/types/errors.h"

namespace py = pybind11;

namespace uzp::python {

namespace {

/// The class definitions, executed in the namespace of `uzpainter.exception`.
constexpr const char* kClasses = R"PY(
class ProjectError(Exception):
    """An operation is incompatible with the current project, or no project is open."""


class ServiceNotFoundError(Exception):
    """A service the operation relies on is not available."""


class ResourceNotFoundError(Exception):
    """A resource could not be found (an unknown resource id or hash)."""


class EditionContextException(Exception):
    """The channel argument is not valid in the node's context (a multichannel node given None)."""


class UnsupportedInUzPainter(Exception):
    """A desktop-only Painter symbol: it changes no texture, render or script-visible state."""

    def __init__(self, symbol, reason="", alternative=""):
        super().__init__(f"{symbol} is not supported in UzPainter: {reason}"
                         + (f" (use {alternative})" if alternative else ""))
        self.symbol = symbol
        self.reason = reason
        self.alternative = alternative


class NotYetSupported(Exception):
    """A release gap: refused before any mutation; the message names the owner task."""


class UnsupportedProcedural(NotYetSupported):
    """Procedural content this build does not evaluate."""


class BusyError(RuntimeError):
    """A job is running; the operation would interfere with it."""

    def __init__(self, job_id, message=None):
        super().__init__(message or f"busy: job {job_id} is running")
        self.job_id = job_id


class StaleRevisionError(RuntimeError):
    """The call was based on a revision that is no longer current."""

    def __init__(self, expected, current):
        super().__init__(f"stale revision: the call expected revision {expected}, the project is at {current}")
        self.expected = expected
        self.current = current


class AmbiguousNameError(ValueError):
    """A name matched more than one node of its scope; nothing was changed."""

    def __init__(self, message, candidates):
        super().__init__(message)
        self.candidates = list(candidates)


class MeshParseError(ProjectError):
    """The mesh file is not valid in its format."""

    def __init__(self, message, details=None):
        super().__init__(message)
        self.details = details or {}


class UnsupportedFormat(MeshParseError):
    """Not a mesh format Painter imports."""


class DuplicateMaterialNames(MeshParseError):
    """Two materials of the mesh share a name."""


class UVOutsideTile(MeshParseError):
    """UVs outside tile 1001 in the Default workflow."""


class ReleaseGap(NotYetSupported):
    """A mesh format Painter imports that UzPainter v1 does not."""

    def __init__(self, message, details=None):
        super().__init__(message)
        self.details = details or {}
)PY";

/// `uzpainter.exception`, referenced for the life of the process (never released: the module
/// outlives every static destructor that could run after the interpreter finalized).
PyObject* g_exception_module = nullptr;

py::object Class(const std::string& name) {
    if (name == "ValueError") return py::reinterpret_borrow<py::object>(PyExc_ValueError);
    if (name == "RuntimeError") return py::reinterpret_borrow<py::object>(PyExc_RuntimeError);
    if (name == "AttributeError") return py::reinterpret_borrow<py::object>(PyExc_AttributeError);
    if (name == "TypeError") return py::reinterpret_borrow<py::object>(PyExc_TypeError);
    return py::handle(g_exception_module).attr(name.c_str());
}

void Raise(const py::object& instance) { PyErr_SetObject(reinterpret_cast<PyObject*>(Py_TYPE(instance.ptr())), instance.ptr()); }

void RaiseApiError(const ApiError& error) {
    const std::string& cls = error.cls();
    py::object type = Class(cls);
    if (cls == "BusyError") {
        Raise(type(error.job_id, error.what()));
    } else if (cls == "StaleRevisionError") {
        Raise(type(error.expected, error.current));
    } else if (cls == "UnsupportedInUzPainter") {
        Raise(type(error.symbol, error.reason, error.alternative));
    } else if (cls == "MeshParseError" || cls == "UnsupportedFormat" || cls == "DuplicateMaterialNames" ||
               cls == "UVOutsideTile" || cls == "ReleaseGap") {
        Raise(type(error.what(), FromJson(error.details)));
    } else {
        Raise(type(error.what()));
    }
}

ApiError FromImportError(const mesh::ImportError& error) {
    std::string cls(mesh::ErrorClassName(error.kind()));
    ApiError api(cls, error.what());
    api.details = error.details();
    return api;
}

}  // namespace

void ThrowProjectError(const std::string& message) { throw ApiError("ProjectError", message); }
void ThrowNotYetSupported(const std::string& message) { throw ApiError("NotYetSupported", message); }
void ThrowEditionContext(const std::string& message) { throw ApiError("EditionContextException", message); }
void ThrowResourceNotFound(const std::string& message) { throw ApiError("ResourceNotFoundError", message); }

void ThrowBusy(const std::string& job_id, const std::string& message) {
    ApiError error("BusyError", message);
    error.job_id = job_id;
    throw error;
}

void ThrowStale(std::int64_t expected, std::int64_t current) {
    ApiError error("StaleRevisionError", "stale revision");
    error.expected = expected;
    error.current = current;
    throw error;
}

void RaiseFailed(const core::TransactionResult& result, const std::exception_ptr& error) {
    if (error) std::rethrow_exception(error);
    const std::string cls = result.error_type.empty() ? "RuntimeError" : result.error_type;
    throw ApiError(cls, result.error);
}

py::object ExceptionClass(const std::string& name) { return Class(name); }

void RegisterExceptions(py::module_& exception) {
    g_exception_module = exception.inc_ref().ptr();
    py::exec(kClasses, exception.attr("__dict__"));
    py::register_exception_translator([](std::exception_ptr pointer) {
        if (!pointer) return;
        try {
            std::rethrow_exception(pointer);
        } catch (const ApiError& error) {
            RaiseApiError(error);
        } catch (const core::AmbiguousNameError& error) {
            py::list candidates;
            for (const core::Id id : error.candidates()) candidates.append(py::int_(id));
            Raise(Class("AmbiguousNameError")(error.what(), candidates));
        } catch (const core::NotYetSupported& error) {
            Raise(Class("NotYetSupported")(error.what()));
        } catch (const core::ValueError& error) {
            PyErr_SetString(PyExc_ValueError, error.what());
        } catch (const core::ManifestError& error) {
            Raise(Class("ProjectError")(error.what()));
        } catch (const mesh::ImportError& error) {
            RaiseApiError(FromImportError(error));
        } catch (const store::StoreError& error) {
            const std::string message = "project store: " + std::string(store::CodeName(error.code())) + ": " + error.what();
            Raise(Class(error.code() == store::StoreError::Code::missing_resource ? "ResourceNotFoundError" : "ProjectError")(
                message));
        }
    });
}

core::json::Value ToJson(const py::handle& value) {
    if (value.is_none()) return nullptr;
    if (py::isinstance<py::bool_>(value)) return value.cast<bool>();
    if (py::isinstance<py::int_>(value)) return value.cast<std::int64_t>();
    if (py::isinstance<py::float_>(value)) {
        const double number = value.cast<double>();
        if (!std::isfinite(number)) throw ApiError("RuntimeError", "a non-finite float cannot be stored");
        return number;
    }
    if (py::isinstance<py::str>(value)) return value.cast<std::string>();
    if (py::isinstance<py::list>(value) || py::isinstance<py::tuple>(value)) {
        core::json::Array array;
        for (const py::handle item : value) array.push_back(ToJson(item));
        return array;
    }
    if (py::isinstance<py::dict>(value)) {
        core::json::Object object;
        for (const auto& [key, item] : value.cast<py::dict>()) {
            if (!py::isinstance<py::str>(key)) throw ApiError("RuntimeError", "dictionary keys must be str");
            object[key.cast<std::string>()] = ToJson(item);
        }
        return object;
    }
    throw ApiError("RuntimeError",
                   "unsupported type " + py::str(py::type::of(value).attr("__name__")).cast<std::string>() +
                       " (supported: bool, int, float, str, list, dict with str keys, None)");
}

py::object FromJson(const core::json::Value& value) {
    return std::visit(
        [](const auto& v) -> py::object {
            using T = std::decay_t<decltype(v)>;
            if constexpr (std::is_same_v<T, std::nullptr_t>) {
                return py::none();
            } else if constexpr (std::is_same_v<T, bool>) {
                return py::bool_(v);
            } else if constexpr (std::is_same_v<T, std::int64_t>) {
                return py::int_(v);
            } else if constexpr (std::is_same_v<T, double>) {
                return py::float_(v);
            } else if constexpr (std::is_same_v<T, std::string>) {
                return py::str(v);
            } else if constexpr (std::is_same_v<T, core::json::Array>) {
                py::list list;
                for (const auto& item : v) list.append(FromJson(item));
                return std::move(list);
            } else {
                py::dict dict;
                for (const auto& [key, item] : v) dict[py::str(key)] = FromJson(item);
                return std::move(dict);
            }
        },
        value.data);
}

}  // namespace uzp::python
