#pragma once

// The authoritative census of a project's raster planes, procedural snapshots and resources
// (decision 362 option 2, phase3.1 item 2.6j foundation). It is the store-side half of a future
// Filter observation context: every field is read from the store's own rows, staged state and
// bytes, verified, and serialised canonically. Nothing here creates, binds or evaluates anything,
// and no observation schema uses it yet.
//
// One call reads one `core::Project` against one consistent store view. Only a commit extension,
// which runs under the store's mutex, calls the unlocked `InventoryIn`; every other caller,
// including a transaction's call inside `Submit` (which runs without the mutex), uses
// `ProjectStore::ReadObservationInventory`, which takes the mutex once. No result is cached by
// version id: a running transaction replaces its own staged version under the same id
// (planes.h `StagePlaneContent`), so every call re-reads and re-hashes every byte. The project
// uuid is the container's own (`meta.project_uuid`), never a caller's argument.
//
// Checked, each failure a `StoreError`:
// - the project validates (`core::Validate`) and its projection without the top-level
//   `filter_source_observations` namespace round-trips through `ProjectFromJson` to the same
//   canonical text (`WriteCanonical` keeps int versus double and the sign of zero) (`conflict`);
// - every plane binding is well formed and every referenced plane is bound by the paint object
//   or snapshot entry that references it, once; every plane is held by exactly one paint node
//   (`paint.planes` or `paint.plane`) or snapshot entry, the object referencing it (a plane held,
//   referenced or bound twice is refused, as the commit refuses it, planes.h `WritePlaneRows`)
//   and no binding lacks a reference (`conflict`);
// - each plane's row (staged, else stored) and bound version (staged when the transaction holds
//   that id for that plane, else stored) exist (`missing_resource`); a staged id of another plane
//   is a `conflict`;
// - before any size is used, the row names that plane, its holder's texture set, stack and
//   channel (none for a mask-stack plane; no set, stack, channel or UV tile for a snapshot
//   plane) and one of the set's UV tiles, a size inside 1..`kMaxPlaneEdge`, the store's
//   `kChunkSize` and a known format (`corrupt`). A snapshot signature is any object here, as
//   `StageSnapshot` accepts it; its procedural meaning is checked where a host selects it;
// - the binding's `chunk_root` equals the version's and the root recomputed from its chunk rows,
//   every chunk lies inside the plane once, and every listed chunk's bytes (staged, else the
//   stored blob) hash to their row (`corrupt`); a listed chunk without bytes is
//   `missing_resource`, an unlisted chunk reads as zero bytes;
// - every `procedural_snapshots` entry, active or not, passes `SnapshotProblem` for the store's
//   project uuid (`conflict`);
// - every resource of `project.resources` has embedded bytes (stored blob, else staged) that hash
//   to it, and every record's `mime` and `size` equal the stored or staged ones (`corrupt`;
//   absent or locator-only bytes are `missing_resource`).
//
// The census holds every plane row field but `created_revision` (unset while staged, the commit
// revision afterwards), so a staged census equals the committed one; whether a version is staged
// or stored is not part of it.

#include <cstdint>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "store/commit.h"
#include "store/container.h"
#include "store/planes.h"
#include "uzp_core/manifest/json.h"
#include "uzp_core/types/project.h"

namespace uzp::store {

inline constexpr std::string_view kObservationInventorySchema = "uzpainter/observation-inventory/1";

/// A paint object or snapshot entry that references a plane: its path and owning node.
struct InventoryReference {
    std::string path;
    std::optional<core::Id> owner;
};

/// One verified plane.
struct InventoryPlane {
    PlaneRow row;  // `created_revision` is never serialised
    std::vector<InventoryReference> references;
    VersionRef version;
    std::vector<ChunkRow> chunks;  // sorted by (x, y)
    std::int64_t byte_count = 0;   // of the reconstructed texels
    std::string sha256;            // of the reconstructed texels
};

/// One verified resource: its bytes' size and MIME type, and every manifest record of the hash.
struct InventoryResource {
    std::string sha256;
    std::int64_t size = 0;
    std::string mime;
    core::json::Array records;
};

struct ObservationInventory {
    std::string project_uuid;
    std::vector<InventoryPlane> planes;        // by plane id
    std::vector<InventoryResource> resources;  // by SHA-256
    std::vector<std::string> snapshots;        // every snapshot entry's key, sorted

    /// The canonical census (`kObservationInventorySchema`).
    core::json::Value ToJson() const;
    /// SHA-256 of the canonical JSON of `ToJson()`.
    std::string Sha256() const;
};

/// The census of `project` against `container` (whose `meta.project_uuid` it uses) and the
/// transaction's staged planes and resources. The caller holds the store's mutex: only a commit
/// extension calls it. Throws `StoreError` as described above.
ObservationInventory InventoryIn(Container& container, const PendingPlanes& planes, const PendingContent& content,
                                 const core::Project& project);

}  // namespace uzp::store
