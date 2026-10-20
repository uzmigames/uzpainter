#include "store/snapshots.h"

#include "uzp_core/manifest/sha256.h"
#include "uzp_core/types/errors.h"

namespace uzp::store {

using core::Id;
using core::json::Object;
using core::json::Value;

std::vector<SnapshotEntry> SnapshotEntries(const Value& member) {
    std::vector<SnapshotEntry> out;
    const std::string base(kSnapshotsKey);
    const auto* entries = std::get_if<Object>(&member.data);
    if (entries == nullptr) {
        SnapshotEntry malformed;
        malformed.path = base;
        malformed.error = "procedural_snapshots is not an object";
        out.push_back(std::move(malformed));
        return out;
    }
    for (const auto& [key, value] : *entries) {
        SnapshotEntry entry;
        entry.key = key;
        entry.path = base + "." + key;
        const auto* object = std::get_if<Object>(&value.data);
        if (object == nullptr) {
            entry.error = "the entry is not an object";
            out.push_back(std::move(entry));
            continue;
        }
        const auto member_of = [&](std::string_view name) -> const Value* {
            const auto it = object->find(name);
            return it == object->end() ? nullptr : &it->second;
        };
        const Value* signature = member_of("signature");
        const Value* uuid = member_of("project_uuid");
        const Value* plane = member_of("plane");
        const Value* versions = member_of(kPlaneVersionsKey);
        if (signature == nullptr || !signature->IsObject()) {
            entry.error = "the entry has no signature object";
        } else if (uuid == nullptr || !uuid->IsString() || std::get<std::string>(uuid->data).empty()) {
            entry.error = "the entry names no project_uuid";
        } else if (plane == nullptr || !plane->IsInt() || std::get<std::int64_t>(plane->data) <= 0) {
            entry.error = "the entry holds no plane";
        } else {
            entry.signature = *signature;
            entry.project_uuid = std::get<std::string>(uuid->data);
            entry.plane_id = static_cast<Id>(std::get<std::int64_t>(plane->data));
            const auto* map = versions ? std::get_if<Object>(&versions->data) : nullptr;
            const auto bound = map ? map->find(std::to_string(entry.plane_id)) : Object::const_iterator{};
            if (map == nullptr || bound == map->end()) {
                entry.error = "the entry does not bind its plane " + std::to_string(entry.plane_id);
            } else if (map->size() != 1) {
                entry.error = "the entry binds planes other than its own";
            } else {
                entry.version = ParseBinding(bound->second, entry.error);
            }
        }
        out.push_back(std::move(entry));
    }
    return out;
}

std::vector<SnapshotEntry> ManifestSnapshots(const Value& manifest) {
    const auto* top = std::get_if<Object>(&manifest.data);
    if (top == nullptr) return {};
    const auto member = top->find(kSnapshotsKey);
    return member == top->end() ? std::vector<SnapshotEntry>{} : SnapshotEntries(member->second);
}

std::vector<SnapshotEntry> ProjectSnapshots(const core::Project& project) {
    const auto member = project.extra.find(kSnapshotsKey);
    return member == project.extra.end() ? std::vector<SnapshotEntry>{} : SnapshotEntries(member->second);
}

std::string SnapshotProblem(const SnapshotEntry& entry, std::string_view project_uuid) {
    if (!entry.error.empty()) return entry.error;
    const std::string hash = core::Sha256Hex(core::json::WriteCanonical(entry.signature));
    if (hash != entry.key) {
        return "the entry is stored under " + entry.key + ", its signature hashes to " + hash;
    }
    if (entry.project_uuid != project_uuid) {
        return "the snapshot was recorded for project " + entry.project_uuid + ", not for project " +
               std::string(project_uuid) + ": snapshots are project-private and are never copied into another project";
    }
    return {};
}

void CheckSnapshots(const core::Project& project, std::string_view project_uuid) {
    for (const SnapshotEntry& entry : ProjectSnapshots(project)) {
        const std::string problem = SnapshotProblem(entry, project_uuid);
        if (!problem.empty()) throw StoreError(StoreError::Code::conflict, entry.path + ": " + problem);
    }
}

Id StageSnapshot(Container& container, PendingPlanes& pending, core::Edit& edit, std::string_view project_uuid,
                 const Value& signature, const PlaneImage& image) {
    if (!signature.IsObject()) throw core::ValueError("snapshot: the signature is not a JSON object");
    if (image.width < 1 || image.height < 1 || image.width > kMaxPlaneEdge || image.height > kMaxPlaneEdge) {
        throw core::ValueError("snapshot: size " + std::to_string(image.width) + "x" + std::to_string(image.height) +
                               " is outside 1.." + std::to_string(kMaxPlaneEdge));
    }
    const std::string key = core::Sha256Hex(core::json::WriteCanonical(signature));
    core::Project& project = edit.project();
    Value& member = project.extra[std::string(kSnapshotsKey)];
    if (member.IsNull()) member = Object{};
    if (!member.IsObject()) throw core::ValueError("snapshot: the project's procedural_snapshots is not an object");
    if (std::get<Object>(member.data).count(key) != 0) {
        throw core::ValueError("snapshot: the project already holds a snapshot with signature " + key +
                               "; a snapshot is immutable migration data");
    }

    const Id plane_id = edit.AllocateId();
    if (pending.planes.count(plane_id) != 0 || ReadPlaneRow(container, plane_id)) {
        throw StoreError(StoreError::Code::conflict, "plane id " + std::to_string(plane_id) +
                                                         " is already a stored plane (the project counter went back)");
    }
    PlaneRow row;  // no texture set, stack, channel or UV tile: the project's own raster
    row.plane_id = plane_id;
    row.format = image.format;
    row.width = image.width;
    row.height = image.height;
    const VersionRef ref = StageVersion(container, pending, row, image);
    pending.planes[plane_id] = row;
    std::get<Object>(member.data)[key] = Object{
        {"signature", signature},
        {"project_uuid", std::string(project_uuid)},
        {"plane", static_cast<std::int64_t>(plane_id)},
        {std::string(kPlaneVersionsKey), Object{{std::to_string(plane_id), ref.ToJson()}}},
    };
    return plane_id;
}

}  // namespace uzp::store
