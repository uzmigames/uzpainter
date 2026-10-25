#pragma once

// The Assets3D production guard (phase3.1_assets3d-cutover QG-02/M11, decision 360): the native
// side of a production paint round. Process-wide state, never reset by closing or reopening a
// project:
//
// - absent: the default; nothing here changes any behaviour (`UzPainter.exe run` without the flag,
//   the worker, the MCP server and every other verb).
// - required: `run --assets3d-production-required` set it before the interpreter starts. Every
//   import, restore and mutation refuses until a policy is installed.
// - armed: `_assets3d_install_production_policy(policy_json)` installed the one policy of the
//   process (it cannot be replaced or removed).
//
// Policy `uzpainter/assets3d-native-policy/1`: exactly `schema`, `source_sha256`, `source_size`,
// `import_report` (the complete canonical report of the admitted mesh import, certificate
// included), `request_sha256` and `pins` (`{path, sha256, size}` per file the preflight read:
// absolute paths, one of them the request). Every pin is re-hashed at every admission boundary,
// before anything is persisted. Comparisons use canonical JSON, which keeps scalar identities
// (int versus double, the sign of zero). Refusals raise `uzpainter.Assets3DProductionError`.

#include <filesystem>
#include <optional>
#include <string>

#include "mesh/mesh_import.h"
#include "uzp_core/manifest/json.h"
#include "uzp_core/types/project.h"

namespace uzp::python::assets3d {

enum class Mode { absent, required, armed };

/// `run --assets3d-production-required`: absent -> required, before the interpreter starts.
void Require();
Mode CurrentMode();
/// required -> armed with the validated policy; refused in any other mode or for a malformed policy.
void InstallPolicy(const std::string& policy_json);
/// `uzpainter/assets3d-production-status/1`: mode, policy_installed, request_sha256 and
/// source_sha256 (both null until armed).
core::json::Object Status();

/// A mesh import (create or reload) before anything is written: the guard must be armed, every
/// pin unchanged, the bytes the admitted source (SHA-256 and size), the complete report equal to
/// the policy's, and the certificate not `fail`. No effect when absent.
void CheckImport(const mesh::ImportResult& result);
/// A project before it becomes current or before a mutation, revert or rebuild is persisted: the
/// guard must be armed, every pin unchanged, and the project's mesh the admitted source with the
/// admitted report. No effect when absent.
void RequireAdmittedProject(const core::Project& project);
/// Opening `path`: a bundle directory is refused in production (its import writes a whole project
/// before any check). No effect when absent.
void CheckOpenPath(const std::filesystem::path& path);
/// Revert and discard restore a stored revision through the store directly, past every mutation
/// check; they are refused outright in production (required or armed). No effect when absent.
void RefuseRestore(const std::string& operation);
/// The mesh unit scale the project's current mesh import requested (its report's
/// `units.requested_mesh_unit_scale`): none when it requested none or the project has no mesh.
std::optional<double> RequestedMeshUnitScale(const core::Project& project);

}  // namespace uzp::python::assets3d
