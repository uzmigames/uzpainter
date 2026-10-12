// Native tests of the mesh reload (`src/mesh/reload.h`, task phase1.6_mesh-reload;
// `docs/architecture/12-mesh-import.md` §7, §9). Built by `zig build mesh-tests` and driven by
// tests/mesh/test_mesh_reload.py. CPU only.
//
// Usage: uzp-mesh-reload-tests run [case]   run every case (or one); exit 0 when all pass.
//
// The fixture is an OBJ of four quads in tile 1001 on a 128 x 128 texel grid:
//   A: object `body`,   material `cloth`, u 0-0.25,   v 0-1    (4096 texels)
//   B: object `body`,   material `cloth`, u 0.25-0.5, v 0-1    (4096 texels)
//   C: object `sleeve`, material `cloth`, u 0.5-0.75, v 0-0.5  (2048 texels)
//   D: object `head`,   material `skin`,  u 0.5-1,    v 0.5-1  (4096 texels)
// The `cloth` set has an imported AO map and three layers: a paint layer, a fill layer with a
// geometry mask on `sleeve` and a fill layer with a generator effect.

#include <cstdio>
#include <cstring>
#include <exception>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iterator>
#include <map>
#include <memory>
#include <string>
#include <string_view>
#include <vector>

#include "mesh/import_error.h"
#include "mesh/mesh_import.h"
#include "mesh/reload.h"
#include "uzp_core/document/document.h"
#include "uzp_core/manifest/json.h"
#include "uzp_core/manifest/manifest.h"
#include "uzp_core/manifest/sha256.h"
#include "uzp_core/transaction/transaction.h"
#include "uzp_core/types/errors.h"
#include "uzp_core/types/receipt.h"

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

constexpr std::string_view kTime = "2026-10-10T00:00:00Z";

// ── Fixture ──────────────────────────────────────────────────────────────────────────────────

struct Quad {
    std::string object;
    std::string material;
    float x = 0.0f;  ///< left edge; the quad spans x..x+1, y 0..1, in the plane z
    float z = 0.0f;
    float u0 = 0.0f, u1 = 0.0f, v0 = 0.0f, v1 = 0.0f;
};

std::vector<Quad> BaseQuads() {
    return {{"body", "cloth", 0.0f, 0.0f, 0.0f, 0.25f, 0.0f, 1.0f},
            {"body", "cloth", 1.0f, 0.0f, 0.25f, 0.5f, 0.0f, 1.0f},
            {"sleeve", "cloth", 2.0f, 0.0f, 0.5f, 0.75f, 0.0f, 0.5f},
            {"head", "skin", 3.0f, 0.0f, 0.5f, 1.0f, 0.5f, 1.0f}};
}

std::string Num(float value) {
    char text[32];
    std::snprintf(text, sizeof(text), "%.9g", static_cast<double>(value));
    return text;
}

/// The OBJ text of `quads`: an `o` line when the object changes, a `usemtl` line when the
/// material changes, four corners per quad facing +z.
std::string Obj(const std::vector<Quad>& quads) {
    std::string text = "vn 0 0 1\n";
    std::string object, material;
    int base = 1;
    for (const Quad& q : quads) {
        if (q.object != object) text += "o " + (object = q.object) + "\n";
        if (q.material != material) text += "usemtl " + (material = q.material) + "\n";
        const float xs[4] = {q.x, q.x + 1.0f, q.x + 1.0f, q.x};
        const float ys[4] = {0.0f, 0.0f, 1.0f, 1.0f};
        const float us[4] = {q.u0, q.u1, q.u1, q.u0};
        const float vs[4] = {q.v0, q.v0, q.v1, q.v1};
        for (int k = 0; k < 4; ++k) text += "v " + Num(xs[k]) + " " + Num(ys[k]) + " " + Num(q.z) + "\n";
        for (int k = 0; k < 4; ++k) text += "vt " + Num(us[k]) + " " + Num(vs[k]) + "\n";
        text += "f";
        for (int k = 0; k < 4; ++k) text += " " + std::to_string(base + k) + "/" + std::to_string(base + k) + "/1";
        text += "\n";
        base += 4;
    }
    return text;
}

std::filesystem::path WriteFile(const std::filesystem::path& path, const std::string& text) {
    std::filesystem::create_directories(path.parent_path());
    std::ofstream(path, std::ios::binary) << text;
    return path;
}

core::Blending Normal() { return core::Blending{core::BlendingMode::Normal, 1.0, {}}; }

core::Source Uniform() { return core::Source{core::UniformColorSource{{0.5, 0.5, 0.5}, "sRGB", {}}}; }

core::FillContent UniformFill() {
    core::FillContent fill;
    fill.sources[core::ChannelType::BaseColor] = Uniform();
    fill.active_channels = {core::ChannelType::BaseColor};
    return fill;
}

struct Fixture {
    std::filesystem::path dir;
    std::map<std::string, std::string> blobs;  ///< what the project store keeps, by SHA-256
    std::unique_ptr<core::Document> doc;
    std::string ao;  ///< the AO map's resource hash
    core::Id cloth = core::kNoId, skin = core::kNoId;
    core::Id paint = core::kNoId, masked = core::kNoId, generated = core::kNoId, generator = core::kNoId;
    int requests = 0;

