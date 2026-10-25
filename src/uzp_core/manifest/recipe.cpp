#include "uzp_core/manifest/recipe.h"

#include <algorithm>
#include <initializer_list>
#include <map>
#include <optional>
#include <stdexcept>
#include <type_traits>
#include <utility>
#include <variant>
#include <vector>

#include "uzp_core/manifest/manifest.h"
#include "uzp_core/manifest/object_reader.h"
#include "uzp_core/manifest/sha256.h"
#include "uzp_core/types/errors.h"
#include "uzp_core/types/receipt.h"
#include "uzp_core/types/resource_url.h"
#include "uzp_core/types/validation.h"

namespace uzp::core {

using namespace manifest_detail;

namespace {

/// The manifest key of a paint object's plane bindings (`src/store/planes.h`), the one unknown
/// key this version reads.
constexpr std::string_view kPlaneVersions = "plane_versions";

// ── Keys this version does not know ─────────────────────────────────────────────────────────

void Strip(Resolution& r) { r.extra.clear(); }
void Strip(ProceduralResolution& r) { std::visit([](auto& value) { value.extra.clear(); }, r); }
void Strip(Blending& b) { b.extra.clear(); }
void Strip(ChannelBlending& blending) {
    for (auto& [channel, b] : blending) Strip(b);
}
void Strip(ResourceBinding& b) { b.extra.clear(); }
void Strip(LevelsParams& levels) {
    levels.extra.clear();
    for (LevelsComponent& c : levels.components) c.extra.clear();
}
void Strip(ProceduralRef& ref) {
    ref.extra.clear();
    for (auto& [name, binding] : ref.image_inputs) Strip(binding);
    if (ref.resolution_override) Strip(*ref.resolution_override);
}
void Strip(Source& source) {
    std::visit(
        [](auto& s) {
            using T = std::decay_t<decltype(s)>;
            if constexpr (std::is_same_v<T, ProceduralSource>) {
                Strip(s.ref);
            } else {
                s.extra.clear();
                if constexpr (std::is_same_v<T, BitmapSource> || std::is_same_v<T, VectorSource> ||
                              std::is_same_v<T, FontSource>) {
                    Strip(s.resource);
                }
                if constexpr (std::is_same_v<T, ReferenceSource>) {
                    if (s.levels) Strip(*s.levels);
                }
            }
        },
        source.value);
}
void Strip(FillContent& fill) {
    fill.extra.clear();
    for (auto& [channel, source] : fill.sources) Strip(source);
    if (fill.mono_source) Strip(*fill.mono_source);
    if (fill.material_source) Strip(*fill.material_source);
    fill.projection.extra.clear();
    fill.projection.uv.extra.clear();
    fill.projection.uv.uv_transformation.extra.clear();
    fill.symmetry.extra.clear();
}
void Strip(PaintContent& paint) {
    // The plane bindings are read (store planes): the only unknown key kept.
    json::Object kept;
    if (const auto it = paint.extra.find(kPlaneVersions); it != paint.extra.end()) kept.emplace(it->first, it->second);
    paint.extra = std::move(kept);
}
void Strip(Effect& e) {
    e.extra.clear();
    Strip(e.blending);
    if (e.mono_blending) Strip(*e.mono_blending);
    if (e.fill) Strip(*e.fill);
    if (e.paint) Strip(*e.paint);
    if (e.procedural) Strip(*e.procedural);
    if (e.levels) Strip(*e.levels);
}
void Strip(Layer& layer) {
    layer.extra.clear();
    Strip(layer.blending);
    for (Effect& e : layer.content_effects) Strip(e);
    if (layer.mask) {
        layer.mask->extra.clear();
        Strip(layer.mask->blending);
        for (Effect& e : layer.mask->effects) Strip(e);
    }
    layer.geometry_mask.extra.clear();
    if (layer.fill) Strip(*layer.fill);
    if (layer.paint) Strip(*layer.paint);
    for (Layer& child : layer.children) Strip(child);
}
void Strip(MeshMapBinding& binding) {
    binding.extra.clear();
    std::visit(
        [](auto& p) {
            p.extra.clear();
            if constexpr (std::is_same_v<std::decay_t<decltype(p)>, BakedProvenance>) p.mesh_hashes.extra.clear();
        },
        binding.provenance);
}
void Strip(TextureSet& set) {
    set.extra.clear();
    Strip(set.resolution);
    for (UVTile& tile : set.uv_tiles) tile.extra.clear();
    for (auto& [usage, binding] : set.mesh_maps) Strip(binding);
    for (Stack& stack : set.stacks) {
        stack.extra.clear();
        for (auto& [type, channel] : stack.channels) channel.extra.clear();
        for (Layer& layer : stack.root_layers) Strip(layer);
    }
}

/// `project` without the keys this version does not know (`plane_versions` excepted).
Project Stripped(const Project& project) {
    Project p = project;
    p.extra.clear();
    p.settings.extra.clear();
    p.settings.color_management.extra.clear();
    Strip(p.settings.default_resolution);
    if (p.mesh) p.mesh->extra.clear();
    for (TextureSet& set : p.texture_sets) Strip(set);
    return p;
}

// ── JSON helpers ────────────────────────────────────────────────────────────────────────────

// Unchecked access to JSON this file wrote, or that a rebuild reads inside `Malformed` (a wrong
// type or missing key there is a `ManifestError`).
json::Object& Obj(json::Value& value) { return std::get<json::Object>(value.data); }
json::Array& Arr(json::Value& value) { return std::get<json::Array>(value.data); }

const json::Value& Need(const json::Object& object, std::string_view key, const std::string& path) {
    const auto it = object.find(key);
    if (it == object.end()) Fail(path, "missing key '" + std::string(key) + "'");
    return it->second;
}

json::Value& Need(json::Object& object, std::string_view key, const std::string& path) {
    const auto it = object.find(key);
    if (it == object.end()) Fail(path, "missing key '" + std::string(key) + "'");
    return it->second;
}

/// The nodes of one stack's JSON, depth first, with their pointer inside the texture set.
template <typename Visit>
void ForEachNode(json::Array& nodes, const std::string& pointer, Visit&& visit);

template <typename Visit>
void ForEachEffect(json::Array& effects, const std::string& pointer, Visit& visit) {
    for (std::size_t i = 0; i < effects.size(); ++i) visit(Obj(effects[i]), pointer + "/" + std::to_string(i), false);
}

template <typename Visit>
void ForEachNode(json::Array& nodes, const std::string& pointer, Visit&& visit) {
    for (std::size_t i = 0; i < nodes.size(); ++i) {
        const std::string here = pointer + "/" + std::to_string(i);
        json::Object& layer = Obj(nodes[i]);
        visit(layer, here, true);
        ForEachEffect(Arr(layer.at("content_effects")), here + "/content_effects", visit);
        if (json::Value& mask = layer.at("mask"); mask.IsObject()) {
            ForEachEffect(Arr(Obj(mask).at("effects")), here + "/mask/effects", visit);
        }
        if (const auto it = layer.find("children"); it != layer.end()) ForEachNode(Arr(it->second), here + "/children", visit);
    }
}

template <typename Visit>
void ForEachStackNode(json::Object& set, Visit&& visit) {
    json::Array& stacks = Arr(set.at("stacks"));
    for (std::size_t s = 0; s < stacks.size(); ++s) {
        ForEachNode(Arr(Obj(stacks[s]).at("root_layers")), "/stacks/" + std::to_string(s) + "/root_layers", visit);
    }
}

/// Every source object of a node: fill sources, the mask stack's source and the material source.
template <typename Visit>
void ForEachSource(json::Object& node, Visit&& visit) {
    const auto fill = node.find("fill");
    if (fill == node.end() || !fill->second.IsObject()) return;
    json::Object& f = Obj(fill->second);
    if (const auto it = f.find("sources"); it != f.end()) {
        for (auto& [channel, source] : Obj(it->second)) visit(Obj(source));
    }
    for (const char* key : {"source", "material_source"}) {
        if (const auto it = f.find(key); it != f.end() && it->second.IsObject()) visit(Obj(it->second));
    }
}

bool IsReference(const json::Object& source) {
    const auto type = source.find("type");
    return type != source.end() && type->second == json::Value(std::string(ToString(SourceKind::reference)));
}

/// The content of plane `id` of a paint object: `{chunk_root}` of the bound version, null when no
/// version is bound.
json::Value PlaneContent(const json::Object& paint, const json::Value& id) {
    json::Value root = nullptr;
    const auto versions = paint.find(kPlaneVersions);
    if (versions != paint.end() && versions->second.IsObject()) {
        const json::Object& bindings = std::get<json::Object>(versions->second.data);
        const auto binding = bindings.find(std::to_string(std::get<std::int64_t>(id.data)));
        if (binding != bindings.end() && binding->second.IsObject()) {
            const json::Object& b = std::get<json::Object>(binding->second.data);
            if (const auto it = b.find("chunk_root"); it != b.end()) root = it->second;
        }
    }
    return json::Object{{"chunk_root", std::move(root)}};
}

std::array<double, 3> Widen(const std::array<float, 3>& v) {
    return {static_cast<double>(v[0]), static_cast<double>(v[1]), static_cast<double>(v[2])};
}

json::Value BaseJson(const std::array<float, 3>& base) {
    const std::array<double, 3> v = Widen(base);
    return json::Array{v[0], v[1], v[2]};
}

void CollectBinding(const ResourceBinding& binding, std::set<std::string>& out) { out.insert(binding.sha256); }

/// True when `value` holds, at any depth, an `asset` of the reserved observation family.
bool NamesObservation(const json::Value& value) {
    if (const auto* object = std::get_if<json::Object>(&value.data)) {
        for (const auto& [key, member] : *object) {
            if (key == "asset" && member.IsString() && IsObservationAsset(std::get<std::string>(member.data))) return true;
            if (NamesObservation(member)) return true;
        }
    } else if (const auto* array = std::get_if<json::Array>(&value.data)) {
        for (const json::Value& item : *array) {
            if (NamesObservation(item)) return true;
        }
    }
    return false;
}

void CollectProcedural(const ProceduralRef& ref, std::set<std::string>& out) {
    for (const auto& [name, binding] : ref.image_inputs) CollectBinding(binding, out);
}

void CollectSource(const Source& source, std::set<std::string>& out) {
    std::visit(
        [&](const auto& s) {
            using T = std::decay_t<decltype(s)>;
            if constexpr (std::is_same_v<T, BitmapSource> || std::is_same_v<T, VectorSource> || std::is_same_v<T, FontSource>) {
                CollectBinding(s.resource, out);
            } else if constexpr (std::is_same_v<T, ProceduralSource>) {
                CollectProcedural(s.ref, out);
            }
        },
        source.value);
}

void CollectFill(const FillContent& fill, std::set<std::string>& out) {
    for (const auto& [channel, source] : fill.sources) CollectSource(source, out);
    if (fill.mono_source) CollectSource(*fill.mono_source, out);
    if (fill.material_source) CollectSource(*fill.material_source, out);
}

void CollectEffect(const Effect& e, std::set<std::string>& out) {
    if (e.fill) CollectFill(*e.fill, out);
    if (e.procedural) CollectProcedural(*e.procedural, out);
}

void CollectLayer(const Layer& layer, std::set<std::string>& out) {
    if (layer.fill) CollectFill(*layer.fill, out);
    for (const Effect& e : layer.content_effects) CollectEffect(e, out);
    if (layer.mask) {
        for (const Effect& e : layer.mask->effects) CollectEffect(e, out);
    }
    for (const Layer& child : layer.children) CollectLayer(child, out);
}

/// Escapes one RFC 6901 token.
std::string Token(std::string_view key) {
    std::string out;
    for (const char c : key) {
        if (c == '~') out += "~0";
        else if (c == '/') out += "~1";
        else out += c;
    }
    return out;
}

std::string Pointer(const std::vector<std::string>& path) {
    std::string out;
    for (const std::string& key : path) out += "/" + Token(key);
    return out;
}

/// The tokens of an RFC 6901 pointer; `ManifestError` when it is not one.
std::vector<std::string> Tokens(const std::string& pointer, const std::string& where) {
    if (pointer.empty() || pointer.front() != '/') Fail(where, "'" + pointer + "' is not a JSON pointer");
    std::vector<std::string> out;
    std::string current;
    for (std::size_t i = 1; i <= pointer.size(); ++i) {
        if (i == pointer.size() || pointer[i] == '/') {
            out.push_back(std::move(current));
            current.clear();
        } else if (pointer[i] == '~') {
            if (i + 1 >= pointer.size() || (pointer[i + 1] != '0' && pointer[i + 1] != '1')) {
                Fail(where, "'" + pointer + "' holds a bad escape");
            }
            current += pointer[++i] == '0' ? '~' : '/';
        } else {
            current += pointer[i];
        }
    }
    return out;
}

bool In(std::string_view key, std::initializer_list<std::string_view> keys) {
    return std::find(keys.begin(), keys.end(), key) != keys.end();
}

/// True for a key of the id-less document that only a rebuild needs: state no evaluation,
/// export or mesh derivation reads (decision 122). Its value goes to the dump's `rebuild` block,
/// outside the digest; every other key is the recipe body.
bool RebuildOnly(const std::vector<std::string>& p) {
    const std::size_t n = p.size();
    if (n == 1) return In(p[0], {"display", "export_defaults", "metadata", "painter_reference", "resource_catalog"});
    if (p[0] == "mesh") return n == 2 && p[1] == "source";
    if (p[0] == "settings") return n == 2 && In(p[1], {"default_resolution", "mesh_unit_scale", "import_cameras", "auto_unwrap"});
    if (p[0] != "texture_sets" || n < 3) return false;
    if (n == 3) return In(p[2], {"description", "bake_settings"});
    if (p[2] == "mesh_maps") {
        return (n == 5 && p[4] == "invalid_report") ||
               (n == 6 && p[4] == "provenance" && !In(p[5], {"kind", "declared_convention"}));
    }
    if (p[2] == "stacks" && n == 7 && p[4] == "channels") return p[6] == "label";
    return p[2] == "stacks" && n >= 7 && p[4] == "root_layers" && In(p.back(), {"collapsed", "preset_ref"});
}

/// Moves every rebuild-only key of `value` (at `path`) into `patches`, keyed by its pointer.
void Partition(json::Value& value, std::vector<std::string>& path, json::Object& patches) {
    if (value.IsObject()) {
        json::Object& object = Obj(value);
        for (auto it = object.begin(); it != object.end();) {
            path.push_back(it->first);
            if (RebuildOnly(path)) {
                patches[Pointer(path)] = std::move(it->second);
                it = object.erase(it);
            } else {
                Partition(it->second, path, patches);
                ++it;
            }
            path.pop_back();
        }
    } else if (value.IsArray()) {
        json::Array& array = Arr(value);
        for (std::size_t i = 0; i < array.size(); ++i) {
            path.push_back(std::to_string(i));
            Partition(array[i], path, patches);
            path.pop_back();
        }
    }
}

/// The id-less document of `project`: its manifest without ids, `next_id`, `versions` (but for
/// `evaluator_profile` and `painter_reference`) and unknown keys; references as pointers, planes
/// as content, base values on the channels, `resources` the referenced hashes `{mime, size}` and
/// `resource_catalog` every stored entry without its id.
json::Object Document(const Project& project, const BaseValueFn& base_value) {
    // Decision 362: Filter source observations are project-private provenance that a recipe would
    // silently drop (Stripped), leaving reserved pins without them; such a project has no recipe.
    if (project.extra.contains(kFilterObservationsKey) || NamesObservation(ProjectToJson(project))) {
        throw ValueError("recipe: a project holding Filter source observations or a reserved observation "
                         "reference has no recipe (decision 362)");
    }
    json::Value manifest = ProjectToJson(Stripped(project));
    json::Object& m = Obj(manifest);
    json::Object doc;
    doc["evaluator_profile"] = project.versions.evaluator_profile;
    doc["painter_reference"] = std::move(Obj(m.at("versions")).at("painter_reference"));
    json::Object settings = std::move(Obj(m.at("settings")));
    settings["template"] = project.settings.template_id;
    doc["settings"] = std::move(settings);
    doc["mesh"] = std::move(m.at("mesh"));
    for (const char* key : {"display", "export_defaults", "metadata"}) doc[key] = std::move(m.at(key));

    for (json::Value& set_value : Arr(m.at("texture_sets"))) {
        json::Object& set = Obj(set_value);
        set.erase("id");
        for (json::Value& tile : Arr(set.at("uv_tiles"))) Obj(tile).erase("id");
        for (json::Value& stack_value : Arr(set.at("stacks"))) {
            json::Object& stack = Obj(stack_value);
            stack.erase("id");
            for (auto& [type, channel] : Obj(stack.at("channels"))) {
                const ChannelFormat format = *FromString<ChannelFormat>(std::get<std::string>(Obj(channel).at("format").data));
                Obj(channel)["base"] =
                    BaseJson(base_value(project.settings.template_id, *FromString<ChannelType>(type), format,
                                        &project.settings.color_management));
            }
        }
        std::map<std::int64_t, std::string> pointers;
        ForEachStackNode(set, [&](json::Object& node, const std::string& pointer, bool) {
            pointers[std::get<std::int64_t>(node.at("uid").data)] = pointer;
        });
        const auto pointer_of = [&](const json::Value& uid, const std::string& what) {
            const auto it = pointers.find(std::get<std::int64_t>(uid.data));
            if (it == pointers.end()) {
                throw ValueError("recipe: " + what + " names node " + std::to_string(std::get<std::int64_t>(uid.data)) +
                                 ", which is not in its texture set");
            }
            return json::Value(it->second);
        };
        ForEachStackNode(set, [&](json::Object& node, const std::string& pointer, bool is_layer) {
            ForEachSource(node, [&](json::Object& source) {
                if (IsReference(source)) source["anchor"] = pointer_of(source.at("anchor"), pointer + " (reference source)");
            });
            if (const auto it = node.find("instance_source"); is_layer && it != node.end()) {
                it->second = pointer_of(it->second, pointer + " (instance)");
            }
            if (const auto it = node.find("paint"); it != node.end() && it->second.IsObject()) {
                json::Object& paint = Obj(it->second);
                if (const auto planes = paint.find("planes"); planes != paint.end()) {
                    for (auto& [channel, id] : Obj(planes->second)) id = PlaneContent(paint, id);
                }
                if (const auto plane = paint.find("plane"); plane != paint.end() && !plane->second.IsNull()) {
                    plane->second = PlaneContent(paint, plane->second);
                }
                paint.erase(std::string(kPlaneVersions));
            }
            node.erase("uid");
        });
    }
    doc["texture_sets"] = std::move(m.at("texture_sets"));

    json::Object resources;
    for (const std::string& hash : RecipeResourceHashes(project)) {
        const auto it = project.resources.find(hash);
        if (it == project.resources.end() || it->second.empty()) {
            throw ValueError("recipe: resource " + hash + " is referenced but not stored");
        }
        // Every entry of one hash holds the same bytes: the smallest mime keeps the body
        // independent of the entries' order and names.
        std::string mime = it->second.front().mime;
        for (const ResourceMeta& meta : it->second) mime = std::min(mime, meta.mime);
        resources[hash] = json::Object{{"mime", mime}, {"size", it->second.front().size}};
    }
    doc["resources"] = std::move(resources);
    json::Object catalog = std::move(Obj(m.at("resources")));
    for (auto& [hash, entries] : catalog) {
        for (json::Value& entry : Arr(entries)) Obj(entry).erase("id");
    }
    doc["resource_catalog"] = std::move(catalog);
    return doc;
}

struct Split {
    json::Object body;
    json::Object rebuild;
};

Split SplitDocument(const Project& project, const BaseValueFn& base_value) {
    json::Value doc = Document(project, base_value);
    Split out;
    std::vector<std::string> path;
    Partition(doc, path, out.rebuild);
    out.body = std::move(Obj(doc));
    return out;
}

}  // namespace

std::set<std::string> MeshResourceHashes(const Project& project) {
    std::set<std::string> out;
    if (!project.mesh) return out;
    out.insert(project.mesh->resource);
    // The files beside the mesh it reads (a glTF's external buffers), stored at import.
    if (const auto files = project.mesh->import_report.find(kMeshExternalFiles); files != project.mesh->import_report.end()) {
        for (const json::Value& file : AsArray(files->second, "mesh.import_report.external_files")) {
            out.insert(AsString(Need(AsObject(file, "mesh.import_report.external_files[]"), "sha256",
                                     "mesh.import_report.external_files[]"),
                                "mesh.import_report.external_files[].sha256"));
        }
    }
    return out;
}

std::set<std::string> RecipeResourceHashes(const Project& project) {
    std::set<std::string> out = MeshResourceHashes(project);
    for (const TextureSet& set : project.texture_sets) {
        for (const auto& [usage, binding] : set.mesh_maps) out.insert(binding.resource);
        for (const Stack& stack : set.stacks) {
            for (const Layer& layer : stack.root_layers) CollectLayer(layer, out);
        }
    }
    return out;
}

json::Object RecipeBody(const Project& project, const BaseValueFn& base_value) {
    return SplitDocument(project, base_value).body;
}

std::string RecipeDigest(const json::Object& body) { return Sha256Hex(json::WriteCanonical(json::Value(body))); }

json::Object DumpRecipe(const Project& project, std::int64_t revision, const RecipeHost& host) {
    Split split = SplitDocument(project, host.base_value);
    json::Array hashes;
    for (const auto& [hash, entry] : std::get<json::Object>(split.body.at("resources").data)) hashes.emplace_back(hash);
    json::Object dump{
        {"schema", std::string(kRecipeSchema)},
        {"revision", revision},
        {"evaluator_profile", project.versions.evaluator_profile},
        {"compat_profile", project.versions.compat_profile},
        {"app_version", host.app_version},
        {"resource_hashes", std::move(hashes)},
        {"digest", RecipeDigest(split.body)},
    };
    dump["recipe"] = std::move(split.body);
    dump["rebuild"] = std::move(split.rebuild);
    return dump;
}

// ── Rebuild ─────────────────────────────────────────────────────────────────────────────────

namespace {

/// `value` set at `pointer` inside `doc`, whose parent object must exist.
void Patch(json::Value& doc, const std::vector<std::string>& tokens, json::Value value, const std::string& where) {
    json::Value* at = &doc;
    for (std::size_t i = 0; i + 1 < tokens.size(); ++i) {
        if (at->IsObject()) {
            const auto it = Obj(*at).find(tokens[i]);
            if (it == Obj(*at).end()) Fail(where, "names a place the recipe does not hold");
            at = &it->second;
        } else if (at->IsArray()) {
            const std::string& t = tokens[i];
            if (t.empty() || t.find_first_not_of("0123456789") != std::string::npos || std::stoull(t) >= Arr(*at).size()) {
                Fail(where, "names a place the recipe does not hold");
            }
            at = &Arr(*at)[std::stoull(t)];
        } else {
            Fail(where, "names a place the recipe does not hold");
        }
    }
    if (!at->IsObject()) Fail(where, "names a place the recipe does not hold");
    Obj(*at)[tokens.back()] = std::move(value);
}

/// Sets `key` of `object` to `value` unless the rebuild block gave it.
void Default(json::Object& object, std::string_view key, json::Value value) {
    if (object.find(key) == object.end()) object.emplace(std::string(key), std::move(value));
}

/// The manifest of the project the document describes (fresh ids; see `ProjectFromRecipe`).
/// Reads the document unchecked: the caller turns a wrong type or a missing key into a
/// `ManifestError`.
json::Value RebuildManifest(json::Object doc, const RecipeHost& host) {
    json::Value manifest_value = json::Object{};
    json::Object& manifest = Obj(manifest_value);
    json::Value defaults = ProjectToJson(Project{});
    json::Object& d = Obj(defaults);
    Id next_id = 1;
    const auto allocate = [&] { return json::Value(static_cast<std::int64_t>(next_id++)); };

    manifest["schema"] = std::string(kManifestSchema);
    json::Object versions = std::move(Obj(d.at("versions")));
    versions["app_version"] = host.app_version;
    versions["evaluator_profile"] = AsString(Need(doc, "evaluator_profile", "$.recipe"), "$.recipe.evaluator_profile");
    if (const auto it = doc.find("painter_reference"); it != doc.end()) versions["painter_reference"] = it->second;
    manifest["versions"] = std::move(versions);

    json::Object settings = AsObject(Need(doc, "settings", "$.recipe"), "$.recipe.settings");
    for (const char* key : {"default_resolution", "mesh_unit_scale", "import_cameras", "auto_unwrap"}) {
        Default(settings, key, Obj(d.at("settings")).at(key));
    }
    const std::string template_id = AsString(Need(settings, "template", "$.recipe.settings"), "$.recipe.settings.template");
    if (template_id == "default") settings.erase("template");
    // The colour management of the project being rebuilt, never the session's: the host's base
    // values can depend on it. Absent when the recipe names no string mode.
    std::optional<ColorManagement> colour;
    if (const auto it = settings.find("color_management"); it != settings.end() && it->second.IsObject()) {
        const json::Object& recorded = std::get<json::Object>(it->second.data);
        const auto mode = recorded.find("mode");
        if (mode != recorded.end() && mode->second.IsString()) {
            colour.emplace();
            colour->mode = std::get<std::string>(mode->second.data);
            const auto hash = recorded.find("config_hash");
            if (hash != recorded.end() && hash->second.IsString()) {
                colour->config_hash = std::get<std::string>(hash->second.data);
            }
        }
    }
    manifest["settings"] = std::move(settings);
    manifest["mesh"] = Need(doc, "mesh", "$.recipe");
    for (const char* key : {"display", "export_defaults", "metadata"}) {
        const auto it = doc.find(key);
        manifest[key] = it != doc.end() ? it->second : d.at(key);
    }

    json::Array sets = AsArray(Need(doc, "texture_sets", "$.recipe"), "$.recipe.texture_sets");
    for (std::size_t i = 0; i < sets.size(); ++i) {
        const std::string path = "$.recipe.texture_sets[" + std::to_string(i) + "]";
        json::Object& set = Obj(sets[i]);
        set["id"] = allocate();
        Default(set, "description", "");
        Default(set, "bake_settings",
                json::Object{{"common", json::Object{}}, {"detail", json::Object{}}, {"per_baker", json::Object{}}});
        for (json::Value& tile : Arr(Need(set, "uv_tiles", path))) Obj(tile)["id"] = allocate();
        for (auto& [usage, binding_value] : Obj(Need(set, "mesh_maps", path))) {
            json::Object& binding = Obj(binding_value);
            Default(binding, "invalid_report", nullptr);
            json::Object& provenance = Obj(binding.at("provenance"));
            // A recipe written without its rebuild block (a migration) states an imported map's
            // convention only: the rest of its provenance reads as unknown.
            if (provenance.at("kind") == json::Value(std::string(ToString(MeshMapProvenanceKind::imported)))) {
                Default(provenance, "source_path", "");
                Default(provenance, "source_sha256", binding.at("resource"));
                Default(provenance, "declared_role", std::string(ToString(MeshMapRole::geometry_only)));
                Default(provenance, "units", "");
            }
        }
        for (json::Value& stack_value : Arr(Need(set, "stacks", path))) {
            json::Object& stack = Obj(stack_value);
            stack["id"] = allocate();
            for (auto& [type, channel_value] : Obj(Need(stack, "channels", path))) {
                json::Object& channel = Obj(channel_value);
                const std::optional<ChannelType> channel_type = FromString<ChannelType>(type);
                if (!channel_type) Fail(path + ".channels." + type, "unknown channel type");
                const std::string& format_name = AsString(Need(channel, "format", path + ".channels." + type),
                                                          path + ".channels." + type + ".format");
                const std::optional<ChannelFormat> format = FromString<ChannelFormat>(format_name);
                if (!format) Fail(path + ".channels." + type + ".format", "unknown member '" + format_name + "'");
                const json::Value expected =
                    BaseJson(host.base_value(template_id, *channel_type, *format, colour ? &*colour : nullptr));
                if (Need(channel, "base", path + ".channels." + type) != expected) {
                    throw ValueError("recipe: the base value of channel " + type + " differs from this build's template '" +
                                     template_id + "' (" + json::WriteCanonical(channel.at("base")) + " recorded, " +
                                     json::WriteCanonical(expected) + " here)");
                }
                channel.erase("base");
                Default(channel, "label", "");
            }
        }
        std::map<std::string, json::Value> uids;
        ForEachStackNode(set, [&](json::Object& node, const std::string& pointer, bool is_layer) {
            node["uid"] = allocate();
            uids[pointer] = node.at("uid");
            Default(node, "preset_ref", nullptr);
            if (is_layer && node.at("kind") == json::Value(std::string(ToString(LayerKind::group)))) {
                Default(node, "collapsed", false);
            }
        });
        const auto uid_of = [&](const json::Value& pointer, const std::string& what) {
            const auto it = uids.find(AsString(pointer, what));
            if (it == uids.end()) {
                throw ValueError("recipe: " + what + " points at " + std::get<std::string>(pointer.data) +
                                 ", which is not a node of its texture set");
            }
            return it->second;
        };
        ForEachStackNode(set, [&](json::Object& node, const std::string& pointer, bool is_layer) {
            ForEachSource(node, [&](json::Object& source) {
                if (IsReference(source)) source["anchor"] = uid_of(source.at("anchor"), path + pointer + " (reference source)");
            });
            if (const auto it = node.find("instance_source"); is_layer && it != node.end()) {
                it->second = uid_of(it->second, path + pointer + " (instance)");
            }
            if (const auto it = node.find("paint"); it != node.end() && it->second.IsObject()) {
                json::Object& paint = Obj(it->second);
                const auto planes = paint.find("planes");
                const auto plane = paint.find("plane");
                if ((planes != paint.end() && planes->second.IsObject() && !Obj(planes->second).empty()) ||
                    (plane != paint.end() && !plane->second.IsNull())) {
                    throw NotYetSupported("recipe: " + path + pointer +
                                          " holds paint plane content, which a rebuild cannot replay yet "
                                          "(phase4.1_nodes-paint-layers)");
                }
            }
        });
    }
    manifest["texture_sets"] = std::move(sets);

    // The stored entries: the catalog of the rebuild block, else one entry per referenced hash,
    // the mesh named after its file (the `$mesh` export wildcard reads the name from the import
    // report, which the body keeps).
    json::Object resources;
    if (const auto catalog = doc.find("resource_catalog"); catalog != doc.end()) {
        for (auto& [hash, entries] : Obj(catalog->second)) {
            json::Array list;
            for (json::Value& entry : Arr(entries)) {
                json::Object e = Obj(entry);
                e["id"] = allocate();
                list.emplace_back(std::move(e));
            }
            resources[hash] = std::move(list);
        }
    }
    std::string mesh_hash, mesh_name;
    if (json::Value& mesh = manifest.at("mesh"); !mesh.IsNull()) {
        json::Object& m = Obj(mesh);
        mesh_hash = AsString(Need(m, "resource", "$.recipe.mesh"), "$.recipe.mesh.resource");
        json::Object& report = Obj(Need(m, "import_report", "$.recipe.mesh"));
        if (const auto source = report.find("source"); source != report.end()) {
            if (const auto name = Obj(source->second).find("name"); name != Obj(source->second).end() && name->second.IsString()) {
                mesh_name = std::get<std::string>(name->second.data);
            }
        }
    }
    for (const auto& [hash, entry_value] : AsObject(Need(doc, "resources", "$.recipe"), "$.recipe.resources")) {
        if (resources.find(hash) != resources.end()) continue;
        const std::string path = "$.recipe.resources." + hash;
        const json::Object& entry = AsObject(entry_value, path);
        const bool is_mesh = hash == mesh_hash;
        resources[hash] = json::Array{json::Object{
            {"id", allocate()},
            {"name", is_mesh && !mesh_name.empty() ? mesh_name : hash},
            {"mime", AsString(Need(entry, "mime", path), path + ".mime")},
            {"size", AsInt(Need(entry, "size", path), path + ".size")},
            {"usage", is_mesh ? "mesh" : "TEXTURE"},
            {"origin", ""},
            {"imported_at", ""},
            {"color_space", ""},
            {"session", false},
        }};
    }
    manifest["resources"] = std::move(resources);
    manifest["next_id"] = static_cast<std::int64_t>(next_id);
    return manifest_value;
}

}  // namespace

Project ProjectFromRecipe(const json::Value& dump_value, const RecipeHost& host) {
    const json::Object& dump = AsObject(dump_value, "$");
    const auto member = [&](const char* key) -> const json::Value& { return Need(dump, key, "$"); };
    if (AsString(member("schema"), "$.schema") != kRecipeSchema) {
        Fail("$.schema", "expected '" + std::string(kRecipeSchema) + "'");
    }
    const json::Object& body = AsObject(member("recipe"), "$.recipe");
    if (RecipeDigest(body) != AsString(member("digest"), "$.digest")) {
        Fail("$.digest", "does not match the SHA-256 of the recipe's canonical JSON");
    }
    if (NamesObservation(body)) {
        Fail("$.recipe", "names an asset of the reserved observation family, which a recipe never carries (decision 362)");
    }
    // The ARC-11 header: every key present and typed (HeaderFromJson), the compatibility profile
    // this build implements, and the profile and hashes the body states.
    const ResultRecordHeader header = HeaderFromJson(dump);
    if (header.compat_profile != kCompatProfile) {
        Fail("$.compat_profile", "'" + header.compat_profile + "' is not this build's profile '" + std::string(kCompatProfile) + "'");
    }
    if (json::Value(header.evaluator_profile) != Need(body, "evaluator_profile", "$.recipe")) {
        Fail("$.evaluator_profile", "differs from the recipe's evaluator_profile");
    }
    std::set<std::string> referenced;
    for (const auto& [hash, entry] : AsObject(Need(body, "resources", "$.recipe"), "$.recipe.resources")) referenced.insert(hash);
    if (header.resource_hashes != referenced) Fail("$.resource_hashes", "differs from the hashes of the recipe's resources");

    // The rebuild block only adds rebuild-only keys: it never changes what the digest covers.
    const json::Object& rebuild = AsObject(member("rebuild"), "$.rebuild");
    json::Value doc = body;
    for (const auto& [pointer, value] : rebuild) {
        const std::string where = "$.rebuild[\"" + pointer + "\"]";
        const std::vector<std::string> tokens = Tokens(pointer, where);
        if (!RebuildOnly(tokens)) Fail(where, "is output-determining state: it belongs to the digested recipe");
        Patch(doc, tokens, value, where);
    }

    json::Value manifest;
    try {
        manifest = RebuildManifest(std::move(Obj(doc)), host);
    } catch (const std::bad_variant_access&) {
        Fail("$.recipe", "a value does not have the type the recipe schema gives it");
    } catch (const std::out_of_range&) {
        Fail("$.recipe", "a key the recipe schema requires is missing");
    }
    Project project = ProjectFromJson(manifest);
    Validate(project);
    const Split again = SplitDocument(project, host.base_value);
    if (again.body != body) {
        Fail("$.recipe", "holds keys or values this version does not rebuild (its body is not the body of the rebuilt project)");
    }
    for (const auto& [pointer, value] : rebuild) {
        const auto it = again.rebuild.find(pointer);
        if (it == again.rebuild.end() || it->second != value) {
            Fail("$.rebuild[\"" + pointer + "\"]", "is not what the rebuilt project holds there");
        }
    }
    return project;
}

}  // namespace uzp::core
