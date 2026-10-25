#include "store/snapshots.h"

#include "uzp_core/manifest/sha256.h"
#include "uzp_core/types/errors.h"

#include <algorithm>
#include <array>
#include <cmath>

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

namespace {

core::json::Array Strings(const std::vector<std::string>& values) {
    core::json::Array array;
    for (const std::string& value : values) array.push_back(value);
    return array;
}

/// A `source_metadata` member that must be an array of distinct nonempty strings.
std::expected<std::vector<std::string>, std::string> DistinctNames(const Value& value, std::string_view member,
                                                                   bool nonempty) {
    using Result = std::expected<std::vector<std::string>, std::string>;
    const std::string what = "source_metadata " + std::string(member);
    const auto* array = std::get_if<core::json::Array>(&value.data);
    if (array == nullptr || (nonempty && array->empty())) {
        return Result(std::unexpect, what + (nonempty ? " must be a nonempty array" : " must be an array"));
    }
    std::vector<std::string> names;
    for (const Value& item : *array) {
        if (!item.IsString() || std::get<std::string>(item.data).empty()) {
            return Result(std::unexpect, what + " must hold nonempty strings");
        }
        const std::string& name = std::get<std::string>(item.data);
        if (std::find(names.begin(), names.end(), name) != names.end()) {
            return Result(std::unexpect, what + " repeats " + name);
        }
        names.push_back(name);
    }
    return names;
}

/// Why `description` is not one `properties.Property` as the snapshot bridge serializes it
/// (python/uzpainter_snapshot/painter_side.py `described`): exactly the documented getters
/// `value`, `name`, `short_name`, `label`, `widget_type` (one of the documented widget types),
/// `enum_values` (label -> integer) and `properties` (an object), with `name` equal to its key.
std::string PropertyProblem(const std::string& key, const Value& description) {
    static constexpr std::array<std::string_view, 7> kFields = {
        "value", "name", "short_name", "label", "widget_type", "enum_values", "properties"};
    // python-doc `Property.widget_type() -> str`, "One of:".
    static constexpr std::array<std::string_view, 11> kWidgets = {
        "Slider", "Angle", "Color", "Togglebutton", "Combobox", "RandomSeed",
        "File", "FileList", "LineEdit", "Resource", "TextEdit"};
    const auto* object = std::get_if<Object>(&description.data);
    if (key.empty() || object == nullptr || object->size() != kFields.size() ||
        !std::all_of(kFields.begin(), kFields.end(), [&](std::string_view f) { return object->contains(std::string(f)); })) {
        return "a property is an object of exactly value, name, short_name, label, widget_type, enum_values and properties";
    }
    const auto text = [&](std::string_view field) { return object->at(std::string(field)).IsString(); };
    if (!text("name") || std::get<std::string>(object->at("name").data) != key) return "name must equal its key";
    if (!text("short_name") || !text("label")) return "short_name and label must be strings";
    if (!text("widget_type") ||
        std::find(kWidgets.begin(), kWidgets.end(), std::get<std::string>(object->at("widget_type").data)) ==
            kWidgets.end()) {
        return "widget_type must be a documented widget type";
    }
    const auto* labels = std::get_if<Object>(&object->at("enum_values").data);
    if (labels == nullptr ||
        !std::all_of(labels->begin(), labels->end(), [](const auto& entry) { return entry.second.IsInt(); })) {
        return "enum_values must map labels to integers";
    }
    if (!object->at("properties").IsObject()) return "properties must be an object";
    // No typed codec exists for vectors, colours or other values yet: only finite scalars are kept.
    const Value& value = object->at("value");
    const bool finite = value.IsInt() || value.IsString() ||
                        (value.IsDouble() && std::isfinite(std::get<double>(value.data)));
    if (!finite) return "value must be a finite integer, number or string";
    return {};
}

/// Why `typed` is not the typed parameter map of a snapshot of `signature` (decision 361): an
/// object whose keys are exactly the signature's `params` and whose int64, finite double or
/// string values equal them by value. The raw values are kept; nothing is converted.
std::string TypedParametersProblem(const Value& signature, const Value& typed) {
    const auto* map = std::get_if<Object>(&typed.data);
    if (map == nullptr) return "typed_effective_parameters must be an object";
    const auto* object = std::get_if<Object>(&signature.data);
    const auto params = object ? object->find("params") : Object::const_iterator{};
    const auto* expected = object && params != object->end() ? std::get_if<Object>(&params->second.data) : nullptr;
    if (expected == nullptr) return "typed_effective_parameters needs a signature with params";
    if (map->size() != expected->size()) return "typed_effective_parameters keys must be exactly the signature's parameters";
    for (const auto& [name, value] : *map) {
        const auto it = expected->find(name);
        if (it == expected->end()) return "typed_effective_parameters keys must be exactly the signature's parameters";
        const std::optional<Value> byValue = ParamByValue(value);
        if (!byValue) return "typed_effective_parameters." + name + " must be an int64, finite double or string";
        if (core::json::WriteCanonical(*byValue) != core::json::WriteCanonical(it->second)) {
            return "typed_effective_parameters." + name + " is not the signature's value";
        }
    }
    return {};
}

/// `value` read as an observed ResourceID of the snapshot pinned as `pin`, or why not: exactly
/// four nonempty strings, and `pin` the snapshot asset of `url` (`uzasset://snapshot/<sha256>@1`).
std::expected<ObservedResourceId, std::string> ParseObservedResourceId(const Value& value, const std::string& pin) {
    using Result = std::expected<ObservedResourceId, std::string>;
    static constexpr std::array<std::string_view, 4> kParts = {"url", "context", "name", "version"};
    const auto* object = std::get_if<Object>(&value.data);
    const auto part = [&](std::string_view name) -> const std::string* {
        const auto it = object->find(name);
        return it != object->end() && it->second.IsString() && !std::get<std::string>(it->second.data).empty()
                   ? &std::get<std::string>(it->second.data)
                   : nullptr;
    };
    if (object == nullptr || object->size() != kParts.size() ||
        !std::all_of(kParts.begin(), kParts.end(), [&](std::string_view name) { return part(name) != nullptr; })) {
        return Result(std::unexpect, "observed_resource_id must be exactly the nonempty strings url, context, name and version");
    }
    ObservedResourceId id{*part("url"), *part("context"), *part("name"), *part("version")};
    if (pin != "uzasset://snapshot/" + core::Sha256Hex(id.url) + "@1") {
        return Result(std::unexpect, "observed_resource_id url is not the resource the snapshot pin " + pin + " names");
    }
    return id;
}

}  // namespace