    const core::TextureSet& Set(core::Id id) const {
        for (const core::TextureSet& set : doc->snapshot().project->texture_sets) {
            if (set.id == id) return set;
        }
        throw Failure{"no texture set " + std::to_string(id)};
    }
    core::MutationRequest Request(std::string tool) {
        return {std::move(tool), json::Object{{"n", ++requests}}, "key-" + std::to_string(requests), doc->revision()};
    }
};

std::unique_ptr<Fixture> MakeFixture(std::string_view name) {
    auto f = std::make_unique<Fixture>();
    f->dir = std::filesystem::temp_directory_path() / "uzp-mesh-reload-tests" / std::string(name);
    std::filesystem::remove_all(f->dir);
    const std::string text = Obj(BaseQuads());
    const std::filesystem::path path = WriteFile(f->dir / "first" / "mesh.obj", text);
    const ImportResult imported = ImportMeshFile(path, {});
    f->blobs[imported.sha256] = text;

    core::DocumentState state;
    state.project_uuid = "00000000-0000-4000-8000-000000000016";
    state.project.versions.app_version = "0.0.0";
    state.project.versions.evaluator_profile = "painter-12.1-isolated-linear";
    state.project.settings.default_resolution = {128, 128, {}};
    f->doc = std::make_unique<core::Document>(std::move(state));
    const auto created = core::Execute(*f->doc, f->Request("project_create"), [&](core::Edit& edit) {
        CreateTextureSets(edit, imported, MeshSource{path.string(), std::string(kTime)},
                          {{core::ChannelType::BaseColor, core::Channel{core::ChannelFormat::sRGB8, "", {}}}});
    });
    CHECK(created.result && created.result->status == core::ResultStatus::committed);

    f->ao = core::Sha256Hex("ao map bytes");
    const auto decorated = core::Execute(*f->doc, f->Request("decorate"), [&](core::Edit& edit) {
        core::Project& p = edit.project();
        core::ResourceMeta meta;
        meta.id = edit.AllocateId();
        meta.name = "ao.png";
        meta.mime = "image/png";
        meta.size = 12;
        meta.usage = "texture";
        meta.origin = "C:/maps/ao.png";
        meta.imported_at = std::string(kTime);
        p.resources[f->ao] = {meta};
        for (core::TextureSet& set : p.texture_sets) {
            core::Layer paint;
            paint.uid = edit.AllocateId();
            paint.kind = core::LayerKind::paint;
            paint.name = "Paint";
            paint.blending[core::ChannelType::BaseColor] = Normal();
            paint.paint = core::PaintContent{{{core::ChannelType::BaseColor, set.id * 100}}, std::nullopt, {}};
            if (set.material_id == "skin") {
                f->skin = set.id;
                set.stacks[0].root_layers = {paint};
                continue;
            }
            f->cloth = set.id;
            f->paint = paint.uid;
            core::MeshMapBinding binding;
            binding.resource = f->ao;
            binding.format = core::ChannelFormat::L16;
            binding.color_space = "Raw";
            binding.provenance = core::ImportedProvenance{"C:/maps/ao.png", f->ao, core::MeshMapRole::geometry_only,
                                                          core::NormalMapFormat::OpenGL, "cm", {}};
            set.mesh_maps[core::MeshMapUsage::AO] = binding;
            core::Layer masked;
            masked.uid = f->masked = edit.AllocateId();
            masked.kind = core::LayerKind::fill;
            masked.name = "Sleeve only";
            masked.blending[core::ChannelType::BaseColor] = Normal();
            masked.fill = UniformFill();
            masked.geometry_mask = {core::GeometryMaskType::Mesh, true, {"sleeve"}, {}};
            core::Layer generated;
            generated.uid = f->generated = edit.AllocateId();
            generated.kind = core::LayerKind::fill;
            generated.name = "Generated";
            generated.blending[core::ChannelType::BaseColor] = Normal();
            generated.fill = UniformFill();
            core::Effect generator;
            generator.uid = f->generator = edit.AllocateId();
            generator.kind = core::EffectKind::generator;
            generator.name = "Position";
            generator.blending[core::ChannelType::BaseColor] = Normal();
            generator.active_channels = {core::ChannelType::BaseColor};
            generator.procedural = core::ProceduralRef{};
            generator.procedural->asset = "uzasset://generator/position@1.0.0";
            generated.content_effects = {generator};
            set.stacks[0].root_layers = {paint, masked, generated};
        }
    });
    CHECK(decorated.result && decorated.result->status == core::ResultStatus::committed);
    return f;
}

ReloadSettings Settings(std::map<std::string, std::string> mapping = {}) {
    ReloadSettings settings;
    settings.material_mapping = std::move(mapping);
    settings.new_set_channels = {{core::ChannelType::BaseColor, core::Channel{core::ChannelFormat::sRGB8, "", {}}}};
    return settings;
}

