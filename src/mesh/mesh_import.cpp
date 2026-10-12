#include "mesh/mesh_import.h"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <fstream>
#include <iterator>
#include <set>
#include <sstream>
#include <variant>
#include <vector>

#include "mesh/fbx_import.h"
#include "mesh/gltf_import.h"
#include "mesh/import_error.h"
#include "mesh/obj_parser.h"
#include "mesh/tangents.h"
#include "uzp_core/manifest/sha256.h"
#include "uzp_core/types/errors.h"

namespace uzp::mesh {

namespace json = core::json;

std::string_view ErrorClassName(ImportErrorKind kind) {
    switch (kind) {
        case ImportErrorKind::parse_error: return "MeshParseError";
        case ImportErrorKind::unsupported_format: return "UnsupportedFormat";
        case ImportErrorKind::release_gap: return "ReleaseGap";
        case ImportErrorKind::not_yet_supported: return "NotYetSupported";
        case ImportErrorKind::duplicate_material_names: return "DuplicateMaterialNames";
        case ImportErrorKind::uv_outside_0_1: return "UVOutsideTile";
    }
    return "ImportError";
}

std::string_view FormatName(MeshFormat format) {
    switch (format) {
        case MeshFormat::obj: return "obj";
        case MeshFormat::fbx: return "fbx";
        case MeshFormat::gltf: return "gltf";
        case MeshFormat::glb: return "glb";
    }
    return "";
}

std::string_view MimeOf(MeshFormat format) {
    switch (format) {
        case MeshFormat::obj: return "model/obj";
        case MeshFormat::fbx: return "application/octet-stream";
        case MeshFormat::gltf: return "model/gltf+json";
        case MeshFormat::glb: return "model/gltf-binary";
    }
    return "application/octet-stream";
}

MeshFormat FormatOf(std::string_view file_name) {
    const std::size_t dot = file_name.rfind('.');
    std::string ext = dot == std::string_view::npos ? std::string() : std::string(file_name.substr(dot + 1));
    std::transform(ext.begin(), ext.end(), ext.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    if (ext == "obj") return MeshFormat::obj;
    if (ext == "fbx") return MeshFormat::fbx;
    if (ext == "gltf") return MeshFormat::gltf;
    if (ext == "glb") return MeshFormat::glb;
    static const std::set<std::string> kReleaseGaps = {"dae", "ply", "usd", "usda", "usdc", "usdz"};
    if (kReleaseGaps.contains(ext)) {
        throw ImportError(ImportErrorKind::release_gap,
                          "'." + ext + "' meshes are a release gap: UzPainter v1 imports OBJ, FBX, glTF and GLB",
                          {{"format", ext}});
    }
    throw ImportError(ImportErrorKind::unsupported_format,
                      "'" + std::string(file_name) + "' is not a mesh format Painter imports",
                      {{"format", ext}});
}

namespace {

json::Value Count(std::uint64_t n) { return json::Value(n); }

/// The duplicate-material-name rule (PRJ-02): fails, or merges every material into the first one
/// of its name. Returns the merges as `[{name, merged_indices}]`.
json::Array ApplyDuplicateRule(TexturingMesh& mesh, bool allow) {
    std::map<std::string, std::vector<std::uint32_t>> by_name;
    for (const Material& m : mesh.materials) by_name[m.name].push_back(m.index);
    json::Object duplicates;
    for (const auto& [name, indices] : by_name) {
        if (indices.size() < 2) continue;
        json::Array list;
        for (std::uint32_t i : indices) list.push_back(json::Value(static_cast<std::int64_t>(i)));
        duplicates[name] = std::move(list);
    }
    if (duplicates.empty()) return {};
    if (!allow) {
        std::string message = "duplicate material names:";
        for (const auto& [name, list] : duplicates) {
            message += " '" + name + "' (materials";
            for (const json::Value& v : std::get<json::Array>(list.data)) {
                message += " " + std::to_string(std::get<std::int64_t>(v.data));
            }
            message += ")";
        }
        message += "; pass allow_duplicate_material_names to merge them";
        throw ImportError(ImportErrorKind::duplicate_material_names, message, {{"duplicates", duplicates}});
    }
    std::vector<std::uint32_t> remap(mesh.materials.size(), 0);
    std::map<std::string, std::uint32_t> kept;
    std::vector<Material> merged;
    for (const Material& m : mesh.materials) {
        const auto [it, inserted] = kept.try_emplace(m.name, static_cast<std::uint32_t>(merged.size()));
        if (inserted) merged.push_back(Material{m.name, it->second});
        remap[m.index] = it->second;
    }
    for (Corner& c : mesh.corners) c.material = remap[c.material];
    mesh.materials = std::move(merged);
    json::Array merges;
    for (const auto& [name, list] : duplicates) {
        merges.push_back(json::Object{{"merged_indices", list}, {"name", name}});
    }
    return merges;
}

/// The tile of a UV square cell: its UDIM number when it has one, else "u<i>_v<j>".
json::Value TileOf(double fu, double fv) {
    if (fu >= 0 && fu <= 9 && fv >= 0 && fv <= 99) {
        return json::Value(static_cast<std::int64_t>(1001 + fu + 10 * fv));
    }
    return json::Value("u" + std::to_string(static_cast<std::int64_t>(fu)) + "_v" +
                       std::to_string(static_cast<std::int64_t>(fv)));
}

bool Inside01(const Float2& uv) { return uv.u >= 0.0f && uv.u <= 1.0f && uv.v >= 0.0f && uv.v <= 1.0f; }

/// Default workflow: every triangle lies in the 0-1 square (12 §6). A triangle with a corner
/// outside it is listed in the tile of its UV centroid.
void CheckUvTiles(const TexturingMesh& mesh) {
    std::set<std::pair<double, double>> cells;
    std::uint64_t outside = 0;
    for (const Object& object : mesh.objects) {
        for (const Triangle& t : object.triangles) {
            const Float2& a = mesh.corners[t.corners[0]].uv0;
            const Float2& b = mesh.corners[t.corners[1]].uv0;
            const Float2& c = mesh.corners[t.corners[2]].uv0;
            if (Inside01(a) && Inside01(b) && Inside01(c)) continue;
            ++outside;
            const double cu = (static_cast<double>(a.u) + b.u + c.u) / 3.0;
            const double cv = (static_cast<double>(a.v) + b.v + c.v) / 3.0;
            cells.emplace(std::floor(cu), std::floor(cv));
        }
    }
    if (outside == 0) return;
    json::Array tiles;
    std::string list;
    for (const auto& [fu, fv] : cells) {
        json::Value tile = TileOf(fu, fv);
        list += (list.empty() ? "" : ", ") +
                (tile.IsInt() ? std::to_string(std::get<std::int64_t>(tile.data)) : std::get<std::string>(tile.data));
        tiles.push_back(std::move(tile));
    }
    throw ImportError(ImportErrorKind::uv_outside_0_1,
                      "UVs outside the 0-1 tile in tiles " + list + " (" + std::to_string(outside) +
                          " triangles): UV tiles are a release gap of the Default workflow",
                      {{"tiles", std::move(tiles)}, {"triangles_outside", Count(outside)}});
}

void ApplyUnits(Units& units, const ImportSettings& settings) {
    if (settings.mesh_unit_scale) {
        const double scale = *settings.mesh_unit_scale;
        if (!std::isfinite(scale) || scale < 0.0) {
            throw core::ValueError("mesh_unit_scale must be finite and not negative (0 uses the file unit)");
        }
        if (scale > 0.0) {
            units.scale_to_internal = scale;
            units.from = "mesh_unit_scale";
            return;
        }
    }
    units.scale_to_internal = units.source_meters_per_unit > 0.0 ? units.source_meters_per_unit * 100.0 : 1.0;
    units.from = "file";
}

json::Object Report(const ImportResult& r, const ImportSettings& settings, json::Array merges) {
    const TexturingMesh& m = r.mesh;
    json::Array objects;
    for (const Object& o : m.objects) {
        json::Array transform;
        for (double e : o.transform) transform.push_back(json::Value(e));
        objects.push_back(json::Object{{"name", o.name},
                                       {"transform", std::move(transform)},
                                       {"triangles", Count(o.triangles.size())}});
    }
    json::Array materials;
    for (const Material& mat : m.materials) {
        materials.push_back(json::Object{{"index", static_cast<std::int64_t>(mat.index)}, {"name", mat.name}});
    }
    json::Array ignored;
    for (const std::string& name : m.flags.ignored_uv_sets) ignored.push_back(name);
    json::Value requested = nullptr;
    if (settings.mesh_unit_scale) requested = json::Value(*settings.mesh_unit_scale);
    json::Value meters = nullptr;
    if (m.units.source_meters_per_unit > 0.0) meters = json::Value(m.units.source_meters_per_unit);
    json::Object report{
        {"format", std::string(FormatName(r.format))},
        {"source", json::Object{{"name", r.file_name}, {"sha256", r.sha256}, {"size", r.size}}},
        {"units", json::Object{{"from", m.units.from},
                               {"requested_mesh_unit_scale", requested},
                               {"scale_to_internal", json::Value(m.units.scale_to_internal)},
                               {"source", m.units.source},
                               {"source_meters_per_unit", meters}}},
        {"objects", std::move(objects)},
        {"materials", std::move(materials)},
        {"counts", json::Object{{"corners", Count(m.corners.size())},
                                {"materials", Count(m.materials.size())},
                                {"objects", Count(m.objects.size())},
                                {"positions", Count(m.positions.size())},
                                {"triangles", Count(m.TriangleCount())}}},
        {"triangulation", json::Object{{"ngons_triangulated", Count(m.flags.ngons_triangulated)},
                                       {"rule", "fan_from_last_corner"}}},
        {"flags", json::Object{{"corners_without_normal", Count(m.flags.corners_without_normal)},
                               {"corners_without_uv", Count(m.flags.corners_without_uv)},
                               {"ignored_uv_sets", std::move(ignored)},
                               {"skipped_non_surface_elements", Count(m.flags.skipped_non_surface_elements)},
                               {"stored_tangents", Count(m.flags.stored_tangents)},
                               {"uv_set", m.flags.uv_set},
                               {"v_flip", m.flags.v_flip}}},
        {"format_details", m.flags.format_details},
        {"hashes", HashesToJson(m.hashes)},
        {"certificate", CertificateToJson(r.certificate, m)},
    };
    if (!merges.empty()) report["merged_materials"] = std::move(merges);
    if (!r.external_files.empty()) {
        json::Array files;
        for (const ExternalFile& f : r.external_files) {
            files.push_back(json::Object{{"uri", f.uri},
                                         {"sha256", core::Sha256Hex(f.bytes)},
                                         {"size", static_cast<std::int64_t>(f.bytes.size())}});
        }
        report[std::string(core::kMeshExternalFiles)] = std::move(files);
    }
    return report;
}

}  // namespace

ImportResult ImportMesh(std::string_view bytes, std::string_view file_name, const ImportSettings& settings,
                        const std::filesystem::path& directory) {
    const ExternalFileReader beside = [&directory](const std::string& uri, const std::filesystem::path& path) {
        if (directory.empty()) {
            throw ImportError(ImportErrorKind::parse_error,
                              "glTF: the buffer '" + uri + "' is a file beside the mesh, and no folder was given to read it from");
        }
        std::ifstream file(directory / path, std::ios::binary);
        if (!file) throw ImportError(ImportErrorKind::parse_error, "glTF: cannot read the buffer '" + uri + "'");
        return std::string((std::istreambuf_iterator<char>(file)), std::istreambuf_iterator<char>());
    };
    return ImportMesh(bytes, file_name, settings, beside);
}

ImportResult ImportMesh(std::string_view bytes, std::string_view file_name, const ImportSettings& settings,
                        const ExternalFileReader& read) {
    if (settings.auto_unwrap) {
        throw ImportError(ImportErrorKind::not_yet_supported,
                          "AutoUnwrapSettings is not supported yet: UzPainter never unwraps or repacks UVs "
                          "(release gap); import a mesh with UVs",
                          {{"auto_unwrap", *settings.auto_unwrap}});
    }
    ImportResult result;
    result.format = FormatOf(file_name);
    result.file_name = std::string(file_name);
    result.sha256 = core::Sha256Hex(bytes);
    result.size = static_cast<std::int64_t>(bytes.size());
    switch (result.format) {
        case MeshFormat::obj: ParseObj(bytes, result.mesh); break;
        case MeshFormat::fbx: ImportFbx(bytes, result.mesh); break;
        case MeshFormat::gltf:
        case MeshFormat::glb: ImportGltf(bytes, read, result.mesh, result.external_files); break;
    }
    json::Array merges = ApplyDuplicateRule(result.mesh, settings.allow_duplicate_material_names);
    CheckUvTiles(result.mesh);
    ApplyUnits(result.mesh.units, settings);
    result.mesh.hashes = ComputeHashes(result.mesh);
    ComputeTangents(result.mesh);
    result.certificate = Certify(result.mesh, settings.certificate);
    result.report = Report(result, settings, std::move(merges));
    return result;
}

ImportResult ImportMeshFile(const std::filesystem::path& path, const ImportSettings& settings) {
    std::ifstream file(path, std::ios::binary);
    if (!file) {
        throw ImportError(ImportErrorKind::parse_error, "cannot read '" + path.string() + "'");
    }
    const std::string bytes((std::istreambuf_iterator<char>(file)), std::istreambuf_iterator<char>());
    return ImportMesh(bytes, path.filename().string(), settings, path.parent_path());
}

void RecordMeshResource(core::Edit& edit, const ImportResult& result, const MeshSource& source) {
    core::Project& project = edit.project();
    std::vector<core::ResourceMeta>& entries = project.resources[result.sha256];
    const bool stored = std::any_of(entries.begin(), entries.end(),
                                    [&](const core::ResourceMeta& e) { return e.name == result.file_name; });
    if (stored) {
        edit.NoteSkippedResource(result.sha256);
    } else {
        core::ResourceMeta meta;
        meta.id = edit.AllocateId();
        meta.name = result.file_name;
        meta.mime = std::string(MimeOf(result.format));
        meta.size = result.size;
        meta.usage = "mesh";
        meta.origin = source.origin;
        meta.imported_at = source.imported_at;
        entries.push_back(std::move(meta));
    }
    for (const ExternalFile& file : result.external_files) {
        const std::string sha256 = core::Sha256Hex(file.bytes);
        std::vector<core::ResourceMeta>& list = project.resources[sha256];
        if (std::any_of(list.begin(), list.end(), [&](const core::ResourceMeta& e) { return e.name == file.uri; })) {
            edit.NoteSkippedResource(sha256);
            continue;
        }
        core::ResourceMeta meta;
        meta.id = edit.AllocateId();
        meta.name = file.uri;
        meta.mime = std::string(kExternalFileMime);
        meta.size = static_cast<std::int64_t>(file.bytes.size());
        meta.usage = std::string(kExternalFileUsage);
        meta.origin = source.origin.empty()
                          ? std::string()
                          : (std::filesystem::path(source.origin).parent_path() / file.uri).generic_string();
        meta.imported_at = source.imported_at;
        list.push_back(std::move(meta));
    }
    project.mesh = core::MeshReference{result.sha256, result.report, {}, source.origin};
}

void CreateTextureSets(core::Edit& edit, const ImportResult& result, const MeshSource& source,
                       const std::map<core::ChannelType, core::Channel>& channels) {
    core::Project& project = edit.project();
    if (project.mesh || !project.texture_sets.empty()) {
        throw core::ValueError("the project already has a mesh; replacing it is a mesh reload");
    }
    RecordMeshResource(edit, result, source);
    for (const Material& material : result.mesh.materials) {
        core::TextureSet set;
        set.id = edit.AllocateId();
        set.name = material.name;
        set.original_name = material.name;
        set.material_id = material.name;
        set.resolution = project.settings.default_resolution;
        set.uv_tiles.push_back(core::UVTile{edit.AllocateId(), 1001, {}});
        core::Stack stack;
        stack.id = edit.AllocateId();
        stack.channels = channels;
        set.stacks.push_back(std::move(stack));
        project.texture_sets.push_back(std::move(set));
    }
}

}  // namespace uzp::mesh
