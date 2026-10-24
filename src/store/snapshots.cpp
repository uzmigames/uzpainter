#include "store/snapshots.h"

#include "uzp_core/manifest/sha256.h"
#include "uzp_core/types/errors.h"

#include <algorithm>

namespace uzp::store {

using core::Id;
using core::json::Object;
using core::json::Value;

namespace {

/// The signature's `<asset>@<version>` pin and output id, or empty strings when it lacks them.
std::pair<std::string, std::string> PinAndOutput(const Value& signature) {
    const auto* object = std::get_if<Object>(&signature.data);
    if (object == nullptr) return {};
    const auto text = [](const Object& from, std::string_view name) -> std::string {
        const auto it = from.find(name);
        return it != from.end() && it->second.IsString() ? std::get<std::string>(it->second.data) : std::string();
    };
    const std::string asset = text(*object, "asset");
    const std::string version = text(*object, "version");
    const auto output = object->find("output");
    const auto* out = output == object->end() ? nullptr : std::get_if<Object>(&output->second.data);
    return {asset.empty() || version.empty() ? std::string() : asset + "@" + version,
            out ? text(*out, "id") : std::string()};
}

}  // namespace

Value SourceMetadataJson(const Value& signature, const std::vector<std::string>& image_outputs) {
    core::json::Array outputs;
    for (const std::string& output : image_outputs) outputs.push_back(output);
    return Object{{"schema", std::string(kSourceMetadataSchema)},
                  {"asset", PinAndOutput(signature).first},
                  {"image_outputs", std::move(outputs)}};
}

std::string SourceMetadataProblem(const Value& signature, const Value& metadata) {
    const auto* object = std::get_if<Object>(&metadata.data);
    if (object == nullptr || object->size() != 3 || !object->contains("schema") || !object->contains("asset") ||
        !object->contains("image_outputs")) {
        return "source_metadata must be an object of exactly schema, asset and image_outputs";
    }
    const Value& schema = object->at("schema");
    if (!schema.IsString() || std::get<std::string>(schema.data) != kSourceMetadataSchema) {
        return "source_metadata schema must be " + std::string(kSourceMetadataSchema);
    }
    const auto [pin, output] = PinAndOutput(signature);
    if (pin.empty() || output.empty()) return "source_metadata needs a signature with asset, version and output id";
    const Value& asset = object->at("asset");
    if (!asset.IsString() || std::get<std::string>(asset.data) != pin) {
        return "source_metadata asset must be the signature's exact pin " + pin;
    }
    const auto* outputs = std::get_if<core::json::Array>(&object->at("image_outputs").data);
    if (outputs == nullptr || outputs->empty()) return "source_metadata image_outputs must be a nonempty array";
    std::vector<std::string> seen;
    for (const Value& item : *outputs) {
        if (!item.IsString() || std::get<std::string>(item.data).empty()) {
            return "source_metadata image_outputs must hold nonempty strings";
        }
        const std::string& name = std::get<std::string>(item.data);
        if (std::find(seen.begin(), seen.end(), name) != seen.end()) {
            return "source_metadata image_outputs repeats " + name;
        }
        seen.push_back(name);
    }
    if (std::find(seen.begin(), seen.end(), output) == seen.end()) {
        return "source_metadata image_outputs does not hold the signature's output " + output;
    }
    return {};
}

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
            const Value* metadata = member_of(kSourceMetadataKey);
            if (entry.error.empty() && metadata != nullptr) {
                entry.error = SourceMetadataProblem(entry.signature, *metadata);
                if (entry.error.empty()) {
                    entry.image_outputs.emplace();
                    const Value& outputs = std::get<Object>(metadata->data).at("image_outputs");
                    for (const Value& item : std::get<core::json::Array>(outputs.data)) {
                        entry.image_outputs->push_back(std::get<std::string>(item.data));
                    }
                }
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
                 const Value& signature, const PlaneImage& image,
                 const std::optional<std::vector<std::string>>& image_outputs) {
    if (!signature.IsObject()) throw core::ValueError("snapshot: the signature is not a JSON object");
    std::optional<Value> metadata;
    if (image_outputs) {
        metadata = SourceMetadataJson(signature, *image_outputs);
        const std::string problem = SourceMetadataProblem(signature, *metadata);
        if (!problem.empty()) throw core::ValueError("snapshot: " + problem);
    }
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
    Object entry{
        {"signature", signature},
        {"project_uuid", std::string(project_uuid)},
        {"plane", static_cast<std::int64_t>(plane_id)},
        {std::string(kPlaneVersionsKey), Object{{std::to_string(plane_id), ref.ToJson()}}},
    };
    if (metadata) entry[std::string(kSourceMetadataKey)] = std::move(*metadata);
    std::get<Object>(member.data)[key] = std::move(entry);
    return plane_id;
}

}  // namespace uzp::store
