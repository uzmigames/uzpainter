#include "mesh/reload.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstring>
#include <fstream>
#include <iterator>
#include <map>
#include <set>
#include <utility>
#include <variant>

#include "mesh/import_error.h"
#include "uzp_core/manifest/recipe.h"
#include "uzp_core/manifest/sha256.h"
#include "uzp_core/types/errors.h"

namespace uzp::mesh {

namespace json = core::json;

std::string_view TexelClassName(TexelClass value) {
    switch (value) {
        case TexelClass::none: return "none";
        case TexelClass::unchanged: return "unchanged";
        case TexelClass::moved: return "moved";
        case TexelClass::new_: return "new";
        case TexelClass::replaced: return "replaced";
        case TexelClass::removed: return "removed";
    }
    return "";
}

json::Object SetRegions::ToJson() const {
    return {{"grid", json::Object{{"height", height}, {"width", width}}},
            {"moved", json::Value(moved)},
            {"new", json::Value(new_)},
            {"removed", json::Value(removed)},
            {"replaced", json::Value(replaced)},
            {"unchanged", json::Value(unchanged)}};
}

json::Object ReloadReport::ToJson() const {
    const auto strings = [](const std::vector<std::string>& list) {
        json::Array out;
        for (const std::string& s : list) out.push_back(s);
        return out;
    };
    const auto ids = [](const std::vector<core::Id>& list) {
        json::Array out;
        for (core::Id id : list) out.push_back(json::Value(static_cast<std::uint64_t>(id)));
        return out;
    };
    json::Array renamed_json;
    for (const auto& [from, to] : renamed) renamed_json.push_back(json::Object{{"from", from}, {"to", to}});
    json::Object regions_json;
    for (const SetRegions& r : regions) regions_json[r.texture_set] = r.ToJson();
    json::Array maps;
    for (const MeshMapRef& m : invalid_mesh_maps) {
        maps.push_back(json::Object{{"texture_set", m.texture_set}, {"usage", std::string(core::ToString(m.usage))}});
    }
    return {{"sets", json::Object{{"added", strings(added)}, {"removed", strings(removed)}, {"renamed", std::move(renamed_json)}}},
            {"regions", std::move(regions_json)},
            {"mesh", json::Object{{"changed", strings(changed)}, {"from", mesh_from}, {"to", mesh_to}}},
            {"invalidated", json::Object{{"geometry_masks", ids(invalid_geometry_masks)},
                                         {"mesh_maps", std::move(maps)},
                                         {"procedural", ids(invalid_procedural)},
                                         {"receipt_resources", strings(invalid_receipt_resources)}}}};
}

namespace {

using Digest = std::array<std::uint8_t, 32>;
constexpr std::uint32_t kNone = 0xFFFFFFFFu;

/// SHA-256 over values appended in their little-endian byte form.
class Hasher {
public:
    template <typename T>
    Hasher& Put(const T& value) {
        char bytes[sizeof(T)];
        std::memcpy(bytes, &value, sizeof(T));
        sha_.Update(std::string_view(bytes, sizeof(T)));
        return *this;
    }
    Hasher& Text(std::string_view text) {
        sha_.Update(text);
        return Put<std::uint8_t>(0);
    }
    Digest Finish() { return sha_.Finish(); }

private:
    core::Sha256 sha_;
};

/// A triangle of a texturing mesh with its corner hashes (12 §7):
/// - `uv`: the corners' `uv0` (float32 pairs), in the triangle's cyclic order starting from the
///   smallest corner hash, so the same UV triangle written from another corner has the same key;
/// - `full`: per corner its `uv0`, its scene-space position in centimetres (object transform and
///   `units.scale_to_internal` applied, float64), its authored normal, its tangent and sign and
///   its object's transform, in the same canonical cyclic order;
/// - `place`: the object's name and `uv` (where a material's triangles are found again).
struct KeyedTriangle {
    std::array<Float2, 3> uv{};
    std::uint32_t material = 0;
    std::uint32_t object = 0;
    Digest uv_key{};
    Digest full_key{};
    Digest place_key{};
};

std::array<double, 3> Transform(const Matrix4& m, const Float3& p) {
    const double x = p.x, y = p.y, z = p.z;
    return {m[0] * x + m[4] * y + m[8] * z + m[12], m[1] * x + m[5] * y + m[9] * z + m[13],
            m[2] * x + m[6] * y + m[10] * z + m[14]};
}

/// The hash of `corners` in cyclic order from the smallest one.
Digest Cyclic(const std::array<Digest, 3>& corners) {
    const std::size_t start = static_cast<std::size_t>(std::min_element(corners.begin(), corners.end()) - corners.begin());
    Hasher h;
    for (std::size_t k = 0; k < 3; ++k) h.Put(corners[(start + k) % 3]);
    return h.Finish();
}

std::vector<KeyedTriangle> KeyTriangles(const TexturingMesh& mesh) {
    std::vector<KeyedTriangle> out;
    out.reserve(mesh.TriangleCount());
    const double scale = mesh.units.scale_to_internal;
    for (std::uint32_t o = 0; o < mesh.objects.size(); ++o) {
        const Object& object = mesh.objects[o];
        for (const Triangle& t : object.triangles) {
            KeyedTriangle tri;
            tri.object = o;
            tri.material = mesh.corners[t.corners[0]].material;
            std::array<Digest, 3> uv_corners{}, full_corners{};
            for (std::size_t k = 0; k < 3; ++k) {
                const Corner& c = mesh.corners[t.corners[k]];
                tri.uv[k] = c.uv0;
                uv_corners[k] = Hasher().Put(c.uv0.u).Put(c.uv0.v).Finish();
                Hasher full;
                full.Put(c.uv0.u).Put(c.uv0.v);
                for (double p : Transform(object.transform, mesh.positions[c.position])) full.Put(p * scale);
                full.Put(c.normal.x).Put(c.normal.y).Put(c.normal.z);
                for (float e : c.tangent) full.Put(e);
                for (double e : object.transform) full.Put(e);
                full_corners[k] = full.Finish();
            }
            tri.uv_key = Cyclic(uv_corners);
            tri.full_key = Cyclic(full_corners);
            tri.place_key = Hasher().Text(object.name).Put(tri.uv_key).Finish();
            out.push_back(tri);
        }
    }
    return out;
}

/// The keyed triangles and material names of one mesh.
struct KeyedMesh {
    const ImportResult* import = nullptr;
    std::vector<KeyedTriangle> triangles;

