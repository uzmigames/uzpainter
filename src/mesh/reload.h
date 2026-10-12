#pragma once

// Mesh reload (`docs/architecture/12-mesh-import.md` §7, `03-project-model.md` §4; PRJ-08,
// BAK-06): replace a project's mesh while keeping its texture sets, stacks and resources.
//
// `ReloadMesh` is one document transaction (`core::Execute`):
// 1. Re-derive the current mesh from its stored bytes (`ResourceReader`) with the settings its
//    import report records, and check that it gives the stored hashes.
// 2. Parse and certify the new mesh (`ImportMesh`; every import refusal applies).
// 3. Match texture sets by material identity: a material whose name is in both meshes keeps its
//    set; `ReloadSettings::material_mapping` accepts renames. A material that disappears while
//    its triangles (same object, same UV triangle) reappear under other materials is a rename, a
//    split or a merge, and the reload fails with `MaterialMappingError` carrying the mapping
//    proposal; a set is never attached silently. Otherwise a material that disappears without a
//    trace removes its set and a material that appears without one adds a set.
// 4. Classify the texels of every set on its texel grid (tile 1001, the `uv_raster.h` texel and
//    coverage convention, evaluated on the CPU) from the corner hashes of the triangle covering
//    each texel centre before and after: `unchanged`, `moved` (same UV triangle, different
//    position, normal or tangent frame), `new` (covered only now), `replaced` (covered by another
//    UV triangle) and `removed` (covered only before).
// 5. Invalidate what depends on the changed mesh, keeping it: mesh-map bindings (`invalid`,
//    `invalid_report`), geometry masks and procedural nodes (`invalid` and `invalid_report` in
//    their `extra` members, written to the manifest beside their fields); receipts are outside
//    the project and are judged by `ReceiptInvalidated`.
// A failure at any point (refused import, mapping error, invalid project, commit sink) commits
// nothing: the old mesh, its sets and every binding stay as they were.

#include <cstdint>
#include <exception>
#include <filesystem>
#include <functional>
#include <map>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

#include "mesh/mesh_import.h"
#include "uzp_core/document/document.h"
#include "uzp_core/manifest/json.h"
#include "uzp_core/transaction/transaction.h"
#include "uzp_core/types/enums.h"
#include "uzp_core/types/errors.h"
#include "uzp_core/types/ids.h"
#include "uzp_core/types/project.h"
#include "uzp_core/types/receipt.h"

namespace uzp::mesh {

/// The bytes the project store keeps under `sha256` (the original mesh file). Throws when they
/// cannot be read.
using ResourceReader = std::function<std::string(const std::string& sha256)>;

struct ReloadSettings {
    /// How the new mesh is imported (`mesh_unit_scale`, duplicate names, certificate grid).
    ImportSettings import;
    /// Accepted renames, current material name -> new material name (one to one), e.g. the
    /// `mapping` of a `MaterialMappingError` proposal.
    std::map<std::string, std::string> material_mapping;
    /// The channels of the stack of every texture set the reload adds.
    std::map<core::ChannelType, core::Channel> new_set_channels;
};

/// The reload refused because materials were renamed, split or merged (12 §7: never a silent
/// attach). `details()`: `{"proposal": [{"kind": "rename"|"split"|"merge", "from": [...],
/// "to": [...]}], "mapping": {old: new}}`, where `mapping` holds the renames, ready for
/// `ReloadSettings::material_mapping`.
class MaterialMappingError : public std::runtime_error {
public:
    MaterialMappingError(const std::string& message, core::json::Object details)
        : std::runtime_error(message), details_(std::move(details)) {}
    const core::json::Object& details() const { return details_; }

private:
    core::json::Object details_;
};

/// The error class name the bindings raise for `MaterialMappingError`.
inline constexpr std::string_view kMaterialMappingErrorClass = "MaterialMappingError";

enum class TexelClass : std::uint8_t { none, unchanged, moved, new_, replaced, removed };

/// "none", "unchanged", "moved", "new", "replaced", "removed".
std::string_view TexelClassName(TexelClass value);

/// The texels of one texture set on its `width` x `height` grid of tile 1001, row 0 at the top
/// (v = 1), row-major.
struct SetRegions {
    std::string texture_set;  ///< the set's material name after the reload (before, if removed)
    int width = 0;
    int height = 0;
    std::vector<TexelClass> texels;
    std::uint64_t unchanged = 0, moved = 0, new_ = 0, replaced = 0, removed = 0;

