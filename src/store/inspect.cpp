#include "store/inspect.h"

#include <windows.h>

#include <atomic>
#include <set>
#include <utility>

#include "store/blobs.h"
#include "store/commit.h"
#include "store/integrity.h"
#include "store/planes.h"
#include "store/save.h"
#include "store/versioning.h"
#include "uzp_core/manifest/manifest.h"
#include "uzp_core/manifest/sha256.h"

namespace uzp::store {

using core::json::Array;
using core::json::Object;
using core::json::Value;

namespace {

std::string Utf8(const std::filesystem::path& path) {
    const std::u8string text = path.u8string();
    return std::string(text.begin(), text.end());
}

const Value* Member(const Value& value, std::string_view key) {
    const auto* object = std::get_if<Object>(&value.data);
    if (object == nullptr) return nullptr;
    const auto it = object->find(key);
    return it == object->end() ? nullptr : &it->second;
}

Value Get(const Value& value, std::string_view key) {
    const Value* member = Member(value, key);
    return member ? *member : Value();
}

const Array& Items(const Value* value) {
    static const Array empty;
    const auto* array = value ? std::get_if<Array>(&value->data) : nullptr;
    return array ? *array : empty;
}

Value Optional(const std::optional<std::string>& text) { return text ? Value(*text) : Value(); }

/// One `SELECT COUNT(*), SUM(a), SUM(b) ...` row as `{count, <a>, <b>}`.
Object Totals(Container& container, const std::string& sql, const char* first, const char* second) {
    Statement q(container, sql);
    Object out{{"count", std::int64_t{0}}};
    if (first) out[first] = std::int64_t{0};
    if (second) out[second] = std::int64_t{0};
    if (q.Step()) {
        out["count"] = q.Int(0);
        if (first) out[first] = q.Int(1);
        if (second) out[second] = q.Int(2);
    }
    return out;
}

// ── The layer tree ─────────────────────────────────────────────────────────────────────────

constexpr std::string_view kNestedKeys[] = {"children", "content_effects", "mask", "effects"};

bool Nested(std::string_view key) {
    for (std::string_view nested : kNestedKeys) {
        if (key == nested) return true;
    }
    return false;
}

/// Every resource hash a node's own payload names (not its children, effects or mask).
void ResourceBindings(const Value& value, const std::string& path, const std::set<std::string, std::less<>>& resources,
                      Array& out) {
    if (const auto* text = std::get_if<std::string>(&value.data)) {
        if (resources.count(*text) != 0) out.push_back(Object{{"path", path}, {"sha256", *text}});
    } else if (const auto* array = std::get_if<Array>(&value.data)) {
        for (std::size_t i = 0; i < array->size(); ++i) {
            ResourceBindings((*array)[i], path + "[" + std::to_string(i) + "]", resources, out);
        }
    } else if (const auto* object = std::get_if<Object>(&value.data)) {
        for (const auto& [key, member] : *object) {
            if (path.empty() && Nested(key)) continue;
            ResourceBindings(member, path.empty() ? key : path + "." + key, resources, out);
        }
    }
}

/// The planes a node's `paint` object holds, with their bound version and stored row.
Array PlaneBindings(Container& container, const Value& node) {
    Array out;
    const Value* paint = Member(node, "paint");
    if (paint == nullptr || !paint->IsObject()) return out;
    std::vector<std::pair<Value, Value>> held;  // (channel or null, plane_id)
    if (const Value* planes = Member(*paint, "planes"); planes && planes->IsObject()) {
        for (const auto& [channel, id] : std::get<Object>(planes->data)) held.emplace_back(Value(channel), id);
    }
    if (const Value* plane = Member(*paint, "plane"); plane && plane->IsInt()) held.emplace_back(Value(), *plane);
    const Value* versions = Member(*paint, kPlaneVersionsKey);
    for (const auto& [channel, id] : held) {
        Object row{{"channel", channel}, {"plane_id", id}};
        if (id.IsInt()) {
            const Value binding = versions ? Get(*versions, std::to_string(std::get<std::int64_t>(id.data))) : Value();
            row["version_id"] = Get(binding, "version_id");
            row["chunk_root"] = Get(binding, "chunk_root");
            if (const std::optional<PlaneRow> stored = ReadPlaneRow(container, static_cast<core::Id>(std::get<std::int64_t>(id.data)))) {
                row["format"] = std::string(core::ToString(stored->format));
                row["width"] = std::int64_t{stored->width};
                row["height"] = std::int64_t{stored->height};
                row["udim"] = std::int64_t{1001 + stored->tile_u + 10 * stored->tile_v};
            }
        }
        out.push_back(std::move(row));
    }
    return out;
}

Value Node(Container& container, const Value& node, const std::set<std::string, std::less<>>& resources);

Array Nodes(Container& container, const Value* list, const std::set<std::string, std::less<>>& resources) {
    Array out;
    for (const Value& node : Items(list)) out.push_back(Node(container, node, resources));
    return out;
}

Value Node(Container& container, const Value& node, const std::set<std::string, std::less<>>& resources) {
    Object out;
    for (const char* key : {"uid", "kind", "name", "visible"}) out[key] = Get(node, key);
    if (const Value* blending = Member(node, "blending")) out["blending"] = *blending;
    if (const Value* blending = Member(node, "mono_blending")) out["mono_blending"] = *blending;
    if (const Value* source = Member(node, "instance_source")) out["instance_source"] = *source;
    Array bound;
    ResourceBindings(node, "", resources, bound);
    out["bindings"] = Object{{"planes", PlaneBindings(container, node)}, {"resources", std::move(bound)}};
    if (Member(node, "content_effects")) out["content_effects"] = Nodes(container, Member(node, "content_effects"), resources);
    if (const Value* mask = Member(node, "mask")) {
        out["mask"] = mask->IsObject() ? Value(Object{{"enabled", Get(*mask, "enabled")},
                                                      {"effects", Nodes(container, Member(*mask, "effects"), resources)}})
                                       : Value();
    }
    if (Member(node, "children")) out["children"] = Nodes(container, Member(node, "children"), resources);
    return out;
}

Array TextureSets(Container& container, const Value& manifest, const std::set<std::string, std::less<>>& resources) {
    Array out;
    for (const Value& set : Items(Member(manifest, "texture_sets"))) {
        Object row;
        for (const char* key : {"id", "name", "original_name", "material_id", "description", "resolution"}) {
            row[key] = Get(set, key);
        }
        Array tiles;
        for (const Value& tile : Items(Member(set, "uv_tiles"))) tiles.push_back(Get(tile, "udim"));
        row["uv_tiles"] = std::move(tiles);
        Array stacks;
        for (const Value& stack : Items(Member(set, "stacks"))) {
            stacks.push_back(Object{{"id", Get(stack, "id")},
                                    {"name", Get(stack, "name")},
                                    {"channels", Get(stack, "channels")},
                                    {"layers", Nodes(container, Member(stack, "root_layers"), resources)}});
        }
        row["stacks"] = std::move(stacks);
        Array maps;
        if (const Value* mesh_maps = Member(set, "mesh_maps"); mesh_maps && mesh_maps->IsObject()) {
            for (const auto& [usage, map] : std::get<Object>(mesh_maps->data)) {
                Object entry{{"usage", usage}};
                for (const char* key : {"resource", "format", "color_space", "invalid", "invalid_report", "provenance"}) {
                    entry[key] = Get(map, key);
                }
                maps.push_back(std::move(entry));
            }
        }
        row["mesh_maps"] = std::move(maps);
        out.push_back(std::move(row));
    }
    return out;
}

Array Resources(Container& container, const Value& manifest) {
    Array out;
    const Value* resources = Member(manifest, "resources");
    if (resources == nullptr || !resources->IsObject()) return out;
    for (const auto& [sha256, entries] : std::get<Object>(resources->data)) {
        Statement q(container, "SELECT mime, size, zstd_size FROM blob WHERE sha256 = ?");
        q.Bind(1, sha256);
        const bool embedded = q.Step();
        const bool located = !embedded && FindLocator(container, sha256).has_value();
        for (const Value& entry : Items(&entries)) {
            Object row{{"sha256", sha256}};
            for (const char* key : {"name", "usage", "color_space", "origin", "imported_at"}) row[key] = Get(entry, key);
            row["mime"] = embedded ? Value(q.Text(0)) : Get(entry, "mime");
            row["bytes"] = embedded ? Value(q.Int(1)) : Get(entry, "size");
            row["stored_bytes"] = embedded ? Value(q.Int(2)) : Value(std::int64_t{0});
            row["storage"] = embedded ? "embedded" : located ? "locator" : "missing";
            out.push_back(std::move(row));
        }
    }
    return out;
}

Object ExternalDependencies(Container& container) {
    std::int64_t count = 0, bytes = 0, missing = 0;
    Statement q(container, "SELECT path FROM locator ORDER BY sha256");
    while (q.Step()) {
        ++count;
        const std::string path = q.Text(0);
        std::error_code ec;
        const std::uintmax_t size = std::filesystem::file_size(std::filesystem::path(std::u8string(path.begin(), path.end())), ec);
        if (ec) {
            ++missing;
        } else {
            bytes += static_cast<std::int64_t>(size);
        }
    }
    return Object{{"bytes", bytes}, {"count", count}, {"missing", missing}};
}

Value Report(Container& container, const std::filesystem::path& project, const InspectOptions& options) {
    if (!container.HasTable("meta")) {
        throw StoreError(StoreError::Code::not_a_project, Utf8(project) + " has no meta table: not a .uzp project");
    }
    const std::optional<std::string> version_text = container.Meta("format_version");
    const std::optional<std::string> uuid = container.Meta("project_uuid");
    if (!version_text || !uuid) {
        throw StoreError(StoreError::Code::not_a_project, Utf8(project) + " has no format_version or project_uuid");
    }
    CheckReadable(FormatVersion::Parse(*version_text), VersionPolicy::Current());

    const std::int64_t current = ReadCurrentRevision(container);
    const std::int64_t revision = options.revision.value_or(current);
    const std::string text = ReadManifestText(container, revision);
    Value manifest;
    try {
        manifest = core::json::Parse(text);
    } catch (const core::json::ParseError& error) {
        throw CorruptionError(CorruptItem{"manifest", std::to_string(revision), error.what(), {}});
    }

    Object report;
    report["file"] = Utf8(project);
    report["project"] = Object{{"uuid", *uuid},
                               {"portable", container.Meta("portable").value_or("1") != "0"},
                               {"created", Optional(container.Meta("created"))},
                               {"operation_horizon_revision", ReadHorizon(container)}};
    {
        Statement q(container, "SELECT parent, created_at, kind, name, manifest_sha256 FROM revision WHERE revision = ?");
        q.Bind(1, revision);
        q.Step();  // ReadManifestText found the row
        report["revision"] = Object{{"number", revision},
                                    {"current", current},
                                    {"parent", q.IsNull(0) ? Value() : Value(q.Int(0))},
                                    {"created_at", q.Text(1)},
                                    {"kind", q.Text(2)},
                                    {"name", q.IsNull(3) ? Value() : Value(q.Text(3))},
                                    {"manifest_sha256", q.Text(4)}};
    }
    {
        Statement q(container, "SELECT COUNT(*), MIN(revision), MAX(revision) FROM revision");
        q.Step();
        report["revisions"] = Object{{"count", q.Int(0)}, {"first", q.Int(1)}, {"last", q.Int(2)}};
    }
    const Value versions = Get(manifest, "versions");
    report["versions"] = Object{{"format_version", Get(versions, "format_version")},
                                {"file_format_version", *version_text},
                                {"app_version", Get(versions, "app_version")},
                                {"painter_reference", Get(versions, "painter_reference")}};
    report["profiles"] = Object{{"evaluator_profile", Get(versions, "evaluator_profile")},
                                {"compat_profile", Get(versions, "compat_profile")}};
    report["settings"] = Get(manifest, "settings");
    report["mesh"] = Get(manifest, "mesh");

    std::set<std::string, std::less<>> resource_keys;
    if (const Value* resources = Member(manifest, "resources"); resources && resources->IsObject()) {
        for (const auto& [sha256, entries] : std::get<Object>(resources->data)) resource_keys.insert(sha256);
    }
    report["texture_sets"] = TextureSets(container, manifest, resource_keys);
    report["resources"] = Resources(container, manifest);

    Array checkpoints;
    for (const CheckpointRow& row : ReadCheckpoints(container)) {
        checkpoints.push_back(Object{{"name", row.name},
                                     {"revision", row.revision},
                                     {"created_at", row.created_at},
                                     {"note", row.note},
                                     {"protected", row.is_protected}});
    }
    report["checkpoints"] = std::move(checkpoints);

    std::error_code ec;
    const std::uintmax_t file_bytes = std::filesystem::file_size(project, ec);
    const std::string chunk_mime(kChunkMime);
    report["sizes"] = Object{
        {"file_bytes", ec ? Value() : Value(static_cast<std::int64_t>(file_bytes))},
        {"manifests", Totals(container, "SELECT COUNT(*), COALESCE(SUM(LENGTH(manifest)), 0) FROM revision", "stored_bytes", nullptr)},
        {"resources", Totals(container,
                             "SELECT COUNT(*), COALESCE(SUM(size), 0), COALESCE(SUM(zstd_size), 0) FROM blob WHERE mime IS NOT '" +
                                 chunk_mime + "'",
                             "bytes", "stored_bytes")},
        {"plane_chunks", Totals(container,
                                "SELECT COUNT(*), COALESCE(SUM(size), 0), COALESCE(SUM(zstd_size), 0) FROM blob WHERE mime IS '" +
                                    chunk_mime + "'",
                                "bytes", "stored_bytes")},
        {"operations", Totals(container, "SELECT COUNT(*), COALESCE(SUM(LENGTH(outcome)), 0) FROM operation", "stored_bytes", nullptr)},
        {"cache", Totals(container,
                         "SELECT COUNT(*), COALESCE(SUM(b.zstd_size), 0) FROM cache c LEFT JOIN blob b ON b.sha256 = c.sha256",
                         "stored_bytes", nullptr)},
        {"external_dependencies", ExternalDependencies(container)},
    };
    if (options.recipe == nullptr) {
        report["recipe_digest"] = Object{{"available", false}, {"reason", std::string(kRecipeHostMissing)}};
    } else {
        try {
            const Object dump = core::DumpRecipe(core::LoadManifest(text), revision, *options.recipe);
            report["recipe_digest"] = Object{{"available", true}, {"digest", dump.at("digest")}};
        } catch (const std::exception& error) {
            report["recipe_digest"] = Object{{"available", false}, {"reason", std::string(error.what())}};
        }
    }

    if (options.verify) {
        const Value current_manifest = revision == current ? manifest : core::json::Parse(ReadManifestText(container, current));
        const IntegrityReport integrity = CheckIntegrity(container, current_manifest, VerifyLevel::full);
        Value verify = integrity.ToJson();
        std::get<Object>(verify.data)["ok"] = integrity.ok();
        report["verify"] = std::move(verify);
    }
    return report;
}

void Indent(const Value& value, int depth, std::string& out) {
    const std::string pad(static_cast<std::size_t>(depth + 1) * 2, ' ');
    if (const auto* array = std::get_if<Array>(&value.data); array && !array->empty()) {
        out += "[\n";
        for (std::size_t i = 0; i < array->size(); ++i) {
            out += pad;
            Indent((*array)[i], depth + 1, out);
            out += i + 1 < array->size() ? ",\n" : "\n";
        }
        out += std::string(static_cast<std::size_t>(depth) * 2, ' ') + "]";
    } else if (const auto* object = std::get_if<Object>(&value.data); object && !object->empty()) {
        out += "{\n";
        std::size_t i = 0;
        for (const auto& [key, member] : *object) {
            out += pad + core::json::WriteCanonical(Value(key)) + ": ";
            Indent(member, depth + 1, out);
            out += ++i < object->size() ? ",\n" : "\n";
        }
        out += std::string(static_cast<std::size_t>(depth) * 2, ' ') + "}";
    } else {
        out += core::json::WriteCanonical(value);
    }
}

}  // namespace

Value Inspect(const std::filesystem::path& project, const InspectOptions& options) {
    if (options.verify) {
        ReadSnapshot snapshot(project);
        return Report(snapshot.container(), project, options);
    }
    Container container = Container::OpenReadOnly(project);
    container.Exec("BEGIN");  // one consistent read; a read-only connection never writes
    Value report = Report(container, project, options);
    container.Exec("COMMIT");
    return report;
}

Object InspectRecipe(const std::filesystem::path& project, std::optional<std::int64_t> revision,
                     const core::RecipeHost& host) {
    Container container = Container::OpenReadOnly(project);
    container.Exec("BEGIN");  // one consistent read; a read-only connection never writes
    const std::optional<std::string> version_text = container.Meta("format_version");
    if (!container.HasTable("meta") || !version_text) {
        throw StoreError(StoreError::Code::not_a_project, Utf8(project) + " is not a .uzp project");
    }
    CheckReadable(FormatVersion::Parse(*version_text), VersionPolicy::Current());
    const std::int64_t number = revision.value_or(ReadCurrentRevision(container));
    Object dump = core::DumpRecipe(core::LoadManifest(ReadManifestText(container, number)), number, host);
    container.Exec("COMMIT");
    return dump;
}

std::string WriteIndented(const Value& value) {
    std::string out;
    Indent(value, 0, out);
    out += "\n";
    return out;
}

ReadSnapshot::ReadSnapshot(const std::filesystem::path& project) {
    static std::atomic<unsigned> counter{0};
    copy_ = std::filesystem::temp_directory_path() /
            ("uzp-snapshot-" + std::to_string(GetCurrentProcessId()) + "-" + std::to_string(counter++) + ".uzp");
    std::error_code ec;
    std::filesystem::remove(copy_, ec);
    try {
        Container source = Container::OpenReadOnly(project);
        Container::Snapshot(source, copy_);
        container_.emplace(Container::OpenReadOnly(copy_));
    } catch (...) {
        container_.reset();
        std::filesystem::remove(copy_, ec);
        throw;
    }
}

ReadSnapshot::~ReadSnapshot() {
    container_.reset();
    std::error_code ec;
    std::filesystem::remove(copy_, ec);
}

}  // namespace uzp::store
