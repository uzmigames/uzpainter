// Native tests and driver of UzPainter's mesh importers (`src/mesh/`, task
// phase1.4_mesh-importers). Built by `zig build mesh-tests` and driven by
// tests/mesh/test_mesh_import.py.
//
// Usage:
//   uzp-mesh-tests run [case]               run every native case (or one); exit 0 when all pass
//   uzp-mesh-tests import <file> [options]  import a mesh, print {"report": ..., "mesh": ...}
//   uzp-mesh-tests project <file> [options] import into a new document in one transaction, print
//                                           the result, texture sets, resources and mesh reference
//   uzp-mesh-tests texel <png> <u> <v>      the texel of a PNG that contains (u, v) and its RGBA16
// Options: --mesh-unit-scale <x>, --allow-duplicate-material-names, --auto-unwrap <json object>.
// Every JSON output is canonical (`json::WriteCanonical`). An import refusal prints
// "<ErrorClass>: <message>" and then its details as canonical JSON on stderr and exits 3; for
// `project`, the unchanged document is still printed on stdout.

#include <cstdio>
#include <exception>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iterator>
#include <map>
#include <string>
#include <string_view>
#include <vector>

#include "mesh/import_error.h"
#include "mesh/mask_image.h"
#include "mesh/mesh_builder.h"
#include "mesh/mesh_import.h"
#include "mesh/obj_parser.h"
#include "mesh/texturing_mesh.h"
#include "uzp_core/document/document.h"
#include "uzp_core/manifest/json.h"
#include "uzp_core/transaction/transaction.h"
#include "uzp_core/types/errors.h"