/// Reloads the mesh with `text` written as `<dir>/<folder>/mesh.obj`; the store keeps the new
/// bytes when the reload commits.
ReloadOutcome Reload(Fixture& f, const std::string& text, const ReloadSettings& settings = Settings(),
                     std::string_view folder = "next") {
    const std::filesystem::path path = WriteFile(f.dir / std::string(folder) / "mesh.obj", text);
    const ResourceReader read = [&](const std::string& sha) { return f.blobs.at(sha); };
    ReloadOutcome out = ReloadMesh(*f.doc, f.Request("reload_mesh"), path, settings, read,
                                   MeshSource{path.string(), std::string(kTime)});
    if (out.outcome.result && out.outcome.result->status == core::ResultStatus::committed) {
        f.blobs[core::Sha256Hex(text)] = text;
    }
    return out;
}

const SetRegions& RegionsOf(const ReloadReport& report, std::string_view set) {
    for (const SetRegions& r : report.regions) {
        if (r.texture_set == set) return r;
    }
    throw Failure{"no regions for " + std::string(set)};
}

/// unchanged, moved, new, replaced, removed.
bool Counts(const SetRegions& r, std::uint64_t unchanged, std::uint64_t moved, std::uint64_t fresh, std::uint64_t replaced,
            std::uint64_t removed) {
    return r.unchanged == unchanged && r.moved == moved && r.new_ == fresh && r.replaced == replaced && r.removed == removed;
}

/// The error of a failed reload, rethrown as `E`.
template <typename E>
E ErrorOf(const ReloadOutcome& out) {
    CHECK(out.error != nullptr);
    try {
        std::rethrow_exception(out.error);
    } catch (const E& error) {
        return error;
    } catch (const std::exception& other) {
        throw Failure{std::string("unexpected error type: ") + other.what()};
    }
    throw Failure{"unreachable"};
}

/// A failed reload changed nothing: same revision, same project, no report.
void CheckUnchanged(const Fixture& f, const core::Snapshot& before, const ReloadOutcome& out) {
    CHECK(out.outcome.result && out.outcome.result->status == core::ResultStatus::failed);
    CHECK(!out.report);
    const core::Snapshot after = f.doc->snapshot();
    CHECK(after.revision == before.revision);
    CHECK(*after.project == *before.project);
    CHECK(after.project->mesh->resource == before.project->mesh->resource);
    CHECK(!f.Set(f.cloth).mesh_maps.at(core::MeshMapUsage::AO).invalid);
}

json::Value Strings(std::initializer_list<const char*> list) {
    json::Array out;
    for (const char* s : list) out.push_back(s);
    return out;
}

bool HasInvalidFlag(const json::Object& extra) {
    const auto it = extra.find("invalid");
    return it != extra.end() && it->second == json::Value(true) && extra.contains("invalid_report");
}

// ── Cases ────────────────────────────────────────────────────────────────────────────────────

void IdenticalReload() {
    auto f = MakeFixture("identical");
    const core::Snapshot before = f->doc->snapshot();
    // The identical bytes from another folder: no pixel or derivation change, only the mesh's
    // source (decision 116) moves, in a metadata-only revision (decision 123).
    const ReloadOutcome out = Reload(*f, Obj(BaseQuads()));
    CHECK(out.outcome.result && out.outcome.result->status == core::ResultStatus::committed);
    CHECK(out.report);
    const ReloadReport& r = *out.report;
    CHECK(r.added.empty() && r.removed.empty() && r.renamed.empty());
    CHECK(r.changed.empty());
    CHECK(r.mesh_from == r.mesh_to);
    CHECK(Counts(RegionsOf(r, "cloth"), 10240, 0, 0, 0, 0));
    CHECK(Counts(RegionsOf(r, "skin"), 4096, 0, 0, 0, 0));
    CHECK(RegionsOf(r, "cloth").texels.size() == 128u * 128u);
    CHECK(r.invalid_mesh_maps.empty() && r.invalid_geometry_masks.empty() && r.invalid_procedural.empty());
    CHECK(r.invalid_receipt_resources.empty());
    CHECK(f->doc->revision() == before.revision + 1);
    core::Project expected = *before.project;
    expected.mesh->source = (f->dir / "next" / "mesh.obj").string();
    CHECK(*f->doc->snapshot().project == expected);
    // The same file again is a no-op: nothing at all changes.
    const ReloadOutcome again = Reload(*f, Obj(BaseQuads()));
    CHECK(again.outcome.result && again.outcome.result->status == core::ResultStatus::no_op);
    CHECK(f->doc->revision() == before.revision + 1 && *f->doc->snapshot().project == expected);
    const json::Object sets = std::get<json::Object>(r.ToJson().at("sets").data);
    CHECK(sets.at("added") == json::Value(json::Array{}) && sets.at("removed") == json::Value(json::Array{}) &&
          sets.at("renamed") == json::Value(json::Array{}));
}

