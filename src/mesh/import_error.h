#pragma once

// Errors of mesh import (`docs/architecture/12-mesh-import.md` §2, §3, §6, §8). Every refusal
// names its cause; nothing is created when an import fails.

#include <stdexcept>
#include <string>
#include <string_view>

#include "uzp_core/manifest/json.h"

namespace uzp::mesh {

enum class ImportErrorKind {
    parse_error,               ///< the file is not valid in its format
    unsupported_format,        ///< not a mesh format Painter imports
    release_gap,               ///< a format Painter imports that UzPainter v1 does not (dae, ply, usd)
    not_yet_supported,         ///< `AutoUnwrapSettings` (12 §8)
    duplicate_material_names,  ///< two materials share a name (PRJ-02)
    uv_outside_0_1,            ///< UVs outside tile 1001 in the Default workflow (12 §6)
};

/// The error class name the bindings raise for `kind`: `MeshParseError`, `UnsupportedFormat`,
/// `ReleaseGap`, `NotYetSupported`, `DuplicateMaterialNames`, `UVOutsideTile`.
std::string_view ErrorClassName(ImportErrorKind kind);

class ImportError : public std::runtime_error {
public:
    ImportError(ImportErrorKind kind, const std::string& message, core::json::Object details = {})
        : std::runtime_error(message), kind_(kind), details_(std::move(details)) {}

    ImportErrorKind kind() const { return kind_; }
    /// Structured facts of the refusal, e.g. `{"tiles": [1002]}` or `{"duplicates": {...}}`.
    const core::json::Object& details() const { return details_; }

private:
    ImportErrorKind kind_;
    core::json::Object details_;
};

}  // namespace uzp::mesh