    /// Any texel moved, new, replaced or removed.
    bool Changed() const { return moved + new_ + replaced + removed > 0; }
    /// Any texel new, replaced or removed (the set's UV coverage changed).
    bool CoverageChanged() const { return new_ + replaced + removed > 0; }
    /// `{grid {width, height}, moved, new, removed, replaced, unchanged}`.
    core::json::Object ToJson() const;
};

struct MeshMapRef {
    std::string texture_set;
    core::MeshMapUsage usage = core::MeshMapUsage::AO;
};

struct ReloadReport {
    std::vector<std::string> added;    ///< sets created for new materials, in material order
    std::vector<std::string> removed;  ///< sets of materials that disappeared
    std::vector<std::pair<std::string, std::string>> renamed;  ///< (from, to), by `material_mapping`
    std::vector<SetRegions> regions;   ///< every set before or after, in material order
    std::string mesh_from, mesh_to;    ///< SHA-256 of the old and new mesh files
    /// The texturing-mesh hashes that differ ("positions", "uvs", "corner_normals",
    /// "triangulation", "materials") and "units" when the effective scale changed.
    std::vector<std::string> changed;
    std::vector<MeshMapRef> invalid_mesh_maps;
    std::vector<core::Id> invalid_geometry_masks;  ///< layer uids
    std::vector<core::Id> invalid_procedural;      ///< layer or effect uids
    /// Resource hashes whose receipts are now invalid: the old mesh and invalidated mesh maps.
    std::vector<std::string> invalid_receipt_resources;

    /// `{sets {added, removed, renamed [{from, to}]}, regions {<set>: SetRegions}, mesh {from, to,
    /// changed}, invalidated {mesh_maps [{texture_set, usage}], geometry_masks, procedural,
    /// receipt_resources}}`.
    core::json::Object ToJson() const;
};

struct ReloadOutcome {
    /// The transaction's outcome; its result's `returned.reload` is `report->ToJson()`.
    core::RequestOutcome outcome;
    /// Set when the reload was applied: committed, or a no-op for an identical mesh from the same
    /// path (from another path the new `mesh.source` is a metadata-only commit, decision 123).
    std::optional<ReloadReport> report;
    /// The typed error behind a failed result (`ImportError`, `MaterialMappingError`,
    /// `core::ValueError`, a reader or commit error), for the bindings to raise.
    std::exception_ptr error;
};

/// Inside a transaction: reloads the project's mesh with `next` (an accepted import), as
/// described above; `current` is the re-derived current mesh (`RederiveMesh`). Throws
/// `MaterialMappingError` or `core::ValueError`; the caller's transaction then commits nothing.
ReloadReport ApplyReload(core::Edit& edit, const ImportResult& current, const ImportResult& next,
                         const MeshSource& source, const ReloadSettings& settings);

/// The old geometry cannot be recovered: the current mesh is a glTF of a project written before a
/// mesh's external files were stored (its import report has no `core::kMeshExternalFiles`), and a
/// file it reads beside its origin is gone, or altered so that the mesh no longer gives the
/// recorded geometry, or the caller reads stored files only. `ReloadMesh` then replaces the mesh
/// without re-deriving it (`ApplyReloadWithoutCurrent`). A stored file or mesh whose bytes do not
/// give the recorded geometry is corruption: `core::ValueError`.
class MeshFileMissing : public core::ValueError {
public:
    using core::ValueError::ValueError;
};

/// The current mesh of `project` re-derived from its stored bytes with the settings its import
/// report records (`requested_mesh_unit_scale`, merged duplicate names). A glTF's external
/// buffers are the stored resources its report lists (`core::kMeshExternalFiles`). A report
/// written before they were stored lists none: its files are read beside the resource's `origin`,
/// as that version did, when `beside_origin` (`MeshFileMissing` when one is gone, or always
/// without `beside_origin`, or when such a file no longer gives the recorded hashes); the
/// re-derived hashes are checked either way. Throws
/// `core::ValueError` when the project has no mesh, a listed file is not stored, or the bytes do
/// not give the stored hashes.
ImportResult RederiveMesh(const core::Project& project, const ResourceReader& read, bool beside_origin = true);

/// The reload when the current mesh cannot be re-derived (`MeshFileMissing`, whose message is
/// `reason`): with no old geometry to compare, every texture set keeps its material by name or
/// through `material_mapping` (a set whose material the new mesh lacks is a `MaterialMappingError`
/// before anything changes), every mesh-map binding and mesh geometry mask of a kept set is
/// invalidated with `previous_mesh: reason` in its report, every hash counts as changed, and a
/// new material adds a set. The new mesh and its external files are recorded as by `ApplyReload`,
/// so the project re-derives again afterwards.
ReloadReport ApplyReloadWithoutCurrent(core::Edit& edit, const ImportResult& next, const MeshSource& source,
                                       const ReloadSettings& settings, const std::string& reason);

/// `project.reload_mesh(path, settings)`: one transaction (`request`) that re-derives the
/// current mesh, imports `path` and applies `ApplyReload` (`ApplyReloadWithoutCurrent` when the
/// current mesh is `MeshFileMissing`). Never throws for a failing reload: the outcome is `failed`
/// and `error` holds the typed error.
ReloadOutcome ReloadMesh(core::Document& document, core::MutationRequest request, const std::filesystem::path& path,
                         const ReloadSettings& settings, const ResourceReader& read, const MeshSource& source);

/// A receipt (export, capture, bake, recipe dump) is invalid in `project` when it read a mesh
/// file the project's mesh no longer reads (the mesh file or a file beside it, such as a glTF's
/// buffer: `core::MeshResourceHashes`) or the resource of an invalid mesh-map binding.
bool ReceiptInvalidated(const core::ResultRecordHeader& header, const core::Project& project);

}  // namespace uzp::mesh