void MovedVertices() {
    auto f = MakeFixture("moved");
    const core::Snapshot before = f->doc->snapshot();
    std::vector<Quad> quads = BaseQuads();
    quads[2].z = 0.5f;  // the sleeve moves; its UVs stay
    const ReloadOutcome out = Reload(*f, Obj(quads));
    CHECK(out.outcome.result && out.outcome.result->status == core::ResultStatus::committed);
    CHECK(out.report);
    const ReloadReport& r = *out.report;
    CHECK(r.added.empty() && r.removed.empty() && r.renamed.empty());
    CHECK(r.changed == std::vector<std::string>{"positions"});
    const SetRegions& cloth = RegionsOf(r, "cloth");
    CHECK(Counts(cloth, 8192, 2048, 0, 0, 0));
    // The sleeve's texels (u 0.5-0.75, v 0-0.5) are the moved ones: row 0 is v = 1.
    CHECK(cloth.texels[127 * 128 + 64] == TexelClass::moved);
    CHECK(cloth.texels[64 * 128 + 95] == TexelClass::moved);
    CHECK(cloth.texels[63 * 128 + 64] == TexelClass::none);
    CHECK(cloth.texels[0] == TexelClass::unchanged);
    CHECK(Counts(RegionsOf(r, "skin"), 4096, 0, 0, 0, 0));

    // The stack is kept: same sets, same layers in the same order, same paint.
    const core::Project& now = *f->doc->snapshot().project;
    CHECK(now.texture_sets.size() == 2);
    const core::TextureSet& set = f->Set(f->cloth);
    const core::TextureSet& old = before.project->texture_sets[0];
    CHECK(set.id == old.id && set.name == "cloth" && set.stacks.size() == 1);
    CHECK(set.stacks[0].root_layers.size() == 3);
    CHECK(set.stacks[0].root_layers[0] == old.stacks[0].root_layers[0]);  // the paint layer
    CHECK(set.stacks[0].root_layers[1] == old.stacks[0].root_layers[1]);  // the sleeve mask: same selection
    CHECK(f->Set(f->skin).stacks == before.project->texture_sets[1].stacks);

    // The AO binding is kept and marked invalid with the region report.
    const core::MeshMapBinding& ao = set.mesh_maps.at(core::MeshMapUsage::AO);
    CHECK(ao.resource == f->ao && ao.invalid && ao.invalid_report);
    CHECK(ao.invalid_report->at("reason") == json::Value("mesh_reload"));
    CHECK(ao.invalid_report->at("regions") == json::Value(cloth.ToJson()));
    CHECK(ao.invalid_report->at("changed") == Strings({"positions"}));
    CHECK(now.resources.contains(f->ao));
    CHECK(r.invalid_mesh_maps.size() == 1 && r.invalid_mesh_maps[0].texture_set == "cloth" &&
          r.invalid_mesh_maps[0].usage == core::MeshMapUsage::AO);

    // The generator's procedural cache is flagged; the geometry mask is not (same selection).
    const core::Effect& generator = set.stacks[0].root_layers[2].content_effects[0];
    CHECK(HasInvalidFlag(generator.procedural->extra));
    CHECK(r.invalid_procedural == std::vector<core::Id>{f->generator});
    CHECK(r.invalid_geometry_masks.empty());

    // The old mesh stays stored; the new one is the project's mesh.
    CHECK(now.mesh->resource == r.mesh_to && r.mesh_to != r.mesh_from);
    CHECK(now.resources.contains(r.mesh_from) && now.resources.contains(r.mesh_to));
    CHECK(out.outcome.result->returned.at("reload") == json::Value(r.ToJson()));

    // Receipts that read the old mesh or the invalid AO map are invalid.
    CHECK((r.invalid_receipt_resources == std::vector<std::string>{std::min(r.mesh_from, f->ao), std::max(r.mesh_from, f->ao)}));
    core::ResultRecordHeader receipt;
    receipt.resource_hashes = {r.mesh_from};
    CHECK(ReceiptInvalidated(receipt, now));
    receipt.resource_hashes = {r.mesh_to};
    CHECK(!ReceiptInvalidated(receipt, now));
    receipt.resource_hashes = {r.mesh_to, f->ao};
    CHECK(ReceiptInvalidated(receipt, now));
    CHECK(!ReceiptInvalidated(receipt, *before.project));

    // The flags are part of the manifest.
    const std::string manifest = core::SaveManifest(now);
    CHECK(core::LoadManifest(manifest) == now);
    CHECK(manifest.find("\"invalid\":true") != std::string::npos);
}

void UvChangeReplaced() {
    auto f = MakeFixture("uv-change");
    std::vector<Quad> quads = BaseQuads();
    quads[2].v1 = 0.25f;  // the sleeve's UV island shrinks to v 0-0.25
    const ReloadOutcome out = Reload(*f, Obj(quads));
    CHECK(out.outcome.result && out.outcome.result->status == core::ResultStatus::committed);
    const ReloadReport& r = *out.report;
    const SetRegions& cloth = RegionsOf(r, "cloth");
    CHECK(Counts(cloth, 8192, 0, 0, 1024, 1024));
    CHECK(cloth.texels[127 * 128 + 64] == TexelClass::replaced);  // v near 0
    CHECK(cloth.texels[64 * 128 + 64] == TexelClass::removed);    // v near 0.5
    CHECK(r.invalid_geometry_masks == std::vector<core::Id>{f->masked});
    const core::TextureSet& set = f->Set(f->cloth);
    CHECK(HasInvalidFlag(set.stacks[0].root_layers[1].geometry_mask.extra));
    CHECK(set.stacks[0].root_layers[1].geometry_mask.items == std::vector<std::string>{"sleeve"});
    CHECK(set.mesh_maps.at(core::MeshMapUsage::AO).invalid);
}

