#pragma once

// The error classes of the `uzpainter` module (docs/architecture/10-python-api.md §5,
// `uzpainter.exception`) and the translation of every C++ error the API meets into one of them.
//
// Painter-documented classes: `ProjectError`, `ServiceNotFoundError`, `ResourceNotFoundError`,
// `EditionContextException` (raised where Painter raises them), with Python's own `ValueError` and
// `RuntimeError`. UzPainter additions: `UnsupportedInUzPainter(symbol, reason, alternative)`,
// `NotYetSupported` (a release gap, raised before any mutation, decision 082),
// `UnsupportedProcedural` (a `NotYetSupported` for procedural content), `BusyError(job_id)`,
// `StaleRevisionError(expected, current)` and `AmbiguousNameError(name, candidates)` (a
// `ValueError` listing every matching node id, LAY-06). Mesh import refusals keep the class names
// of `mesh::ErrorClassName`: `MeshParseError`, `UnsupportedFormat`, `DuplicateMaterialNames` and
// `UVOutsideTile` are `ProjectError`s, `ReleaseGap` a `NotYetSupported`; each carries `details`.
//
// No failure returns an empty success: every refused or failed call raises one of these.

#include <cstdint>
#include <exception>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

#include <pybind11/eval.h>
#include <pybind11/pybind11.h>

#include "uzp_core/manifest/json.h"
#include "uzp_core/transaction/transaction.h"
#include "uzp_core/types/ids.h"

namespace uzp::python {

/// A failure the API raises as the `uzpainter.exception` class (or builtin) `cls`.
class ApiError : public std::runtime_error {
public:
    ApiError(std::string cls, const std::string& message) : std::runtime_error(message), cls_(std::move(cls)) {}

    const std::string& cls() const { return cls_; }

    /// `BusyError`: the running job.
    std::string job_id;
    /// `StaleRevisionError`: the revision the call was based on and the current one.
    std::int64_t expected = 0;
    std::int64_t current = 0;
    /// `UnsupportedInUzPainter`.
    std::string symbol, reason, alternative;
    /// `ProjectError` subclasses of mesh import: the refusal's structured facts.
    core::json::Object details;

private:
    std::string cls_;
};

[[noreturn]] void ThrowProjectError(const std::string& message);
[[noreturn]] void ThrowNotYetSupported(const std::string& message);
[[noreturn]] void ThrowEditionContext(const std::string& message);
[[noreturn]] void ThrowBusy(const std::string& job_id, const std::string& message);
[[noreturn]] void ThrowStale(std::int64_t expected, std::int64_t current);
[[noreturn]] void ThrowResourceNotFound(const std::string& message);

/// Raises the error of a failed transaction result: `error`, when the call stored the typed
/// exception that failed it, otherwise the class `result.error_type` names.
[[noreturn]] void RaiseFailed(const core::TransactionResult& result, const std::exception_ptr& error);

/// Defines the classes in `exception` (the `uzpainter.exception` module) and registers the
/// translator of every C++ error type the API lets through.
void RegisterExceptions(pybind11::module_& exception);
/// The class `name` of `uzpainter.exception` (or the builtin `ValueError`, `RuntimeError`, ...).
pybind11::object ExceptionClass(const std::string& name);

/// The canonical JSON of a Python value made of None, bool, int, float, str, list/tuple and dict
/// with str keys (`RuntimeError` for any other type, as Painter's `Metadata.set`).
core::json::Value ToJson(const pybind11::handle& value);
/// The Python value of a JSON value (dict, list, str, int, float, bool, None).
pybind11::object FromJson(const core::json::Value& value);

}  // namespace uzp::python