namespace {

using namespace uzp;
using namespace uzp::mesh;
namespace json = uzp::core::json;

struct Failure {
    std::string message;
};

#define CHECK(cond)                                                                                    \
    do {                                                                                               \
        if (!(cond)) throw Failure{std::string(__FILE__ ":") + std::to_string(__LINE__) + ": " #cond}; \
    } while (false)

/// Runs `body`, which must throw `ImportError` of `kind`; returns the error.
ImportError ExpectImportError(ImportErrorKind kind, const std::function<void()>& body) {
    try {
        body();
    } catch (const ImportError& error) {
        if (error.kind() != kind) {
            throw Failure{"expected " + std::string(ErrorClassName(kind)) + ", got " +
                          std::string(ErrorClassName(error.kind())) + ": " + error.what()};
        }
        return error;
    }
    throw Failure{"expected " + std::string(ErrorClassName(kind)) + ", nothing thrown"};
}

ImportResult ImportText(std::string_view text, std::string_view name = "mesh.obj", ImportSettings settings = {}) {
    return ImportMesh(text, name, settings);
}

// ── Cases ────────────────────────────────────────────────────────────────────────────────────

void FanTriangulation() {
    TexturingMesh mesh;
    MeshBuilder builder(mesh);
    builder.BeginObject("o");
    const std::uint32_t m = builder.Material(7, 0, "m");
    std::vector<Corner> tri(3), penta(5);
    for (std::uint32_t i = 0; i < 3; ++i) tri[i] = Corner{i, {}, {}, {}, m};
    for (std::uint32_t i = 0; i < 5; ++i) penta[i] = Corner{i, {}, {}, {}, m};
    builder.AddPolygon(tri);
    builder.AddPolygon(penta);
    builder.Finish();
    CHECK(mesh.corners.size() == 8);
    CHECK(mesh.flags.ngons_triangulated == 1);
    const std::vector<Triangle>& t = mesh.objects.at(0).triangles;
    CHECK(t.size() == 4);
    CHECK((t[0].corners == std::array<std::uint32_t, 3>{0, 1, 2}));
    // The fan from the last corner (Painter's split, parity/semantics/polygon-triangulation.json).
    CHECK((t[1].corners == std::array<std::uint32_t, 3>{3, 4, 7}));
    CHECK((t[2].corners == std::array<std::uint32_t, 3>{4, 5, 7}));
    CHECK((t[3].corners == std::array<std::uint32_t, 3>{5, 6, 7}));
    bool threw = false;
    try {
        builder.AddPolygon(std::span<const Corner>(tri.data(), 2));
    } catch (const std::invalid_argument&) {
        threw = true;
    }
    CHECK(threw);
}

void ObjNegativeIndices() {
    const std::string positive =
        "v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\nvt 0 0\nvt 1 0\nvt 1 1\nvt 0 1\nvn 0 0 1\n"
        "f 1/1/1 2/2/1 3/3/1\nf 1/1/1 3/3/1 4/4/1\n";
    const std::string negative =
        "v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\nvt 0 0\nvt 1 0\nvt 1 1\nvt 0 1\nvn 0 0 1\n"
        "f -4/-4/-1 -3/-3/-1 -2/-2/-1\nf -4/-4/-1 -2/-2/-1 -1/-1/-1\n";
    const ImportResult a = ImportText(positive);
    const ImportResult b = ImportText(negative);
    CHECK(a.mesh.hashes == b.mesh.hashes);
    CHECK(a.mesh.corners == b.mesh.corners);
    // Relative to the elements defined so far, not to the file's totals.
    const ImportResult c = ImportText("v 0 0 0\nv 1 0 0\nv 0 1 0\nf -3 -2 -1\nv 5 5 5\nf -4 -3 -2\n");
    CHECK(c.mesh.corners[3].position == 0 && c.mesh.corners[5].position == 2);
}

void ObjMissingAttributes() {
    const ImportResult r = ImportText("v 0 0 0\nv 1 0 0\nv 0 1 0\nvt 0.25 0.5\nvn 0 0 1\nf 1 2 3\nf 1/1 2/1 3/1\nf 1//1 2//1 3//1\n");
    CHECK(r.mesh.flags.corners_without_uv == 6);
    CHECK(r.mesh.flags.corners_without_normal == 6);
    CHECK((r.mesh.corners[3].uv0 == Float2{0.25f, 0.5f}));
    CHECK((r.mesh.corners[0].normal == Float3{}));
    CHECK((r.mesh.corners[6].normal == Float3{0, 0, 1}));
    // Normals are kept as authored: not normalised, not recomputed.
    const ImportResult n = ImportText("v 0 0 0\nv 1 0 0\nv 0 1 0\nvn 0 0 3\nvn 1 0 0\nf 1//1 2//2 3//1\n");
    CHECK((n.mesh.corners[0].normal == Float3{0, 0, 3}));
    CHECK((n.mesh.corners[1].normal == Float3{1, 0, 0}));
}

void ObjObjectsAndMaterials() {
    const ImportResult r = ImportText(
        "mtllib a.mtl b.mtl\nv 0 0 0\nv 1 0 0\nv 0 1 0\n"
        "f 1 2 3\n"                          // object `default`, material `default`
        "o Body\nusemtl M_b\nf 1 2 3\n"      // Body, M_b
        "g Body\nusemtl M_a\nf 1 2 3\n"      // same name: still Body
        "g Trim\nusemtl M_b\nf 1 2 3 1\n"    // Trim, M_b again (a quad)
        "o Empty\nl 1 2\np 3\n");            // no faces: dropped
    const TexturingMesh& m = r.mesh;
    CHECK(m.objects.size() == 3);
    CHECK(m.objects[0].name == "default" && m.objects[1].name == "Body" && m.objects[2].name == "Trim");
    CHECK(m.objects[1].triangles.size() == 2 && m.objects[2].triangles.size() == 2);
    CHECK(m.materials.size() == 3);
    CHECK(m.materials[0].name == "default" && m.materials[1].name == "M_b" && m.materials[2].name == "M_a");
    CHECK(m.corners[3].material == 1 && m.corners[6].material == 2 && m.corners[9].material == 1);
    CHECK(m.flags.skipped_non_surface_elements == 2);
    CHECK(m.flags.ngons_triangulated == 1);
    CHECK((m.flags.format_details.at("mtllib") == json::Value(json::Array{"a.mtl", "b.mtl"})));
    // A `usemtl` without faces does not create a material.
    const ImportResult unused = ImportText("v 0 0 0\nv 1 0 0\nv 0 1 0\nusemtl X\nusemtl Y\nf 1 2 3\n");
    CHECK(unused.mesh.materials.size() == 1 && unused.mesh.materials[0].name == "Y");
}

void ObjParseErrors() {
    const ImportError zero = ExpectImportError(ImportErrorKind::parse_error, [] { ImportText("v 0 0 0\nf 0 1 1\n"); });
    CHECK(std::string(zero.what()).find("line 2") != std::string::npos);
    ExpectImportError(ImportErrorKind::parse_error, [] { ImportText("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 4\n"); });
    ExpectImportError(ImportErrorKind::parse_error, [] { ImportText("v 0 0 0\nv 1 0 0\nv 0 1 0\nf -4 2 3\n"); });
    ExpectImportError(ImportErrorKind::parse_error, [] { ImportText("v 0 x 0\n"); });
    ExpectImportError(ImportErrorKind::parse_error, [] { ImportText("v 0 0 0\nv 1 0 0\nf 1 2\n"); });
    ExpectImportError(ImportErrorKind::parse_error, [] { ImportText("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1/1 2 3\n"); });
}

void Formats() {
    CHECK(FormatOf("a.OBJ") == MeshFormat::obj);
    CHECK(FormatOf("dir.v2/a.Fbx") == MeshFormat::fbx);
    CHECK(FormatOf("a.gltf") == MeshFormat::gltf);
    CHECK(FormatOf("a.glb") == MeshFormat::glb);
    for (const char* gap : {"a.dae", "a.ply", "a.usd", "a.usda", "a.usdc", "a.usdz"}) {
        ExpectImportError(ImportErrorKind::release_gap, [&] { FormatOf(gap); });
    }
    ExpectImportError(ImportErrorKind::unsupported_format, [] { FormatOf("a.stl"); });
    ExpectImportError(ImportErrorKind::unsupported_format, [] { FormatOf("noextension"); });
}

void Units() {
    const std::string tri = "v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n";
    const ImportResult file = ImportText(tri);
    CHECK(file.mesh.units.source == "unspecified" && file.mesh.units.scale_to_internal == 1.0);
    CHECK(file.mesh.units.from == "file");
    ImportSettings zero;
    zero.mesh_unit_scale = 0.0;
    CHECK(ImportText(tri, "m.obj", zero).mesh.units.from == "file");
    ImportSettings inches;
    inches.mesh_unit_scale = 2.54;
    const ImportResult scaled = ImportText(tri, "m.obj", inches);
    CHECK(scaled.mesh.units.scale_to_internal == 2.54 && scaled.mesh.units.from == "mesh_unit_scale");
    ImportSettings negative;
    negative.mesh_unit_scale = -1.0;
    bool threw = false;
    try {
        ImportText(tri, "m.obj", negative);
    } catch (const core::ValueError&) {
        threw = true;
    }
    CHECK(threw);
}

void UvTiles() {
    const auto tiles = [](const std::string& uvs) {
        const ImportError e = ExpectImportError(ImportErrorKind::uv_outside_0_1, [&] {
            ImportText("v 0 0 0\nv 1 0 0\nv 0 1 0\n" + uvs + "f 1/1 2/2 3/3\n");
        });
        return e.details().at("tiles");
    };
    CHECK((tiles("vt 1.1 0.1\nvt 1.9 0.1\nvt 1.5 0.9\n") == json::Value(json::Array{1002})));
    CHECK((tiles("vt 0.1 1.1\nvt 0.9 1.1\nvt 0.5 1.9\n") == json::Value(json::Array{1011})));
    CHECK((tiles("vt -0.9 0.1\nvt -0.1 0.1\nvt -0.5 0.9\n") == json::Value(json::Array{"u-1_v0"})));
    // The closed square is inside: UVs exactly 0 or 1 are tile 1001.
    ImportText("v 0 0 0\nv 1 0 0\nv 0 1 0\nvt 0 0\nvt 1 0\nvt 1 1\nf 1/1 2/2 3/3\n");
}

void AutoUnwrapRejectedFirst() {
    ImportSettings settings;
    settings.auto_unwrap = json::Object{{"padding", 4}};
    const ImportError e = ExpectImportError(ImportErrorKind::not_yet_supported,
                                            [&] { ImportMesh("not a mesh at all", "x.dae", settings); });
    CHECK((e.details().at("auto_unwrap") == json::Value(json::Object{{"padding", 4}})));
}

void TexelConvention() {
    CHECK((TexelAt({0.0f, 1.0f}, 4, 4) == Texel{0, 0}));   // top-left: row 0 is v = 1
    CHECK((TexelAt({1.0f, 0.0f}, 4, 4) == Texel{3, 3}));   // bottom-right, clamped
    CHECK((TexelAt({0.125f, 0.875f}, 4, 4) == Texel{0, 0}));  // the centre of texel (0, 0)
    CHECK((TexelAt({0.375f, 0.125f}, 4, 2) == Texel{1, 1}));
}

void HashesSeparateConcerns() {
    const ImportResult a = ImportText("v 0 0 0\nv 1 0 0\nv 0 1 0\nvt 0 0\nvt 1 0\nvt 0 1\nusemtl A\nf 1/1 2/2 3/3\n");
    const ImportResult uv = ImportText("v 0 0 0\nv 1 0 0\nv 0 1 0\nvt 0 0\nvt 1 0\nvt 0 0.5\nusemtl A\nf 1/1 2/2 3/3\n");
    const ImportResult mat = ImportText("v 0 0 0\nv 1 0 0\nv 0 1 0\nvt 0 0\nvt 1 0\nvt 0 1\nusemtl B\nf 1/1 2/2 3/3\n");
    const ImportResult wind = ImportText("v 0 0 0\nv 1 0 0\nv 0 1 0\nvt 0 0\nvt 1 0\nvt 0 1\nusemtl A\nf 2/2 3/3 1/1\n");
    CHECK(a.mesh.hashes.uvs != uv.mesh.hashes.uvs && a.mesh.hashes.positions == uv.mesh.hashes.positions);
    CHECK(a.mesh.hashes.materials != mat.mesh.hashes.materials && a.mesh.hashes.uvs == mat.mesh.hashes.uvs);
    CHECK(a.mesh.hashes.triangulation != wind.mesh.hashes.triangulation);
}

const std::map<std::string, std::function<void()>, std::less<>>& Cases() {
    static const std::map<std::string, std::function<void()>, std::less<>> cases = {
        {"fan_triangulation", FanTriangulation},
        {"obj_negative_indices", ObjNegativeIndices},
        {"obj_missing_attributes", ObjMissingAttributes},
        {"obj_objects_and_materials", ObjObjectsAndMaterials},
        {"obj_parse_errors", ObjParseErrors},
        {"formats", Formats},
        {"units", Units},
        {"uv_tiles", UvTiles},
        {"auto_unwrap_rejected_first", AutoUnwrapRejectedFirst},
        {"texel_convention", TexelConvention},
        {"hashes_separate_concerns", HashesSeparateConcerns},
    };
    return cases;
}

int Run(std::string_view only) {
    int failed = 0;
    int ran = 0;
    for (const auto& [name, body] : Cases()) {
        if (!only.empty() && name != only) continue;
        ++ran;
        try {
            body();
            std::printf("PASS %s\n", name.c_str());
        } catch (const Failure& f) {
            ++failed;
            std::printf("FAIL %s: %s\n", name.c_str(), f.message.c_str());
        } catch (const std::exception& e) {
            ++failed;
            std::printf("FAIL %s: exception %s\n", name.c_str(), e.what());
        }
    }
    if (ran == 0) {
        std::fprintf(stderr, "no case named %.*s\n", static_cast<int>(only.size()), only.data());
        return 2;
    }
    return failed == 0 ? 0 : 1;
}

// ── Driver commands ──────────────────────────────────────────────────────────────────────────

ImportSettings ParseOptions(const std::vector<std::string>& args, std::size_t from) {
    ImportSettings settings;
    for (std::size_t i = from; i < args.size(); ++i) {
        if (args[i] == "--mesh-unit-scale" && i + 1 < args.size()) {
            settings.mesh_unit_scale = std::stod(args[++i]);
        } else if (args[i] == "--allow-duplicate-material-names") {
            settings.allow_duplicate_material_names = true;
        } else if (args[i] == "--auto-unwrap" && i + 1 < args.size()) {
            settings.auto_unwrap = std::get<json::Object>(json::Parse(args[++i]).data);
        } else {
            throw std::invalid_argument("unknown option " + args[i]);
        }
    }
    return settings;
}

json::Value F3(const Float3& v) { return json::Array{json::Value(double(v.x)), json::Value(double(v.y)), json::Value(double(v.z))}; }

json::Object MeshJson(const TexturingMesh& m) {
    json::Array positions;
    for (const Float3& p : m.positions) positions.push_back(F3(p));
    json::Array corners;
    for (const Corner& c : m.corners) {
        corners.push_back(json::Object{
            {"material", static_cast<std::int64_t>(c.material)},
            {"normal", F3(c.normal)},
            {"position", static_cast<std::int64_t>(c.position)},
            {"uv0", json::Array{json::Value(double(c.uv0.u)), json::Value(double(c.uv0.v))}},
        });
    }
    json::Array objects;
    for (const Object& o : m.objects) {
        json::Array triangles;
        for (const Triangle& t : o.triangles) {
            triangles.push_back(json::Array{static_cast<std::int64_t>(t.corners[0]), static_cast<std::int64_t>(t.corners[1]),
                                            static_cast<std::int64_t>(t.corners[2])});
        }
        objects.push_back(json::Object{{"name", o.name}, {"triangles", std::move(triangles)}});
    }
    return {{"corners", std::move(corners)}, {"objects", std::move(objects)}, {"positions", std::move(positions)}};
}

void PrintRefusal(const ImportError& error) {
    std::fprintf(stderr, "%s: %s\n%s\n", std::string(ErrorClassName(error.kind())).c_str(), error.what(),
                 json::WriteCanonical(error.details()).c_str());
}

json::Object ProjectJson(const core::Document& doc) {
    const core::Snapshot snap = doc.snapshot();
    json::Array sets;
    for (const core::TextureSet& set : snap.project->texture_sets) {
        sets.push_back(json::Object{
            {"id", static_cast<std::int64_t>(set.id)},
            {"material_id", set.material_id},
            {"name", set.name},
            {"original_name", set.original_name},
            {"stacks", static_cast<std::int64_t>(set.stacks.size())},
            {"uv_tiles", static_cast<std::int64_t>(set.uv_tiles.size())},
        });
    }
    json::Object resources;
    for (const auto& [hash, entries] : snap.project->resources) {
        json::Array list;
        for (const core::ResourceMeta& e : entries) {
            list.push_back(json::Object{{"mime", e.mime}, {"name", e.name}, {"size", e.size}, {"usage", e.usage}});
        }
        resources[hash] = std::move(list);
    }
    json::Value mesh = nullptr;
    if (snap.project->mesh) mesh = json::Object{{"resource", snap.project->mesh->resource}};
    return {{"mesh", mesh}, {"resources", std::move(resources)}, {"revision", snap.revision}, {"texture_sets", std::move(sets)}};
}

int Project(const std::filesystem::path& path, const ImportSettings& settings) {
    core::DocumentState state;
    state.project_uuid = "00000000-0000-4000-8000-000000000001";
    state.project.versions.app_version = "0.0.0";
    state.project.versions.evaluator_profile = "painter-12.1-layerq-linear";
    core::Document doc(std::move(state));
    std::optional<ImportResult> result;
    try {
        result = ImportMeshFile(path, settings);
    } catch (const ImportError& error) {
        PrintRefusal(error);
        std::printf("%s\n", json::WriteCanonical(json::Object{{"project", ProjectJson(doc)}}).c_str());
        return 3;
    }
    core::MutationRequest request{"project_create", json::Object{{"mesh", path.filename().string()}}, "create", 0};
    const core::RequestOutcome outcome = core::Execute(doc, request, [&](core::Edit& edit) {
        CreateTextureSets(edit, *result, MeshSource{path.string(), "2026-10-10T00:00:00Z"},
                          {{core::ChannelType::BaseColor, core::Channel{core::ChannelFormat::sRGB8, "", {}}}});
    });
    std::printf("%s\n", json::WriteCanonical(json::Object{{"project", ProjectJson(doc)},
                                                          {"report", result->report},
                                                          {"result", outcome.result->ToJson()}})
                            .c_str());
    return 0;
}

int TexelCommand(const std::filesystem::path& path, float u, float v) {
    std::ifstream file(path, std::ios::binary);
    const std::string bytes((std::istreambuf_iterator<char>(file)), std::istreambuf_iterator<char>());
    const ImageRgba16 image = DecodePng(bytes);
    const mesh::Texel t = TexelAt({u, v}, image.width, image.height);
    const auto rgba = image.At(t.col, t.row);
    std::printf("%s\n", json::WriteCanonical(json::Object{
                                                 {"col", static_cast<std::int64_t>(t.col)},
                                                 {"height", static_cast<std::int64_t>(image.height)},
                                                 {"rgba", json::Array{int{rgba[0]}, int{rgba[1]}, int{rgba[2]}, int{rgba[3]}}},
                                                 {"row", static_cast<std::int64_t>(t.row)},
                                                 {"width", static_cast<std::int64_t>(image.width)},
                                             })
                            .c_str());
    return 0;
}

}  // namespace

int main(int argc, char** argv) {
    const std::vector<std::string> args(argv + 1, argv + argc);
    try {
        if (!args.empty() && args[0] == "run") return Run(args.size() > 1 ? args[1] : std::string());
        if (args.size() >= 2 && args[0] == "import") {
            try {
                const ImportResult r = ImportMeshFile(args[1], ParseOptions(args, 2));
                std::printf("%s\n", json::WriteCanonical(json::Object{{"mesh", MeshJson(r.mesh)}, {"report", r.report}}).c_str());
                return 0;
            } catch (const ImportError& error) {
                PrintRefusal(error);
                return 3;
            }
        }
        if (args.size() >= 2 && args[0] == "project") return Project(args[1], ParseOptions(args, 2));
        if (args.size() == 4 && args[0] == "texel") return TexelCommand(args[1], std::stof(args[2]), std::stof(args[3]));
    } catch (const std::exception& e) {
        std::fprintf(stderr, "error: %s\n", e.what());
        return 2;
    }
    std::fprintf(stderr, "usage: uzp-mesh-tests run [case] | import <file> [options] | project <file> [options] | texel <png> <u> <v>\n");
    return 2;
}