void RenameFixture() {
    auto f = MakeFixture("rename");
    const core::Snapshot before = f->doc->snapshot();
    std::vector<Quad> quads = BaseQuads();
    for (Quad& q : quads) {
        if (q.material == "cloth") q.material = "cloth_v2";
    }
    const std::string text = Obj(quads);
    const ReloadOutcome refused = Reload(*f, text);
    CheckUnchanged(*f, before, refused);
    const MaterialMappingError error = ErrorOf<MaterialMappingError>(refused);
    CHECK(error.details().at("proposal") ==
          json::Value(json::Array{json::Object{{"from", Strings({"cloth"})}, {"kind", "rename"}, {"to", Strings({"cloth_v2"})}}}));
    CHECK(error.details().at("mapping") == json::Value(json::Object{{"cloth", "cloth_v2"}}));
    CHECK(std::string(error.what()).find("rename 'cloth' -> 'cloth_v2'") != std::string::npos);

    // Accepting the proposal keeps the set, its stack and its binding (geometry unchanged).
    const ReloadOutcome accepted = Reload(*f, text, Settings({{"cloth", "cloth_v2"}}));
    CHECK(accepted.outcome.result && accepted.outcome.result->status == core::ResultStatus::committed);
    const ReloadReport& r = *accepted.report;
    CHECK((r.renamed == std::vector<std::pair<std::string, std::string>>{{"cloth", "cloth_v2"}}));
    CHECK(r.added.empty() && r.removed.empty());
    CHECK(r.changed == std::vector<std::string>{"materials"});
    CHECK(Counts(RegionsOf(r, "cloth_v2"), 10240, 0, 0, 0, 0));
    const core::TextureSet& set = f->Set(f->cloth);
    CHECK(set.name == "cloth_v2" && set.material_id == "cloth_v2" && set.original_name == "cloth_v2");
    CHECK(set.stacks == before.project->texture_sets[0].stacks);
    CHECK(!set.mesh_maps.at(core::MeshMapUsage::AO).invalid);

    // A mapping that names a material the mesh does not have is refused.
    const core::Snapshot renamed = f->doc->snapshot();
    const ReloadOutcome bad = Reload(*f, text, Settings({{"cloth", "cloth_v3"}}), "bad");
    CHECK(bad.outcome.result->status == core::ResultStatus::failed);
    ErrorOf<core::ValueError>(bad);
    CHECK(*f->doc->snapshot().project == *renamed.project);
}

void SplitFixture() {
    auto f = MakeFixture("split");
    const core::Snapshot before = f->doc->snapshot();
    std::vector<Quad> quads = BaseQuads();
    quads[1].material = "cloth_trim";  // quad B leaves `cloth`
    ReloadOutcome out = Reload(*f, Obj(quads));
    CheckUnchanged(*f, before, out);
    MaterialMappingError error = ErrorOf<MaterialMappingError>(out);
    CHECK(error.details().at("proposal") ==
          json::Value(json::Array{
              json::Object{{"from", Strings({"cloth"})}, {"kind", "split"}, {"to", Strings({"cloth", "cloth_trim"})}}}));
    CHECK(error.details().at("mapping") == json::Value(json::Object{}));

    // `cloth` disappears into two new materials.
    quads = BaseQuads();
    quads[0].material = "cloth_a";
    quads[1].material = "cloth_b";
    quads[2].material = "cloth_b";
    out = Reload(*f, Obj(quads));
    CheckUnchanged(*f, before, out);
    error = ErrorOf<MaterialMappingError>(out);
    CHECK(error.details().at("proposal") ==
          json::Value(json::Array{
              json::Object{{"from", Strings({"cloth"})}, {"kind", "split"}, {"to", Strings({"cloth_a", "cloth_b"})}}}));
}

void MergeFixture() {
    auto f = MakeFixture("merge");
    const core::Snapshot before = f->doc->snapshot();
    std::vector<Quad> quads = BaseQuads();
    quads[3].material = "cloth";  // `skin` merges into `cloth`
    const ReloadOutcome out = Reload(*f, Obj(quads));
    CheckUnchanged(*f, before, out);
    const MaterialMappingError error = ErrorOf<MaterialMappingError>(out);
    CHECK(error.details().at("proposal") ==
          json::Value(json::Array{
              json::Object{{"from", Strings({"cloth", "skin"})}, {"kind", "merge"}, {"to", Strings({"cloth"})}}}));
}