    explicit KeyedMesh(const ImportResult& r) : import(&r), triangles(KeyTriangles(r.mesh)) {}
    const TexturingMesh& mesh() const { return import->mesh; }
    /// The material index named `name`, or kNone.
    std::uint32_t MaterialOf(std::string_view name) const {
        for (const Material& m : mesh().materials) {
            if (m.name == name) return m.index;
        }
        return kNone;
    }
};

// ── Texel coverage (the `uv_raster.h` rule, float32 as its kernel) ───────────────────────────

struct F2 {
    float x = 0.0f;
    float y = 0.0f;
};

float EdgeRaw(F2 a, F2 b, F2 p) {
    const float left = (b.x - a.x) * (p.y - a.y);
    const float right = (b.y - a.y) * (p.x - a.x);
    return left - right;
}

/// The edge function in one canonical vertex order (lexicographic on x, then y).
float Edge(F2 a, F2 b, F2 p) {
    const bool ordered = a.x < b.x || (a.x == b.x && a.y < b.y);
    return ordered ? EdgeRaw(a, b, p) : -EdgeRaw(b, a, p);
}

/// Per texel (row 0 = v 1) the index into `tris` of the lowest-indexed triangle of `material`
/// whose UV triangle contains the texel centre (boundary included, degenerate triangles
/// excluded), or kNone.
std::vector<std::uint32_t> Cover(const std::vector<KeyedTriangle>& tris, std::uint32_t material, int width, int height) {
    std::vector<std::uint32_t> winner(static_cast<std::size_t>(width) * static_cast<std::size_t>(height), kNone);
    if (material == kNone) return winner;
    const float w = static_cast<float>(width), h = static_cast<float>(height);
    for (std::uint32_t i = 0; i < tris.size(); ++i) {
        const KeyedTriangle& tri = tris[i];
        if (tri.material != material) continue;
        std::array<F2, 3> t{};
        for (std::size_t k = 0; k < 3; ++k) t[k] = {tri.uv[k].u * w, tri.uv[k].v * h};
        const float area = Edge(t[0], t[1], t[2]);
        if (area == 0.0f) continue;
        const float orientation = area > 0.0f ? 1.0f : -1.0f;
        const double min_x = std::min({t[0].x, t[1].x, t[2].x}), max_x = std::max({t[0].x, t[1].x, t[2].x});
        const double min_y = std::min({t[0].y, t[1].y, t[2].y}), max_y = std::max({t[0].y, t[1].y, t[2].y});
        const long long x0 = std::max(0LL, static_cast<long long>(std::floor(min_x - 0.5)));
        const long long x1 = std::min<long long>(width - 1, static_cast<long long>(std::ceil(max_x - 0.5)));
        const long long y0 = std::max(0LL, static_cast<long long>(std::floor(min_y - 0.5)));
        const long long y1 = std::min<long long>(height - 1, static_cast<long long>(std::ceil(max_y - 0.5)));
        for (long long y = y0; y <= y1; ++y) {
            for (long long x = x0; x <= x1; ++x) {
                const F2 p{static_cast<float>(x) + 0.5f, static_cast<float>(y) + 0.5f};
                const float e0 = Edge(t[1], t[2], p) * orientation;
                const float e1 = Edge(t[2], t[0], p) * orientation;
                const float e2 = Edge(t[0], t[1], p) * orientation;
                if (!(e0 >= 0.0f && e1 >= 0.0f && e2 >= 0.0f && (e0 + e1) + e2 > 0.0f)) continue;
                const std::size_t row = static_cast<std::size_t>(height - 1 - y);
                std::uint32_t& slot = winner[row * static_cast<std::size_t>(width) + static_cast<std::size_t>(x)];
                if (slot == kNone) slot = i;
            }
        }
    }
    return winner;
}

SetRegions Classify(const std::string& name, const KeyedMesh& before, std::uint32_t old_material, const KeyedMesh& after,
                    std::uint32_t new_material, const core::Resolution& grid) {
    SetRegions r;
    r.texture_set = name;
    r.width = grid.width;
    r.height = grid.height;
    const std::vector<std::uint32_t> was = Cover(before.triangles, old_material, grid.width, grid.height);
    const std::vector<std::uint32_t> now = Cover(after.triangles, new_material, grid.width, grid.height);
    r.texels.resize(was.size(), TexelClass::none);
    for (std::size_t i = 0; i < was.size(); ++i) {
        TexelClass& c = r.texels[i];
        if (was[i] == kNone && now[i] == kNone) continue;
        if (was[i] == kNone) {
            c = TexelClass::new_;
            ++r.new_;
        } else if (now[i] == kNone) {
            c = TexelClass::removed;
            ++r.removed;
        } else if (before.triangles[was[i]].uv_key != after.triangles[now[i]].uv_key) {
            c = TexelClass::replaced;
            ++r.replaced;
        } else if (before.triangles[was[i]].full_key != after.triangles[now[i]].full_key) {
            c = TexelClass::moved;
            ++r.moved;
        } else {
            c = TexelClass::unchanged;
            ++r.unchanged;
        }
    }
    return r;
}

/// Per object name, the sorted UV-triangle keys of `material`'s triangles (a geometry mask's
/// selection).
std::map<std::string, std::vector<Digest>> ObjectUvKeys(const KeyedMesh& keyed, std::uint32_t material) {
    std::map<std::string, std::vector<Digest>> out;
    if (material == kNone) return out;
    for (const KeyedTriangle& t : keyed.triangles) {
        if (t.material == material) out[keyed.mesh().objects[t.object].name].push_back(t.uv_key);
    }
    for (auto& [name, keys] : out) std::sort(keys.begin(), keys.end());
    return out;
}

// ── Material identity ────────────────────────────────────────────────────────────────────────

json::Array Names(const std::set<std::string>& names) {
    json::Array out;
    for (const std::string& n : names) out.push_back(n);
    return out;
}

/// Matches the current materials to the new ones (`material_mapping` applied). Returns, per
/// current material name, its identity in the new mesh (absent: the material disappeared), and
/// throws `MaterialMappingError` for renames, splits and merges the mapping does not accept.
std::map<std::string, std::string> MatchMaterials(const KeyedMesh& before, const KeyedMesh& after,
                                                  const std::map<std::string, std::string>& mapping) {
    std::set<std::string> old_names, new_names;
    for (const Material& m : before.mesh().materials) old_names.insert(m.name);
    for (const Material& m : after.mesh().materials) new_names.insert(m.name);
    std::set<std::string> mapped_targets;
    for (const auto& [from, to] : mapping) {
        if (!old_names.contains(from)) {
            throw core::ValueError("material_mapping names '" + from + "', which the current mesh does not have");
        }
        if (!new_names.contains(to)) {
            throw core::ValueError("material_mapping maps '" + from + "' to '" + to + "', which the new mesh does not have");
        }
        if ((to != from && old_names.contains(to)) || !mapped_targets.insert(to).second) {
            throw core::ValueError("material_mapping maps two materials to '" + to + "': a merge is not a rename");
        }
    }
    std::map<std::string, std::string> identity;  // old name -> new name, for materials that stay
    std::set<std::string> gone;
    for (const std::string& name : old_names) {
        const auto m = mapping.find(name);
        const std::string& target = m != mapping.end() ? m->second : name;
        if (new_names.contains(target)) {
            identity[name] = target;
        } else {
            gone.insert(name);
        }
    }
    std::set<std::string> fresh = new_names;
    for (const auto& [from, to] : identity) fresh.erase(to);

    // Where each current material's triangles are found again (same object, same UV triangle).
    std::map<Digest, std::set<std::uint32_t>> places;
    for (const KeyedTriangle& t : after.triangles) places[t.place_key].insert(t.material);
    std::map<std::string, std::set<std::string>> flows;  // old name -> new names it flows into
    for (const KeyedTriangle& t : before.triangles) {
        const std::string& name = before.mesh().materials[t.material].name;
        const auto found = places.find(t.place_key);
        if (found == places.end()) continue;
        for (std::uint32_t m : found->second) {
            const std::string& target = after.mesh().materials[m].name;
            const bool kept = identity.contains(name);
            if (kept ? fresh.contains(target) : true) flows[name].insert(target);
        }
    }

    json::Array proposal;
    json::Object renames;
    std::set<std::string> merged_targets;
    std::string message;
    const auto add = [&](std::string_view kind, const std::set<std::string>& from, const std::set<std::string>& to) {
        proposal.push_back(json::Object{{"from", Names(from)}, {"kind", kind}, {"to", Names(to)}});
        std::string line(kind);
        for (const std::set<std::string>* side : {&from, &to}) {
            std::string list;
            for (const std::string& n : *side) list += (list.empty() ? "'" : ", '") + n + "'";
            line += (side == &from ? " " : " -> ") + list;
        }
        message += (message.empty() ? "" : "; ") + line;
    };
    for (const auto& [name, targets] : flows) {
        if (identity.contains(name)) {
            std::set<std::string> to = targets;
            to.insert(identity.at(name));
            add("split", {name}, to);
            continue;
        }
        if (targets.size() > 1) {
            add("split", {name}, targets);
            continue;
        }
        const std::string& target = *targets.begin();
        std::set<std::string> sources;
        for (const auto& [other, other_targets] : flows) {
            if (other_targets.contains(target)) sources.insert(other);
        }
        for (const auto& [old_name, new_name] : identity) {
            if (new_name == target) sources.insert(old_name);
        }
        if (sources.size() == 1 && fresh.contains(target)) {
            add("rename", {name}, {target});
            renames[name] = target;
        } else if (merged_targets.insert(target).second) {
            add("merge", sources, {target});
        }
    }
    if (!proposal.empty()) {
        throw MaterialMappingError("the mesh's materials changed identity (" + message +
                                       "); nothing was reloaded: accept renames with material_mapping, "
                                       "or rename the materials in the mesh",
                                   {{"mapping", std::move(renames)}, {"proposal", std::move(proposal)}});
    }
    return identity;
}

// ── Invalidation ─────────────────────────────────────────────────────────────────────────────

void Flag(json::Object& extra, const json::Object& report) {
    extra["invalid"] = true;
    extra["invalid_report"] = report;
}

/// Flags every procedural reference of `fill`; returns whether there was one.
bool FlagFill(core::FillContent& fill, const json::Object& report) {
    bool any = false;
    const auto source = [&](core::Source& s) {
        if (auto* p = std::get_if<core::ProceduralSource>(&s.value)) {
            Flag(p->ref.extra, report);
            any = true;
        }
    };
    for (auto& [channel, s] : fill.sources) source(s);
    if (fill.mono_source) source(*fill.mono_source);
    if (fill.material_source) source(*fill.material_source);
    return any;
}

bool FlagEffect(core::Effect& effect, const json::Object& report) {
    bool any = effect.fill ? FlagFill(*effect.fill, report) : false;
    if (effect.procedural) {
        Flag(effect.procedural->extra, report);
        any = true;
    }
    return any;
}

/// What a reload invalidates in the layers of one texture set.
struct SetInvalidation {
    /// Whether a geometry mask's selection changed.
    std::function<bool(const core::GeometryMask&)> mask_changed;
    json::Object report;
};

void InvalidateLayers(std::vector<core::Layer>& layers, const SetInvalidation& inv, ReloadReport& out) {
    for (core::Layer& layer : layers) {
        if (inv.mask_changed(layer.geometry_mask)) {
            Flag(layer.geometry_mask.extra, inv.report);
            out.invalid_geometry_masks.push_back(layer.uid);
        }
        if (layer.fill && FlagFill(*layer.fill, inv.report)) out.invalid_procedural.push_back(layer.uid);
        for (core::Effect& e : layer.content_effects) {
            if (FlagEffect(e, inv.report)) out.invalid_procedural.push_back(e.uid);
        }
        if (layer.mask) {
            for (core::Effect& e : layer.mask->effects) {
                if (FlagEffect(e, inv.report)) out.invalid_procedural.push_back(e.uid);
            }
        }
        InvalidateLayers(layer.children, inv, out);
    }
}

std::vector<std::string> ChangedHashes(const TexturingMesh& a, const TexturingMesh& b) {
    std::vector<std::string> changed;
    if (a.hashes.positions != b.hashes.positions) changed.push_back("positions");
    if (a.hashes.uvs != b.hashes.uvs) changed.push_back("uvs");
    if (a.hashes.corner_normals != b.hashes.corner_normals) changed.push_back("corner_normals");
    if (a.hashes.triangulation != b.hashes.triangulation) changed.push_back("triangulation");
    if (a.hashes.materials != b.hashes.materials) changed.push_back("materials");
    if (a.units.scale_to_internal != b.units.scale_to_internal) changed.push_back("units");
    return changed;
}

const json::Value* Member(const json::Object& object, std::string_view key) {
    const auto it = object.find(key);
    return it == object.end() ? nullptr : &it->second;
}

const json::Object& ObjectMember(const json::Object& object, std::string_view key) {
    const json::Value* v = Member(object, key);
    if (v == nullptr || !v->IsObject()) {
        throw core::ValueError("the mesh's import report has no '" + std::string(key) + "' object");
    }
    return std::get<json::Object>(v->data);
}

}  // namespace

ImportResult RederiveMesh(const core::Project& project, const ResourceReader& read, bool beside_origin) {
    if (!project.mesh) throw core::ValueError("the project has no mesh to reload; import one first");
    const core::MeshReference& ref = *project.mesh;
    const json::Object& report = ref.import_report;
    const json::Value* name = Member(ObjectMember(report, "source"), "name");
    if (name == nullptr || !name->IsString()) throw core::ValueError("the mesh's import report has no source name");
    const std::string& file_name = std::get<std::string>(name->data);
    ImportSettings settings;
    if (const json::Value* scale = Member(ObjectMember(report, "units"), "requested_mesh_unit_scale")) {
        if (scale->IsInt()) settings.mesh_unit_scale = static_cast<double>(std::get<std::int64_t>(scale->data));
        if (scale->IsDouble()) settings.mesh_unit_scale = std::get<double>(scale->data);
    }
    settings.allow_duplicate_material_names = Member(report, "merged_materials") != nullptr;
    // The files the mesh reads beside it come from the project too (SAV-01). A report written
    // before they were stored reads them beside the origin, as that version did.
    std::map<std::string, std::string> files;  // uri -> sha256
    const json::Value* list = Member(report, core::kMeshExternalFiles);
    std::filesystem::path origin_dir;
    if (const auto entries = project.resources.find(ref.resource); entries != project.resources.end()) {
        for (const core::ResourceMeta& e : entries->second) {
            if (e.name == file_name && !e.origin.empty()) origin_dir = std::filesystem::path(e.origin).parent_path();
        }
    }
    bool read_beside = false;  // a file was read beside the origin (a project written before they were stored)
    const ExternalFileReader beside = [&](const std::string& uri, const std::filesystem::path& path) {
        read_beside = true;
        const std::string legacy = "the mesh '" + file_name + "' reads the file '" + uri +
                                   "' beside it, which a project written before a mesh's files were stored does not hold";
        if (!beside_origin) throw MeshFileMissing(legacy + " (reload the mesh to store it)");
        if (origin_dir.empty()) throw MeshFileMissing(legacy + ", and its origin is unknown (reload the mesh to store it)");
        std::ifstream file(origin_dir / path, std::ios::binary);
        if (!file) {
            throw MeshFileMissing(legacy + ", and it is gone from " + origin_dir.generic_string() +
                                  " (reload the mesh to store it)");
        }
        return std::string((std::istreambuf_iterator<char>(file)), std::istreambuf_iterator<char>());
    };
    if (list != nullptr && list->IsArray()) {
        for (const json::Value& file : std::get<json::Array>(list->data)) {
            const json::Value* uri = file.IsObject() ? Member(std::get<json::Object>(file.data), "uri") : nullptr;
            const json::Value* sha = file.IsObject() ? Member(std::get<json::Object>(file.data), "sha256") : nullptr;
            if (uri == nullptr || sha == nullptr || !uri->IsString() || !sha->IsString()) {
                throw core::ValueError("the mesh's import report lists an external file without its uri and sha256");
            }
            files[std::get<std::string>(uri->data)] = std::get<std::string>(sha->data);
        }
    }
    const ExternalFileReader stored = [&](const std::string& uri, const std::filesystem::path&) {
        const auto it = files.find(uri);
        if (it == files.end()) {
            throw core::ValueError("the mesh '" + file_name + "' reads the file '" + uri +
                                   "' beside it, which the project does not store (reload the mesh to store it)");
        }
        std::string file = read(it->second);
        if (core::Sha256Hex(file) != it->second) {
            throw core::ValueError("the stored bytes of the mesh file '" + uri + "' do not match its hash " + it->second);
        }
        return file;
    };
    const std::string bytes = read(ref.resource);
    if (core::Sha256Hex(bytes) != ref.resource) {
        throw core::ValueError("the stored bytes of the mesh '" + file_name + "' do not match its hash " + ref.resource);
    }
    // A file read beside the origin is not the project's: when it no longer gives the recorded
    // geometry (it was altered), the old geometry is unavailable, not corrupt. A stored file that
    // does is corruption.
    const std::string altered = "the mesh '" + file_name +
                                "' reads a file beside its origin, which a project written before a mesh's files were "
                                "stored does not hold, and that file no longer gives the recorded geometry";
    std::optional<ImportResult> current;
    try {
        current = ImportMesh(bytes, file_name, settings, list != nullptr ? stored : beside);
    } catch (const ImportError& error) {
        if (read_beside) throw MeshFileMissing(altered + " (" + error.what() + "; reload the mesh to store it)");
        throw;
    }
    const json::Value* hashes = Member(report, "hashes");
    if (hashes == nullptr || !(*hashes == json::Value(HashesToJson(current->mesh.hashes)))) {
        if (read_beside) throw MeshFileMissing(altered + " (reload the mesh to store it)");
        throw core::ValueError("the mesh '" + file_name + "' no longer re-derives to the hashes its import report records");
    }
    return std::move(*current);
}

/// The texture set a material of the new mesh adds: named after it, the project's default
/// resolution, tile 1001, one stack with the reload's channels.
core::TextureSet NewSet(core::Edit& edit, const Material& material, const ReloadSettings& settings) {
    core::TextureSet set;
    set.id = edit.AllocateId();
    set.name = material.name;
    set.original_name = material.name;
    set.material_id = material.name;
    set.resolution = edit.project().settings.default_resolution;
    set.uv_tiles.push_back(core::UVTile{edit.AllocateId(), 1001, {}});
    core::Stack stack;
    stack.id = edit.AllocateId();
    stack.channels = settings.new_set_channels;
    set.stacks.push_back(std::move(stack));
    return set;
}

/// The new mesh recorded, and the receipts the reload invalidates: those of every mesh file the
/// new mesh no longer reads (the old file, or only a glTF buffer whose bytes changed), sorted and
/// unique.
void FinishReload(core::Edit& edit, const ImportResult& next, const MeshSource& source, ReloadReport& report) {
    const std::set<std::string> before = core::MeshResourceHashes(edit.project());
    RecordMeshResource(edit, next, source);
    const std::set<std::string> after = core::MeshResourceHashes(edit.project());
    for (const std::string& hash : before) {
        if (!after.contains(hash)) report.invalid_receipt_resources.push_back(hash);
    }
    std::sort(report.invalid_receipt_resources.begin(), report.invalid_receipt_resources.end());
    report.invalid_receipt_resources.erase(
        std::unique(report.invalid_receipt_resources.begin(), report.invalid_receipt_resources.end()),
        report.invalid_receipt_resources.end());
    edit.returned()["reload"] = report.ToJson();
}

ReloadReport ApplyReload(core::Edit& edit, const ImportResult& current, const ImportResult& next, const MeshSource& source,
                         const ReloadSettings& settings) {
    core::Project& project = edit.project();
    if (!project.mesh) throw core::ValueError("the project has no mesh to reload; import one first");
    const KeyedMesh before(current);
    const KeyedMesh after(next);
    const std::map<std::string, std::string> identity = MatchMaterials(before, after, settings.material_mapping);

    ReloadReport report;
    report.mesh_from = project.mesh->resource;
    report.mesh_to = next.sha256;
    report.changed = ChangedHashes(current.mesh, next.mesh);
    const bool geometry_changed = std::any_of(report.changed.begin(), report.changed.end(),
                                              [](const std::string& h) { return h != "materials"; });

    // The current sets by material; a set without a material of the current mesh is kept as is.
    std::map<std::string, std::size_t> set_of;
    for (std::size_t i = 0; i < project.texture_sets.size(); ++i) set_of[project.texture_sets[i].material_id] = i;
    std::vector<bool> taken(project.texture_sets.size(), false);
    std::vector<core::TextureSet> sets;

    for (const Material& material : next.mesh.materials) {
        std::string old_name;
        for (const auto& [from, to] : identity) {
            if (to == material.name) old_name = from;
        }
        const auto found = old_name.empty() ? set_of.end() : set_of.find(old_name);
        if (found == set_of.end()) {
            core::TextureSet set = NewSet(edit, material, settings);
            report.added.push_back(material.name);
            report.regions.push_back(Classify(material.name, before, kNone, after, material.index, set.resolution));
            sets.push_back(std::move(set));
            continue;
        }
        taken[found->second] = true;
        core::TextureSet set = std::move(project.texture_sets[found->second]);
        if (old_name != material.name) {
            if (set.name == set.original_name) set.name = material.name;
            set.original_name = material.name;
            set.material_id = material.name;
            report.renamed.emplace_back(old_name, material.name);
        }
        SetRegions regions =
            Classify(material.name, before, before.MaterialOf(old_name), after, material.index, set.resolution);

        if (geometry_changed || regions.Changed()) {
            const json::Object invalid{{"changed", json::Array(report.changed.begin(), report.changed.end())},
                                       {"mesh", json::Object{{"from", report.mesh_from}, {"to", report.mesh_to}}},
                                       {"reason", "mesh_reload"},
                                       {"regions", regions.ToJson()}};
            for (auto& [usage, binding] : set.mesh_maps) {
                binding.invalid = true;
                binding.invalid_report = invalid;
                report.invalid_mesh_maps.push_back({set.name, usage});
                report.invalid_receipt_resources.push_back(binding.resource);
            }
            const auto was = ObjectUvKeys(before, before.MaterialOf(old_name));
            const auto now = ObjectUvKeys(after, material.index);
            SetInvalidation inv;
            inv.report = invalid;
            const bool coverage_changed = regions.CoverageChanged();
            inv.mask_changed = [&](const core::GeometryMask& mask) {
                if (mask.type != core::GeometryMaskType::Mesh || mask.items.empty()) return false;
                if (coverage_changed) return true;
                return std::any_of(mask.items.begin(), mask.items.end(), [&](const std::string& item) {
                    const auto a = was.find(item);
                    const auto b = now.find(item);
                    if (a == was.end() || b == now.end()) return (a == was.end()) != (b == now.end());
                    return a->second != b->second;
                });
            };
            for (core::Stack& stack : set.stacks) InvalidateLayers(stack.root_layers, inv, report);
        }
        report.regions.push_back(std::move(regions));
        sets.push_back(std::move(set));
    }
    for (std::size_t i = 0; i < project.texture_sets.size(); ++i) {
        if (taken[i]) continue;
        core::TextureSet& set = project.texture_sets[i];
        const std::uint32_t old_material = before.MaterialOf(set.material_id);
        if (old_material == kNone) {
            sets.push_back(std::move(set));  // not a set of the current mesh's materials: untouched
            continue;
        }
        report.removed.push_back(set.material_id);
        report.regions.push_back(Classify(set.material_id, before, old_material, after, kNone, set.resolution));
    }
    project.texture_sets = std::move(sets);

    // Receipts that read the old mesh or an invalidated map (`ReceiptInvalidated`).
    FinishReload(edit, next, source, report);
    return report;
}

ReloadReport ApplyReloadWithoutCurrent(core::Edit& edit, const ImportResult& next, const MeshSource& source,
                                       const ReloadSettings& settings, const std::string& reason) {
    core::Project& project = edit.project();
    if (!project.mesh) throw core::ValueError("the project has no mesh to reload; import one first");
    const KeyedMesh after(next);
    std::set<std::string> names;
    for (const Material& m : next.mesh.materials) names.insert(m.name);

    // Every set keeps its material by name, or through the mapping; nothing else can be proven.
    std::map<std::string, std::size_t> set_of;  // new material -> current set
    for (std::size_t i = 0; i < project.texture_sets.size(); ++i) {
        const std::string& from = project.texture_sets[i].material_id;
        const auto mapped = settings.material_mapping.find(from);
        const std::string to = mapped != settings.material_mapping.end() ? mapped->second : from;
        if (!names.contains(to) || !set_of.emplace(to, i).second) {
            throw MaterialMappingError("the current mesh cannot be re-derived (" + reason +
                                           "): the texture set of material '" + from +
                                           "' is kept only by its name or through material_mapping, and the new mesh " +
                                           (names.contains(to) ? "gives material '" + to + "' to two sets"
                                                               : "has no material '" + to + "'"),
                                       json::Object{{"proposal", json::Array{}}, {"mapping", json::Object{}}});
        }
    }

    ReloadReport report;
    report.mesh_from = project.mesh->resource;
    report.mesh_to = next.sha256;
    report.changed = {"corner_normals", "materials", "positions", "triangulation", "uvs"};
    const json::Object invalid{{"changed", json::Array(report.changed.begin(), report.changed.end())},
                               {"mesh", json::Object{{"from", report.mesh_from}, {"to", report.mesh_to}}},
                               {"previous_mesh", reason},
                               {"reason", "mesh_reload"},
                               {"regions", json::Value(nullptr)}};
    std::vector<core::TextureSet> sets;
    for (const Material& material : next.mesh.materials) {
        const auto found = set_of.find(material.name);
        if (found == set_of.end()) {
            core::TextureSet set = NewSet(edit, material, settings);
            report.added.push_back(material.name);
            report.regions.push_back(Classify(material.name, after, kNone, after, material.index, set.resolution));
            sets.push_back(std::move(set));
            continue;
        }
        core::TextureSet set = std::move(project.texture_sets[found->second]);
        if (set.material_id != material.name) {
            report.renamed.emplace_back(set.material_id, material.name);
            if (set.name == set.original_name) set.name = material.name;
            set.original_name = material.name;
            set.material_id = material.name;
        }
        for (auto& [usage, binding] : set.mesh_maps) {
            binding.invalid = true;
            binding.invalid_report = invalid;
            report.invalid_mesh_maps.push_back({set.name, usage});
            report.invalid_receipt_resources.push_back(binding.resource);
        }
        SetInvalidation inv;
        inv.report = invalid;
        inv.mask_changed = [](const core::GeometryMask& mask) {
            return mask.type == core::GeometryMaskType::Mesh && !mask.items.empty();
        };
        for (core::Stack& stack : set.stacks) InvalidateLayers(stack.root_layers, inv, report);
        // No old coverage to compare with: every texel the new mesh covers counts as new.
        report.regions.push_back(Classify(material.name, after, kNone, after, material.index, set.resolution));
        sets.push_back(std::move(set));
    }
    project.texture_sets = std::move(sets);
    FinishReload(edit, next, source, report);
    return report;
}

ReloadOutcome ReloadMesh(core::Document& document, core::MutationRequest request, const std::filesystem::path& path,
                         const ReloadSettings& settings, const ResourceReader& read, const MeshSource& source) {
    ReloadOutcome out;
    std::optional<ReloadReport> report;
    std::exception_ptr error;
    out.outcome = core::Execute(document, std::move(request), [&](core::Edit& edit) {
        try {
            std::optional<ImportResult> current;
            std::string unavailable;
            try {
                current = RederiveMesh(edit.base(), read);
            } catch (const MeshFileMissing& missing) {
                unavailable = missing.what();
            }
            const ImportResult next = ImportMeshFile(path, settings.import);
            report = current ? ApplyReload(edit, *current, next, source, settings)
                             : ApplyReloadWithoutCurrent(edit, next, source, settings, unavailable);
        } catch (...) {
            error = std::current_exception();
            throw;
        }
    });
    if (!out.outcome.result) return out;  // not admitted: the decision says why
    if (out.outcome.result->status == core::ResultStatus::failed) {
        out.error = error ? error : std::make_exception_ptr(std::runtime_error(out.outcome.result->error));
        return out;
    }
    out.report = std::move(report);
    return out;
}

bool ReceiptInvalidated(const core::ResultRecordHeader& header, const core::Project& project) {
    const std::set<std::string> current = core::MeshResourceHashes(project);
    for (const std::string& hash : header.resource_hashes) {
        if (const auto entries = project.resources.find(hash); entries != project.resources.end()) {
            const bool mesh = std::any_of(entries->second.begin(), entries->second.end(), [](const core::ResourceMeta& e) {
                return e.usage == "mesh" || e.usage == kExternalFileUsage;
            });
            if (mesh && !current.contains(hash)) return true;
        }
        for (const core::TextureSet& set : project.texture_sets) {
            for (const auto& [usage, binding] : set.mesh_maps) {
                if (binding.invalid && binding.resource == hash) return true;
            }
        }
    }
    return false;
}

}  // namespace uzp::mesh