std::optional<Value> ParamByValue(const Value& value) {
    if (value.IsInt() || value.IsString()) return value;
    if (!value.IsDouble()) return std::nullopt;
    const double number = std::get<double>(value.data);
    if (!std::isfinite(number)) return std::nullopt;
    // ParamJson: an integral double inside the int64 range is that integer. Both bounds are exact
    // doubles, so the comparison decides before the cast, which then cannot overflow.
    if (std::trunc(number) == number && number >= -9223372036854775808.0 && number < 9223372036854775808.0) {
        return Value(static_cast<std::int64_t>(number));
    }
    return value;
}

Value SourceMetadataJson(const Value& signature, const SourceMetadata& metadata) {
    const bool v3 = metadata.typed_effective_parameters || metadata.observed_resource_id;
    const bool v2 = metadata.image_inputs || metadata.presets || metadata.properties;
    const std::string_view schema = v3 ? kSourceMetadataSchemaV3 : v2 ? kSourceMetadataSchemaV2 : kSourceMetadataSchema;
    Object object{{"schema", std::string(schema)},
                  {"asset", PinAndOutput(signature).first},
                  {"image_outputs", Strings(metadata.image_outputs)}};
    if (metadata.image_inputs) object["image_inputs"] = Strings(*metadata.image_inputs);
    if (metadata.presets) object["presets"] = Strings(*metadata.presets);
    if (metadata.properties) object["properties"] = *metadata.properties;
    if (metadata.typed_effective_parameters) object["typed_effective_parameters"] = *metadata.typed_effective_parameters;
    if (const auto& id = metadata.observed_resource_id) {
        object["observed_resource_id"] =
            Object{{"url", id->url}, {"context", id->context}, {"name", id->name}, {"version", id->version}};
    }
    return object;
}

Value SourceMetadataJson(const Value& signature, const std::vector<std::string>& image_outputs) {
    return SourceMetadataJson(signature, SourceMetadata{image_outputs, std::nullopt, std::nullopt, std::nullopt, std::nullopt, std::nullopt});
}

