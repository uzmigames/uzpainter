#pragma once

// Frozen procedural snapshots in the project file (`docs/architecture/05-procedural-content.md`
// §4, `09-project-file-format.md` §1, §2; decision 327).
//
// A snapshot is a raster the user's own Painter produced for this project, stored as an
// authoritative raster plane with its exact signature in the manifest. The manifest's top-level
// `procedural_snapshots` object holds one entry per snapshot, keyed by the SHA-256 of the
// signature's canonical JSON:
//
//     "procedural_snapshots": {"<signature sha256>": {
//         "signature": {...},            // procedural/seam.h SignatureJson
//         "project_uuid": "<uuid>",      // the project it was recorded for
//         "plane": <plane_id>,
//         "plane_versions": {"<plane_id>": {"chunk_root": <hex>, "version_id": <n>}},
//         "source_metadata": {...}}}    // optional, see below
//
// `source_metadata` is what the recording observed about the source beyond the signature:
// `{"schema": "uzpainter/procedural-source-metadata/1", "asset": "<asset>@<version>",
// "image_outputs": [...]}`, where `asset` is the signature's exact pin and `image_outputs` the
// source's complete ordered output identifiers (A-PYDOC `SourceSubstance.image_outputs`), which
// include the signature's output id. It is not part of the signature: an absent member means
// "not recorded" and is never written as empty or null, so entries recorded without it keep their
// bytes.
//
// The entry holds its plane as a mask-stack paint object does (`plane`, `plane_versions`), so the
// plane rules of planes.h cover it unchanged: its binding travels with the manifest (digest,
// revert, compaction reachability, integrity, `inspect`, `export-bundle` and the bundle import).
// The plane row has no texture set, stack, channel or UV tile (all 0 / NULL): a snapshot belongs
// to the project, not to a node.
//
// Snapshots are project-private: an entry recorded for another project is refused at commit
// (`CheckSnapshots`), reported by the integrity check and never served (SnapshotBackend). The
// document model keeps the key verbatim (`Project::extra`); the store owns it.

#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "store/container.h"
#include "store/planes.h"
#include "uzp_core/manifest/json.h"
#include "uzp_core/transaction/transaction.h"
#include "uzp_core/types/ids.h"
#include "uzp_core/types/project.h"

namespace uzp::store {

/// The manifest's top-level key of the snapshot entries.
inline constexpr std::string_view kSnapshotsKey = "procedural_snapshots";
/// An entry's optional member of recorded source metadata, and its schema.
inline constexpr std::string_view kSourceMetadataKey = "source_metadata";
inline constexpr std::string_view kSourceMetadataSchema = "uzpainter/procedural-source-metadata/1";

/// One entry of `procedural_snapshots`.
struct SnapshotEntry {
    std::string key;  ///< The signature SHA-256 the entry is stored under.
    core::json::Value signature;
    std::string project_uuid;
    core::Id plane_id = core::kNoId;
    std::optional<VersionRef> version;
    /// The recorded `image_outputs` of `source_metadata`; empty when the entry has none.
    std::optional<std::vector<std::string>> image_outputs;
    std::string path;   ///< The JSON path of the entry (`procedural_snapshots.<key>`).
    std::string error;  ///< Why the entry is malformed; empty when it is well-formed.
};

/// The `source_metadata` of a snapshot of `signature` recording `image_outputs`.
core::json::Value SourceMetadataJson(const core::json::Value& signature, const std::vector<std::string>& image_outputs);
/// Why `metadata` may not be the `source_metadata` of a snapshot of `signature`, or empty: it is
/// not an object of exactly `schema`, `asset` and `image_outputs`; its schema is not
/// `kSourceMetadataSchema`; `asset` is not the signature's `<asset>@<version>`; or `image_outputs`
/// is not a nonempty array of distinct nonempty strings that holds the signature's `output.id`.
std::string SourceMetadataProblem(const core::json::Value& signature, const core::json::Value& metadata);

/// Every entry of the `procedural_snapshots` member `member` (the manifest's, or the value
/// `Project::extra` holds), in key order. A member that is not an object gives one malformed
/// entry.
std::vector<SnapshotEntry> SnapshotEntries(const core::json::Value& member);
/// Every snapshot entry of `manifest` (none when it has no `procedural_snapshots`).
std::vector<SnapshotEntry> ManifestSnapshots(const core::json::Value& manifest);
/// The snapshot entries `project` holds.
std::vector<SnapshotEntry> ProjectSnapshots(const core::Project& project);

/// Why `entry` may not stand in the manifest of project `project_uuid`, or empty: it is
/// malformed, its key is not the SHA-256 of its signature's canonical JSON, or it was recorded
/// for another project.
std::string SnapshotProblem(const SnapshotEntry& entry, std::string_view project_uuid);

/// The commit check: throws `StoreError(conflict)` naming the first entry of `project` with a
/// `SnapshotProblem`, so a snapshot copied from another project is never committed.
void CheckSnapshots(const core::Project& project, std::string_view project_uuid);

/// Stages a snapshot of project `project_uuid` in the edit's working copy: allocates a plane id
/// from the project counter, stages `image` as its first version and adds the entry under the
/// SHA-256 of `signature`'s canonical JSON, with `source_metadata` when `image_outputs` is given.
/// Returns the plane id. The texels are stored unmodified in the image's plane format. Throws
/// `core::ValueError` when `signature` is not an object, the metadata has a
/// `SourceMetadataProblem`, the project already holds a snapshot with that signature (a snapshot
/// is immutable migration data), or the size is outside 1..`kMaxPlaneEdge` or does not match the
/// texels; `StoreError(conflict)` when the allocated id is already a stored plane.
core::Id StageSnapshot(Container& container, PendingPlanes& pending, core::Edit& edit,
                       std::string_view project_uuid, const core::json::Value& signature, const PlaneImage& image,
                       const std::optional<std::vector<std::string>>& image_outputs = std::nullopt);

}  // namespace uzp::store