void AddedAndRemovedSets() {
    auto f = MakeFixture("added-removed");
    std::vector<Quad> quads = BaseQuads();
    quads.pop_back();                                                    // `skin` disappears with its faces
    quads.push_back({"belt", "belt", 5.0f, 0.0f, 0.75f, 1.0f, 0.0f, 0.5f});  // `belt` appears on new faces
    const ReloadOutcome out = Reload(*f, Obj(quads));
    CHECK(out.outcome.result && out.outcome.result->status == core::ResultStatus::committed);
    const ReloadReport& r = *out.report;
    CHECK(r.added == std::vector<std::string>{"belt"});
    CHECK(r.removed == std::vector<std::string>{"skin"});
    CHECK(r.renamed.empty());
    CHECK(Counts(RegionsOf(r, "belt"), 0, 0, 2048, 0, 0));
    CHECK(Counts(RegionsOf(r, "skin"), 0, 0, 0, 0, 4096));
    CHECK(Counts(RegionsOf(r, "cloth"), 10240, 0, 0, 0, 0));
    const core::Project& now = *f->doc->snapshot().project;
    CHECK(now.texture_sets.size() == 2);
    CHECK(now.texture_sets[0].id == f->cloth && now.texture_sets[1].name == "belt");
    CHECK(now.texture_sets[1].resolution == now.settings.default_resolution);
    CHECK(now.texture_sets[1].stacks.size() == 1 && now.texture_sets[1].stacks[0].channels.size() == 1);
    // The mesh's geometry changed: the whole-mesh AO of `cloth` is invalid though its texels are not.
    CHECK(f->Set(f->cloth).mesh_maps.at(core::MeshMapUsage::AO).invalid);
}

void FailureMidReload() {
    auto f = MakeFixture("failure");
    const core::Snapshot before = f->doc->snapshot();
    const auto operations = f->doc->operations().size();
    std::vector<Quad> quads = BaseQuads();
    quads[2].z = 0.5f;
    const std::string moved = Obj(quads);

    // The store fails to write the new revision after the reload applied every change.
    bool sink_saw_reload = false;
    f->doc->SetCommitSink([&](const core::Snapshot& snapshot, const core::OperationRecord&) {
        sink_saw_reload = snapshot.project->mesh->resource != before.project->mesh->resource &&
                          snapshot.project->texture_sets[0].mesh_maps.at(core::MeshMapUsage::AO).invalid;
        throw std::runtime_error("disk full");
    });
    ReloadOutcome out = Reload(*f, moved);
    CHECK(sink_saw_reload);
    CheckUnchanged(*f, before, out);
    CHECK(out.outcome.result->error.find("disk full") != std::string::npos);
    ErrorOf<std::runtime_error>(out);
    CHECK(f->doc->operations().size() == operations);
    f->doc->SetCommitSink(nullptr);

    // The current mesh's bytes cannot be read.
    const ResourceReader unreadable = [](const std::string&) -> std::string { throw std::runtime_error("blob missing"); };
    const std::filesystem::path path = WriteFile(f->dir / "unreadable" / "mesh.obj", moved);
    out = ReloadMesh(*f->doc, f->Request("reload_mesh"), path, Settings(), unreadable, MeshSource{path.string(), std::string(kTime)});
    CheckUnchanged(*f, before, out);
    CHECK(std::string(ErrorOf<std::runtime_error>(out).what()) == "blob missing");

    // The new mesh is refused at import.
    quads[0].u1 = 1.5f;
    out = Reload(*f, Obj(quads), Settings(), "outside");
    CheckUnchanged(*f, before, out);
    CHECK(ErrorOf<ImportError>(out).kind() == ImportErrorKind::uv_outside_0_1);

    // The document still reloads afterwards.
    out = Reload(*f, moved);
    CHECK(out.outcome.result->status == core::ResultStatus::committed);
    CHECK(f->doc->revision() == before.revision + 1);
}

/// A glTF quad (material `skin`, tile 1001) whose buffer is the external file `quad.bin` beside it.
std::filesystem::path WriteExternalGltf(const std::filesystem::path& dir) {
    std::string bin;
    const auto put = [&bin](const void* data, std::size_t size) { bin.append(static_cast<const char*>(data), size); };
    const float positions[12] = {0, 0, 0, 1, 0, 0, 1, 1, 0, 0, 1, 0};
    const float uvs[8] = {0, 1, 1, 1, 1, 0, 0, 0};
    const std::uint32_t indices[6] = {0, 1, 2, 0, 2, 3};
    put(positions, sizeof(positions));
    put(uvs, sizeof(uvs));
    put(indices, sizeof(indices));
    WriteFile(dir / "quad.bin", bin);
    const std::string gltf = R"({"asset":{"version":"2.0"},"scene":0,"scenes":[{"nodes":[0]}],)"
                             R"("nodes":[{"name":"head","mesh":0}],"materials":[{"name":"skin"}],)"
                             R"("meshes":[{"primitives":[{"attributes":{"POSITION":0,"TEXCOORD_0":1},"indices":2,"material":0}]}],)"
                             R"("accessors":[{"bufferView":0,"componentType":5126,"count":4,"type":"VEC3","min":[0,0,0],"max":[1,1,0]},)"
                             R"({"bufferView":1,"componentType":5126,"count":4,"type":"VEC2"},)"
                             R"({"bufferView":2,"componentType":5125,"count":6,"type":"SCALAR"}],)"
                             R"("bufferViews":[{"buffer":0,"byteOffset":0,"byteLength":48},{"buffer":0,"byteOffset":48,"byteLength":32},)"
                             R"({"buffer":0,"byteOffset":80,"byteLength":24}],)"
                             R"("buffers":[{"uri":"quad.bin","byteLength":104}]})";
    return WriteFile(dir / "quad.gltf", gltf);
}