std::expected<SourceMetadata, std::string> ParseSourceMetadata(const Value& signature, const Value& metadata) {
    using Result = std::expected<SourceMetadata, std::string>;
    const auto* object = std::get_if<Object>(&metadata.data);
    const Value* schema = object ? (object->contains("schema") ? &object->at("schema") : nullptr) : nullptr;
    const bool v1 = schema && schema->IsString() && std::get<std::string>(schema->data) == kSourceMetadataSchema;
    const bool v2 = schema && schema->IsString() && std::get<std::string>(schema->data) == kSourceMetadataSchemaV2;
    const bool v3 = schema && schema->IsString() && std::get<std::string>(schema->data) == kSourceMetadataSchemaV3;
    if (object == nullptr || !object->contains("asset") || !object->contains("image_outputs") || schema == nullptr) {
        return Result(std::unexpect, "source_metadata must be an object of schema, asset and image_outputs");
    }
    if (!v1 && !v2 && !v3) {
        return Result(std::unexpect, "source_metadata schema must be " + std::string(kSourceMetadataSchema) + ", " +
                                         std::string(kSourceMetadataSchemaV2) + " or " +
                                         std::string(kSourceMetadataSchemaV3));
    }
    for (const auto& [name, ignored] : *object) {
        const bool required = name == "schema" || name == "asset" || name == "image_outputs";
        const bool optional = name == "image_inputs" || name == "presets" || name == "properties";
        const bool observed = name == "typed_effective_parameters" || name == "observed_resource_id";
        if (!required && !((v2 || v3) && optional) && !(v3 && observed)) {
            return Result(std::unexpect, v1 ? "source_metadata must be an object of exactly schema, asset and image_outputs"
                                            : "source_metadata has the unknown member " + name);
        }
    }
    // One encoding per observation set: /3 exists only for its own members.
    if (v3 && !object->contains("typed_effective_parameters") && !object->contains("observed_resource_id")) {
        return Result(std::unexpect, "source_metadata /3 needs typed_effective_parameters or observed_resource_id");
    }
    const auto [pin, output] = PinAndOutput(signature);
    if (pin.empty() || output.empty()) {
        return Result(std::unexpect, "source_metadata needs a signature with asset, version and output id");
    }
    const Value& asset = object->at("asset");
    if (!asset.IsString() || std::get<std::string>(asset.data) != pin) {
        return Result(std::unexpect, "source_metadata asset must be the signature's exact pin " + pin);
    }
    SourceMetadata parsed;
    auto outputs = DistinctNames(object->at("image_outputs"), "image_outputs", true);
    if (!outputs) return Result(std::unexpect, outputs.error());
    parsed.image_outputs = std::move(*outputs);
    if (std::find(parsed.image_outputs.begin(), parsed.image_outputs.end(), output) == parsed.image_outputs.end()) {
        return Result(std::unexpect, "source_metadata image_outputs does not hold the signature's output " + output);
    }
    for (const auto& [member, target] : {std::pair{"image_inputs", &parsed.image_inputs}, std::pair{"presets", &parsed.presets}}) {
        if (!object->contains(member)) continue;
        auto names = DistinctNames(object->at(member), member, false);
        if (!names) return Result(std::unexpect, names.error());
        *target = std::move(*names);
    }
    if (object->contains("properties")) {
        const auto* properties = std::get_if<Object>(&object->at("properties").data);
        if (properties == nullptr) return Result(std::unexpect, "source_metadata properties must be an object");
        for (const auto& [name, description] : *properties) {
            const std::string problem = PropertyProblem(name, description);
            if (!problem.empty()) return Result(std::unexpect, "source_metadata properties." + name + ": " + problem);
        }
        parsed.properties = *properties;
    }
    if (const auto typed = object->find("typed_effective_parameters"); typed != object->end()) {
        const std::string problem = TypedParametersProblem(signature, typed->second);
        if (!problem.empty()) return Result(std::unexpect, "source_metadata " + problem);
        parsed.typed_effective_parameters = std::get<Object>(typed->second.data);
    }
    if (const auto id = object->find("observed_resource_id"); id != object->end()) {
        auto observed = ParseObservedResourceId(id->second, pin);
        if (!observed) return Result(std::unexpect, "source_metadata " + observed.error());
        parsed.observed_resource_id = std::move(*observed);
    }
    return parsed;
}

std::string SourceMetadataProblem(const Value& signature, const Value& metadata) {
    const auto parsed = ParseSourceMetadata(signature, metadata);
    return parsed ? std::string() : parsed.error();
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
                auto parsed = ParseSourceMetadata(entry.signature, *metadata);
                if (parsed) {
                    entry.source_metadata = std::move(*parsed);
                } else {
                    entry.error = parsed.error();
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
                 const std::optional<SourceMetadata>& observed) {
    if (!signature.IsObject()) throw core::ValueError("snapshot: the signature is not a JSON object");
    std::optional<Value> metadata;
    if (observed) {
        metadata = SourceMetadataJson(signature, *observed);
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
