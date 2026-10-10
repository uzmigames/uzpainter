#pragma once

// The project manifest: the canonical JSON document of a project revision and the public schema
// of the `.uzp` file (`docs/architecture/09-project-file-format.md` §1, §5;
// `src/uzp_core/schema/manifest.schema.json`; key reference in `src/uzp_core/MANIFEST.md`).

#include <string>
#include <string_view>

#include "uzp_core/manifest/json.h"
#include "uzp_core/types/project.h"

namespace uzp::core {

/// The manifest object of `project`, unknown keys included (no validation).
json::Value ProjectToJson(const Project& project);

/// Reads a manifest object. Throws `ManifestError` on a missing or mistyped key, an unknown
/// enum member, a wrong `schema` or a `format_version` of a newer major; unknown keys are kept
/// in the `extra` members. Does not validate the model (see `LoadManifest`).
Project ProjectFromJson(const json::Value& manifest);

/// Validates `project` (`ValueError`) and returns its canonical manifest text.
std::string SaveManifest(const Project& project);

/// Parses (`json::ParseError`), reads (`ManifestError`) and validates (`ValueError`) a manifest.
Project LoadManifest(std::string_view text);

/// SHA-256 of the canonical manifest of `project` (validated first).
std::string ManifestDigest(const Project& project);

}  // namespace uzp::core