/// A document holding `imported` (its bytes in `blobs`, its external files too when `store_files`).
std::unique_ptr<core::Document> GltfDocument(const ImportResult& imported, const std::filesystem::path& path,
                                             std::map<std::string, std::string>& blobs, const std::string& gltf) {
    blobs[imported.sha256] = gltf;
    for (const ExternalFile& file : imported.external_files) blobs[core::Sha256Hex(file.bytes)] = file.bytes;
    core::DocumentState state;
    state.project_uuid = "00000000-0000-4000-8000-000000000017";
    state.project.versions.app_version = "0.0.0";
    state.project.versions.evaluator_profile = "painter-12.1-isolated-linear";
    state.project.settings.default_resolution = {128, 128, {}};
    auto doc = std::make_unique<core::Document>(std::move(state));
    const auto created = core::Execute(*doc, core::MutationRequest{"project_create", json::Object{}, "create", 0},
                                       [&](core::Edit& edit) {
                                           CreateTextureSets(edit, imported, MeshSource{path.string(), std::string(kTime)},
                                                             {{core::ChannelType::BaseColor,
                                                               core::Channel{core::ChannelFormat::sRGB8, "", {}}}});
                                       });
    CHECK(created.result && created.result->status == core::ResultStatus::committed);
    return doc;
}

