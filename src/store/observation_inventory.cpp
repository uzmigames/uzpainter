#include "store/observation_inventory.h"

#include <algorithm>
#include <map>
#include <set>
#include <utility>

#include "store/blobs.h"
#include "store/snapshots.h"
#include "uzp_core/document/nodes.h"
#include "uzp_core/manifest/manifest.h"
#include "uzp_core/manifest/sha256.h"
#include "uzp_core/types/errors.h"
#include "uzp_core/types/resource_url.h"
#include "uzp_core/types/validation.h"

namespace uzp::store {

using core::Id;
using core::json::Array;
using core::json::Object;
using core::json::Value;

namespace {

[[noreturn]] void Refuse(StoreError::Code code, const std::string& message) {
    throw StoreError(code, "observation inventory: " + message);
}

std::string PlaneName(Id plane_id) { return "plane " + std::to_string(plane_id); }

/// The bytes of one listed chunk: the staged bytes when the version holds them, else the stored
/// blob, verified against the chunk row's hash and the chunk's size.
std::string ChunkBytes(Container& container, const PlaneRow& row, const ChunkRow& chunk, const StagedVersion* staged) {
    const std::size_t size = ChunkByteCount(row, chunk.x, chunk.y);
    const std::string where = PlaneName(row.plane_id) + " chunk (" + std::to_string(chunk.x) + "," +
                              std::to_string(chunk.y) + ")";
    if (staged != nullptr) {
        if (const auto it = staged->bytes.find(chunk.sha256); it != staged->bytes.end()) {
            if (it->second.size() != size) Refuse(StoreError::Code::corrupt, where + ": staged bytes have the wrong size");
            if (core::Sha256Hex(it->second) != chunk.sha256) {
                Refuse(StoreError::Code::corrupt, where + ": staged bytes do not hash to the chunk row");
            }
            return it->second;
        }
    }
    if (!HasBlob(container, chunk.sha256)) Refuse(StoreError::Code::missing_resource, where + ": no bytes");
    try {
        return ReadChunkBlob(container, chunk.sha256, size);
    } catch (const StoreError& error) {
        Refuse(StoreError::Code::corrupt, where + ": " + error.what());
    }
}

/// The stored version `ref` of `plane_id`: its plane_version row must name the plane and the
/// binding's root.
std::vector<ChunkRow> StoredChunks(Container& container, Id plane_id, const VersionRef& ref) {
    Statement q(container, "SELECT plane_id, chunk_root FROM plane_version WHERE version_id = ?");
    q.Bind(1, ref.version_id);
    if (!q.Step()) {
        Refuse(StoreError::Code::missing_resource,
               PlaneName(plane_id) + ": plane_version " + std::to_string(ref.version_id) + " is not stored");
    }
    if (q.IsNull(0) || static_cast<Id>(q.Int(0)) != plane_id) {
        Refuse(StoreError::Code::conflict,
               PlaneName(plane_id) + ": plane_version " + std::to_string(ref.version_id) + " belongs to another plane");
    }
    if (q.Text(1) != ref.chunk_root) {
        Refuse(StoreError::Code::corrupt, PlaneName(plane_id) + ": the binding's chunk_root differs from plane_version " +
                                              std::to_string(ref.version_id));
    }
    return ReadChunkRows(container, ref.version_id);
}

/// What holds a plane in the project: a paint node (its set, stack and channel; none for a
/// mask-stack plane) or a procedural snapshot entry (no set, stack, channel or UV tile).
struct PlaneHolder {
    bool snapshot = false;
    std::optional<Id> owner;  // the paint node; none for a snapshot entry
    Id set = core::kNoId;
    Id stack = core::kNoId;
    std::optional<core::ChannelType> channel;
    std::string path;  // a snapshot entry's path
};

/// Every plane the project's paint nodes and snapshot entries hold, by plane id; a plane held twice
/// is refused, as the commit refuses it (planes.h `WritePlaneRows`).
std::map<Id, PlaneHolder> PlaneHolders(const core::Project& project) {
    std::map<Id, PlaneHolder> holders;
    const auto hold = [&](Id plane_id, PlaneHolder holder) {
        if (!holders.emplace(plane_id, std::move(holder)).second) {
            Refuse(StoreError::Code::conflict, PlaneName(plane_id) + " is held twice");
        }
    };
    core::ForEachNode(project, [&](const core::NodeVisit& visit) {
        const auto& paint = visit.layer ? visit.layer->paint : visit.effect->paint;
        if (!paint) return;
        const Id uid = visit.layer ? visit.layer->uid : visit.effect->uid;
        for (const auto& [channel, plane_id] : paint->planes) {
            hold(plane_id, PlaneHolder{false, uid, visit.texture_set, visit.stack, channel, {}});
        }
        if (paint->mono_plane) hold(*paint->mono_plane, PlaneHolder{false, uid, visit.texture_set, visit.stack, std::nullopt, {}});
    });
    for (const SnapshotEntry& entry : ProjectSnapshots(project)) {
        if (entry.plane_id != core::kNoId) hold(entry.plane_id, PlaneHolder{true, std::nullopt, core::kNoId, core::kNoId, std::nullopt, entry.path});
    }
    return holders;
}

/// Refuses a row that does not describe `plane_id` as its holder makes it, before any size is used:
/// the id, the holder's set, stack, channel and one of the set's UV tiles (a snapshot plane has
/// none), a size inside 1..kMaxPlaneEdge, the store's chunk size and a known format.
void CheckRow(const PlaneRow& row, Id plane_id, const PlaneHolder& holder, const core::Project& project) {
    const auto refuse = [&](const std::string& what) {
        Refuse(StoreError::Code::corrupt, PlaneName(plane_id) + ": its row " + what);
    };
    if (row.plane_id != plane_id) refuse("names plane " + std::to_string(row.plane_id));
    if (row.width < 1 || row.height < 1 || row.width > kMaxPlaneEdge || row.height > kMaxPlaneEdge) {
        refuse("has a size outside 1.." + std::to_string(kMaxPlaneEdge));
    }
    if (row.chunk_size != kChunkSize) refuse("has chunk size " + std::to_string(row.chunk_size));
    if (!core::FromString<core::ChannelFormat>(core::ToString(row.format))) refuse("has an unknown format");
    if (row.set_id != holder.set || row.stack_id != holder.stack || row.channel != holder.channel) {
        refuse("names another texture set, stack or channel than its holder");
    }
    if (holder.snapshot) {
        if (row.tile_u != 0 || row.tile_v != 0) refuse("of a snapshot names a UV tile");
        return;
    }
    // The tile range is checked before any arithmetic; the UDIM is computed in 64 bits.
    if (row.tile_u < 0 || row.tile_u > 9 || row.tile_v < 0) refuse("names a UV tile outside the UDIM grid");
    const std::int64_t udim = 1001 + std::int64_t{row.tile_u} + 10 * std::int64_t{row.tile_v};
    const auto set = std::find_if(project.texture_sets.begin(), project.texture_sets.end(),
                                  [&](const core::TextureSet& s) { return s.id == row.set_id; });
    if (set == project.texture_sets.end() ||
        std::none_of(set->uv_tiles.begin(), set->uv_tiles.end(),
                     [&](const core::UVTile& t) { return std::int64_t{t.udim} == udim; })) {
        refuse("names a UV tile its texture set does not hold");
    }
}

InventoryPlane CensusPlane(Container& container, const PendingPlanes& pending, Id plane_id, const VersionRef& ref,
                           std::vector<InventoryReference> references, const PlaneHolder& holder,
                           const core::Project& project) {
    InventoryPlane plane;
    plane.references = std::move(references);
    plane.version = ref;
    if (const auto created = pending.planes.find(plane_id); created != pending.planes.end()) {
        plane.row = created->second;
    } else if (const std::optional<PlaneRow> stored = ReadPlaneRow(container, plane_id)) {
        plane.row = *stored;
    } else {
        Refuse(StoreError::Code::missing_resource, PlaneName(plane_id) + " has no plane row");
    }
    CheckRow(plane.row, plane_id, holder, project);
    const StagedVersion* staged = nullptr;
    if (const auto it = pending.versions.find(ref.version_id); it != pending.versions.end()) {
        if (it->second.plane_id != plane_id) {
            Refuse(StoreError::Code::conflict,
                   PlaneName(plane_id) + ": staged version " + std::to_string(ref.version_id) + " belongs to another plane");
        }
        staged = &it->second;
        if (staged->chunk_root != ref.chunk_root) {
            Refuse(StoreError::Code::corrupt, PlaneName(plane_id) + ": the binding's chunk_root differs from staged version " +
                                                  std::to_string(ref.version_id));
        }
        plane.chunks = staged->chunks;
    } else {
        plane.chunks = StoredChunks(container, plane_id, ref);
    }
    std::sort(plane.chunks.begin(), plane.chunks.end(),
              [](const ChunkRow& a, const ChunkRow& b) { return std::pair(a.x, a.y) < std::pair(b.x, b.y); });
    if (ChunkRoot(plane.chunks) != ref.chunk_root) {
        Refuse(StoreError::Code::corrupt, PlaneName(plane_id) + ": the chunk rows do not hash to the bound chunk_root");
    }
    const PlaneRow& row = plane.row;
    std::string texels(static_cast<std::size_t>(row.width) * static_cast<std::size_t>(row.height) * TexelBytes(row.format),
                       '\0');
    std::set<std::pair<int, int>> seen;
    for (const ChunkRow& chunk : plane.chunks) {
        if (chunk.x < 0 || chunk.y < 0 || chunk.x >= row.chunks_x() || chunk.y >= row.chunks_y() ||
            !seen.insert({chunk.x, chunk.y}).second) {
            Refuse(StoreError::Code::corrupt, PlaneName(plane_id) + ": chunk (" + std::to_string(chunk.x) + "," +
                                                  std::to_string(chunk.y) + ") is outside the plane or listed twice");
        }
        PutChunk(row, texels, chunk.x, chunk.y, ChunkBytes(container, row, chunk, staged));
    }
    plane.byte_count = static_cast<std::int64_t>(texels.size());
    plane.sha256 = core::Sha256Hex(texels);
    return plane;
}

InventoryResource CensusResource(Container& container, const PendingContent& content, const std::string& sha256,
                                 const std::vector<core::ResourceMeta>& metas, const Value& records) {
    InventoryResource resource;
    resource.sha256 = sha256;
    if (const auto* list = std::get_if<Array>(&records.data)) resource.records = *list;
    std::string bytes;
    if (HasBlob(container, sha256)) {
        try {
            bytes = ReadBlob(container, sha256);
        } catch (const StoreError& error) {
            Refuse(StoreError::Code::corrupt, "resource " + sha256 + ": " + error.what());
        }
        Statement q(container, "SELECT mime FROM blob WHERE sha256 = ?");
        q.Bind(1, sha256);
        if (!q.Step()) Refuse(StoreError::Code::missing_resource, "resource " + sha256 + " has no blob row");
        resource.mime = q.IsNull(0) ? std::string() : q.Text(0);
    } else if (const auto staged = content.blobs.find(sha256); staged != content.blobs.end()) {
        if (core::Sha256Hex(staged->second.bytes) != sha256) {
            Refuse(StoreError::Code::corrupt, "resource " + sha256 + ": staged bytes do not hash to it");
        }
        bytes = staged->second.bytes;
        resource.mime = staged->second.mime;
    } else {
        Refuse(StoreError::Code::missing_resource, "resource " + sha256 + " has no embedded bytes");
    }
    resource.size = static_cast<std::int64_t>(bytes.size());
    for (const core::ResourceMeta& meta : metas) {
        if (meta.mime != resource.mime || meta.size != resource.size) {
            Refuse(StoreError::Code::corrupt, "resource " + sha256 + ": the record '" + meta.name +
                                                  "' names another MIME type or size than its bytes");
        }
    }
    return resource;
}

}  // namespace

Value ObservationInventory::ToJson() const {
    Array planesJson;
    for (const InventoryPlane& plane : planes) {
        Array references;
        for (const InventoryReference& reference : plane.references) {
            references.push_back(Object{{"owner", reference.owner ? Value(static_cast<std::int64_t>(*reference.owner)) : Value()},
                                        {"path", reference.path}});
        }
        Array chunks;
        for (const ChunkRow& chunk : plane.chunks) chunks.push_back(Array{chunk.x, chunk.y, chunk.sha256});
        const PlaneRow& row = plane.row;
        planesJson.push_back(Object{
            {"plane_id", static_cast<std::int64_t>(row.plane_id)},
            {"references", std::move(references)},
            {"set_id", static_cast<std::int64_t>(row.set_id)},
            {"stack_id", static_cast<std::int64_t>(row.stack_id)},
            {"channel", row.channel ? Value(std::string(core::ToString(*row.channel))) : Value()},
            {"tile_u", row.tile_u},
            {"tile_v", row.tile_v},
            {"format", std::string(core::ToString(row.format))},
            {"width", row.width},
            {"height", row.height},
            {"chunk_size", row.chunk_size},
            {"version_id", plane.version.version_id},
            {"chunk_root", plane.version.chunk_root},
            {"chunks", std::move(chunks)},
            {"byte_count", plane.byte_count},
            {"sha256", plane.sha256},
        });
    }
    Array resourcesJson;
    for (const InventoryResource& resource : resources) {
        resourcesJson.push_back(Object{{"sha256", resource.sha256},
                                       {"size", resource.size},
                                       {"mime", resource.mime},
                                       {"records", resource.records}});
    }
    return Object{{"schema", std::string(kObservationInventorySchema)},
                  {"project_uuid", project_uuid},
                  {"planes", std::move(planesJson)},
                  {"resources", std::move(resourcesJson)},
                  {"snapshots", Array(snapshots.begin(), snapshots.end())}};
}

std::string ObservationInventory::Sha256() const { return core::Sha256Hex(core::json::WriteCanonical(ToJson())); }

ObservationInventory InventoryIn(Container& container, const PendingPlanes& planes, const PendingContent& content,
                                 const core::Project& project) {
    const std::optional<std::string> project_uuid = container.Meta("project_uuid");
    if (!project_uuid || project_uuid->empty()) Refuse(StoreError::Code::conflict, "the container records no project uuid");

    Value manifest = core::ProjectToJson(project);
    if (auto* top = std::get_if<Object>(&manifest.data)) top->erase(std::string(core::kFilterObservationsKey));
    try {
        core::Validate(project);
        // Canonical text, not Value equality: it keeps int versus double and the sign of zero.
        const std::string canonical = core::json::WriteCanonical(manifest);
        if (core::json::WriteCanonical(core::ProjectToJson(core::ProjectFromJson(manifest))) != canonical) {
            Refuse(StoreError::Code::conflict, "the projection does not round-trip");
        }
    } catch (const core::ValueError& error) {
        Refuse(StoreError::Code::conflict, std::string("the project does not validate: ") + error.what());
    } catch (const core::ManifestError& error) {
        Refuse(StoreError::Code::conflict, std::string("the projection does not load: ") + error.what());
    }

    ObservationInventory inventory;
    inventory.project_uuid = *project_uuid;

    for (const SnapshotEntry& entry : ProjectSnapshots(project)) {
        if (const std::string problem = SnapshotProblem(entry, *project_uuid); !problem.empty()) {
            Refuse(StoreError::Code::conflict, entry.path + ": " + problem);
        }
        inventory.snapshots.push_back(entry.key);
    }
    std::sort(inventory.snapshots.begin(), inventory.snapshots.end());
    const std::map<Id, PlaneHolder> holders = PlaneHolders(project);

    std::map<Id, std::vector<InventoryReference>> references;
    for (const PlaneReference& reference : ManifestPlaneReferences(manifest)) {
        if (!reference.bound) {
            Refuse(StoreError::Code::conflict, PlaneName(reference.plane_id) + " is not bound by " + reference.path);
        }
        const auto holder = holders.find(reference.plane_id);
        if (holder == holders.end() || reference.owner != holder->second.owner ||
            (holder->second.snapshot && reference.path != holder->second.path)) {
            Refuse(StoreError::Code::conflict, reference.path + " references " + PlaneName(reference.plane_id) +
                                                   ", which no paint node or snapshot entry there holds");
        }
        auto& list = references[reference.plane_id];
        if (!list.empty()) Refuse(StoreError::Code::conflict, PlaneName(reference.plane_id) + " is referenced twice");
        list.push_back(InventoryReference{reference.path, reference.owner});
    }
    for (const auto& [plane_id, holder] : holders) {
        if (!references.contains(plane_id)) {
            Refuse(StoreError::Code::conflict, PlaneName(plane_id) + " is held but not referenced");
        }
    }
    std::map<Id, VersionRef> bindings;
    for (const ManifestBinding& binding : ManifestPlaneBindings(manifest)) {
        if (!binding.version) Refuse(StoreError::Code::conflict, binding.path + ": " + binding.error);
        if (!references.contains(binding.plane_id)) {
            Refuse(StoreError::Code::conflict, binding.path + " binds " + PlaneName(binding.plane_id) + ", which it does not reference");
        }
        if (!bindings.emplace(binding.plane_id, *binding.version).second) {
            Refuse(StoreError::Code::conflict, PlaneName(binding.plane_id) + " is bound twice");
        }
    }
    for (auto& [plane_id, list] : references) {
        inventory.planes.push_back(CensusPlane(container, planes, plane_id, bindings.at(plane_id), std::move(list),
                                               holders.at(plane_id), project));
    }

    const auto* top = std::get_if<Object>(&manifest.data);
    const Value* records = nullptr;
    if (top != nullptr) {
        if (const auto it = top->find("resources"); it != top->end()) records = &it->second;
    }
    for (const auto& [sha256, metas] : project.resources) {
        Value recordsOf;
        if (records != nullptr) {
            if (const auto* map = std::get_if<Object>(&records->data)) {
                if (const auto it = map->find(sha256); it != map->end()) recordsOf = it->second;
            }
        }
        inventory.resources.push_back(CensusResource(container, content, sha256, metas, recordsOf));
    }
    return inventory;
}

}  // namespace uzp::store
