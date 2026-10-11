#pragma once

// Mesh import (`docs/architecture/12-mesh-import.md` §2, §3, §6, §8): format selection, the
// explicit refusals, the duplicate-material-name rule, units, the content hashes and the import
// report; and the document side, which stores the mesh resource and creates one texture set per
// material in file order (PRJ-01, PRJ-02, PRJ-07).
//
// Order of the checks: `AutoUnwrapSettings` (rejected before anything is read), the format
// (release gaps, unsupported extensions), parsing, duplicate material names, UVs outside tile
// 1001, then units. An accepted mesh then gets its MikkTSpace tangent frames (`tangents.h`) and
// its certificate (`certificate.h`), stored in the import report beside the hashes. A refused
// import creates nothing.

#include <cstdint>
#include <filesystem>
#include <map>
#include <optional>
#include <string>
#include <string_view>

#include "mesh/certificate.h"
#include "mesh/texturing_mesh.h"
#include "uzp_core/manifest/json.h"
#include "uzp_core/transaction/transaction.h"
#include "uzp_core/types/enums.h"
#include "uzp_core/types/project.h"

namespace uzp::mesh {

enum class MeshFormat { obj, fbx, gltf, glb };

std::string_view FormatName(MeshFormat format);

/// The format of `file_name` by its extension (case-insensitive): `.obj`, `.fbx`, `.gltf`,
/// `.glb`. Throws `ImportError`: `release_gap` for `.dae`, `.ply`, `.usd`, `.usda`, `.usdc` and
/// `.usdz` (formats Painter imports that UzPainter v1 does not), `unsupported_format` otherwise.
MeshFormat FormatOf(std::string_view file_name);

/// The import arguments of `project.create` / `Settings` that concern the mesh.
struct ImportSettings {
    /// Painter's `mesh_unit_scale`: unset or 0 uses the file unit; otherwise the centimetres per
    /// file unit to use. Must be finite and not negative.
    std::optional<double> mesh_unit_scale;
    /// Merge materials that share a name into the first of them (one texture set) instead of
    /// failing the import.
    bool allow_duplicate_material_names = false;
    /// `AutoUnwrapSettings`, when given: recorded in the error and rejected (`NotYetSupported`).
    std::optional<core::json::Object> auto_unwrap;
    /// The texel grid of the certificate's pixel metrics: the texture sets' resolution.
    CertificateOptions certificate;
};

struct ImportResult {
    TexturingMesh mesh;
    MeshFormat format = MeshFormat::obj;
    std::string file_name;
    std::string sha256;  ///< of the original file bytes (the mesh resource)
    std::int64_t size = 0;
    /// The certificate of `mesh` (12 §4); never a repair.
    Certificate certificate;
    /// The import report stored as `MeshReference::import_report`: format, source, units
    /// (requested and effective), objects, materials and merges, counts, flags, hashes and the
    /// certificate (`CertificateToJson`).
    core::json::Object report;
};

/// Imports `bytes`, the content of the file `file_name`; a glTF's external buffers are read from
/// `directory`. Throws `ImportError` for every refusal and `core::ValueError` for invalid
/// settings.
ImportResult ImportMesh(std::string_view bytes, std::string_view file_name, const ImportSettings& settings,
                        const std::filesystem::path& directory = {});

/// Reads `path` and imports it (`directory` = the file's folder).
ImportResult ImportMeshFile(const std::filesystem::path& path, const ImportSettings& settings);

/// Where the mesh came from, for its resource entry.
struct MeshSource {
    std::string origin;       ///< the path or URL it was imported from
    std::string imported_at;  ///< RFC 3339 UTC
};

/// The MIME type stored with the mesh resource.
std::string_view MimeOf(MeshFormat format);

/// Inside one transaction (`core::Execute`): records the mesh resource (the original bytes are
/// stored under `result.sha256` by the project store; an entry already present is noted as
/// skipped), sets `project.mesh` with the import report, and creates one texture set per material
/// in file order, each named after its material, with the project's default resolution, UV tile
/// 1001 and one ordinary stack with `channels`. Throws `core::ValueError` when the project
/// already has a mesh or texture sets (reload is `phase1.6_mesh-reload`).
void CreateTextureSets(core::Edit& edit, const ImportResult& result, const MeshSource& source,
                       const std::map<core::ChannelType, core::Channel>& channels);

}  // namespace uzp::mesh