/// A glTF's external buffer is stored with the mesh and re-derives without its folder; a project
/// written before that (no `external_files` in its report) still re-derives beside its origin, is
/// `MeshFileMissing` once the file is gone (or for a reader of stored files only), and its mesh is
/// still replaced by a reload that cannot compare with it (phase2.1_recipe-dump-manifest-blocks).
void GltfExternalBuffer() {
    const std::filesystem::path dir = std::filesystem::temp_directory_path() / "uzp-mesh-reload-tests" / "gltf_external";
    std::filesystem::remove_all(dir);
    const std::filesystem::path path = WriteExternalGltf(dir / "source");
    std::ifstream in(path, std::ios::binary);
    const std::string gltf{std::istreambuf_iterator<char>(in), std::istreambuf_iterator<char>()};
    in.close();
    const ImportResult imported = ImportMeshFile(path, {});
    CHECK(imported.external_files.size() == 1 && imported.external_files[0].uri == "quad.bin");
    const json::Array& listed = std::get<json::Array>(imported.report.at(std::string(core::kMeshExternalFiles)).data);
    CHECK(listed.size() == 1);
    const std::string bin_sha = core::Sha256Hex(imported.external_files[0].bytes);
    CHECK(std::get<json::Object>(listed[0].data).at("sha256") == json::Value(bin_sha));

    // Current projects: the buffer is a resource, and the mesh re-derives with the folder gone.
    std::map<std::string, std::string> blobs;
    const auto current = GltfDocument(imported, path, blobs, gltf);
    const auto& entries = current->snapshot().project->resources.at(bin_sha);
    CHECK(entries.size() == 1 && entries[0].usage == std::string(kExternalFileUsage) && entries[0].name == "quad.bin");
    const ResourceReader read = [&](const std::string& sha) { return blobs.at(sha); };

    // A project of the previous version: the same mesh without the stored file or the report key.
    ImportResult legacy_import = imported;
    legacy_import.external_files.clear();
    legacy_import.report.erase(std::string(core::kMeshExternalFiles));
    std::map<std::string, std::string> legacy_blobs;
    const auto legacy = GltfDocument(legacy_import, path, legacy_blobs, gltf);
    const ResourceReader legacy_read = [&](const std::string& sha) { return legacy_blobs.at(sha); };
    CHECK(!legacy->snapshot().project->resources.contains(bin_sha));
    CHECK(RederiveMesh(*legacy->snapshot().project, legacy_read).mesh.hashes == imported.mesh.hashes);
    const auto missing_message = [&](bool beside_origin) {
        try {
            RederiveMesh(*legacy->snapshot().project, legacy_read, beside_origin);
        } catch (const MeshFileMissing& missing) {
            return std::string(missing.what());
        }
        throw Failure{"expected MeshFileMissing"};
    };
    CHECK(missing_message(false).find("quad.bin") != std::string::npos);

    std::filesystem::remove(dir / "source" / "quad.bin");
    CHECK(RederiveMesh(*current->snapshot().project, read).mesh.hashes == imported.mesh.hashes);
    CHECK(missing_message(true).find("gone") != std::string::npos);

    // The legacy project's mesh is replaced without re-deriving it: its set kept by material,
    // its bindings invalidated with the reason; the new mesh re-derives afterwards.
    const std::filesystem::path next = WriteFile(dir / "next" / "mesh.obj", Obj({{"head", "skin", 0.0f, 0.0f, 0.0f, 1.0f, 0.0f, 1.0f}}));
    const ReloadOutcome out = ReloadMesh(*legacy, core::MutationRequest{"reload_mesh", json::Object{}, "reload", legacy->revision()},
                                         next, Settings(), legacy_read, MeshSource{next.string(), std::string(kTime)});
    CHECK(out.outcome.result && out.outcome.result->status == core::ResultStatus::committed && out.report);
    CHECK(out.report->added.empty() && out.report->removed.empty());
    CHECK(legacy->snapshot().project->texture_sets.size() == 1);
    CHECK(legacy->snapshot().project->texture_sets[0].material_id == "skin");
    std::ifstream obj(next, std::ios::binary);
    legacy_blobs[core::Sha256Hex(std::string{std::istreambuf_iterator<char>(obj), std::istreambuf_iterator<char>()})] =
        Obj({{"head", "skin", 0.0f, 0.0f, 0.0f, 1.0f, 0.0f, 1.0f}});
    RederiveMesh(*legacy->snapshot().project, legacy_read, false);

    // A reload of the current project whose .gltf is byte-identical and whose buffer moves the
    // UVs: the old buffer's receipts are invalid though the mesh file's hash did not change.
    const core::ResultRecordHeader before_reload{1, "p", "c", "0.0.0", {imported.sha256, bin_sha}};
    CHECK(!ReceiptInvalidated(before_reload, *current->snapshot().project));
    const std::filesystem::path moved = WriteExternalGltf(dir / "moved");
    std::ifstream bin_in(dir / "moved" / "quad.bin", std::ios::binary);
    std::string bin{std::istreambuf_iterator<char>(bin_in), std::istreambuf_iterator<char>()};
    bin_in.close();
    const float shifted[8] = {0.0f, 0.5f, 0.5f, 0.5f, 0.5f, 0.0f, 0.0f, 0.0f};
    std::memcpy(bin.data() + 48, shifted, sizeof(shifted));
    WriteFile(dir / "moved" / "quad.bin", bin);
    const ReloadOutcome uv_only = ReloadMesh(*current, core::MutationRequest{"reload_mesh", json::Object{}, "uv", current->revision()},
                                             moved, Settings(), read, MeshSource{moved.string(), std::string(kTime)});
    CHECK(uv_only.outcome.result && uv_only.outcome.result->status == core::ResultStatus::committed && uv_only.report);
    CHECK(uv_only.report->mesh_from == uv_only.report->mesh_to);
    CHECK(uv_only.report->invalid_receipt_resources == std::vector<std::string>{bin_sha});
    CHECK(ReceiptInvalidated(before_reload, *current->snapshot().project));
    CHECK(current->snapshot().project->resources.contains(core::Sha256Hex(bin)));

    // A reload to a mesh without the set's material is refused before anything changes.
    const std::int64_t revision = legacy->revision();
    ImportResult stale = legacy_import;
    std::map<std::string, std::string> stale_blobs;
    const auto again = GltfDocument(stale, path, stale_blobs, gltf);
    const std::filesystem::path other = WriteFile(dir / "other" / "mesh.obj", Obj({{"head", "cloth", 0.0f, 0.0f, 0.0f, 1.0f, 0.0f, 1.0f}}));
    const ResourceReader stale_read = [&](const std::string& sha) { return stale_blobs.at(sha); };
    const ReloadOutcome refused = ReloadMesh(*again, core::MutationRequest{"reload_mesh", json::Object{}, "refused", again->revision()},
                                             other, Settings(), stale_read, MeshSource{other.string(), std::string(kTime)});
    CHECK(refused.outcome.result && refused.outcome.result->status == core::ResultStatus::failed);
    CHECK(std::string(ErrorOf<MaterialMappingError>(refused).what()).find("cannot be re-derived") != std::string::npos);
    CHECK(legacy->revision() == revision);
}

const std::vector<std::pair<std::string, std::function<void()>>>& Cases() {
    static const std::vector<std::pair<std::string, std::function<void()>>> cases = {
        {"identical_reload", IdenticalReload},
        {"moved_vertices", MovedVertices},
        {"uv_change_replaced", UvChangeReplaced},
        {"rename_fixture", RenameFixture},
        {"split_fixture", SplitFixture},
        {"merge_fixture", MergeFixture},
        {"added_and_removed_sets", AddedAndRemovedSets},
        {"failure_mid_reload", FailureMidReload},
        {"gltf_external_buffer", GltfExternalBuffer},
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
        } catch (const Failure& failure) {
            ++failed;
            std::printf("FAIL %s: %s\n", name.c_str(), failure.message.c_str());
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

}  // namespace

int main(int argc, char** argv) {
    const std::vector<std::string> args(argv + 1, argv + argc);
    if (!args.empty() && args[0] == "run") return Run(args.size() > 1 ? args[1] : std::string());
    std::fprintf(stderr, "usage: uzp-mesh-reload-tests run [case]\n");
    return 2;
}
