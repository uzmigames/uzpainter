#include "store/census.h"

#include <windows.h>

#include <algorithm>
#include <cctype>
#include <chrono>
#include <cmath>
#include <fstream>
#include <functional>
#include <memory>
#include <set>
#include <sstream>
#include <utility>

#include "store/blobs.h"
#include "store/container.h"
#include "store/integrity.h"
#include "store/planes.h"
#include "store/project_store.h"
#include "uzp_core/document/document.h"
#include "uzp_core/manifest/sha256.h"
#include "uzp_core/types/errors.h"

namespace uzp::store {

using core::json::Array;
using core::json::Object;
using core::json::Value;
namespace fs = std::filesystem;

namespace {

std::string Utf8(const fs::path& path) {
    const std::u8string text = path.u8string();
    return std::string(text.begin(), text.end());
}

fs::path FromUtf8(std::string_view text) { return fs::path(std::u8string(text.begin(), text.end())); }

std::string ReadFile(const fs::path& path) {
    std::ifstream file(path, std::ios::binary);
    if (!file) throw StoreError(StoreError::Code::io, "census: cannot read " + Utf8(path));
    std::ostringstream bytes;
    bytes << file.rdbuf();
    if (file.bad()) throw StoreError(StoreError::Code::io, "census: cannot read " + Utf8(path));
    return bytes.str();
}

const Value& Required(const Value& value, std::string_view key, std::string_view where) {
    const auto* object = std::get_if<Object>(&value.data);
    const auto it = object ? object->find(key) : Object::const_iterator{};
    if (object == nullptr || it == object->end()) {
        throw core::ValueError("census inputs: " + std::string(where) + " has no " + std::string(key));
    }
    return it->second;
}

std::string RequiredText(const Value& value, std::string_view key, std::string_view where) {
    const Value& member = Required(value, key, where);
    if (!member.IsString()) throw core::ValueError("census inputs: " + std::string(where) + "." + std::string(key) + " is not a string");
    return std::get<std::string>(member.data);
}

const Array& RequiredList(const Value& value, std::string_view key, std::string_view where) {
    const Value& member = Required(value, key, where);
    if (!member.IsArray()) throw core::ValueError("census inputs: " + std::string(where) + "." + std::string(key) + " is not a list");
    return std::get<Array>(member.data);
}

fs::path Existing(const fs::path& root, const std::string& relative) {
    const fs::path path = root / FromUtf8(relative);
    std::error_code ec;
    if (!fs::exists(path, ec)) throw StoreError(StoreError::Code::io, "census: dependency " + Utf8(path) + " does not exist");
    return path;
}

std::string MimeOf(const fs::path& path) {
    std::string ext = Utf8(path.extension());
    std::transform(ext.begin(), ext.end(), ext.begin(), [](char c) { return static_cast<char>(std::tolower(static_cast<unsigned char>(c))); });
    if (ext == ".png") return "image/png";
    if (ext == ".exr") return "image/x-exr";
    if (ext == ".fbx") return "model/fbx";
    if (ext == ".obj") return "model/obj";
    if (ext == ".mtl") return "model/mtl";
    if (ext == ".glb") return "model/gltf-binary";
    if (ext == ".hdr") return "image/vnd.radiance";
    return "application/octet-stream";
}

/// A deterministic RFC 4122-shaped project uuid for `id`.
std::string UuidFor(const std::string& id) {
    std::string hex = core::Sha256Hex("uzpainter-store-census/" + id).substr(0, 32);
    hex[12] = '4';
    hex[16] = '8';
    return hex.substr(0, 8) + "-" + hex.substr(8, 4) + "-" + hex.substr(12, 4) + "-" + hex.substr(16, 4) + "-" + hex.substr(20, 12);
}

// ── Measuring ──────────────────────────────────────────────────────────────────────────────

struct Probe {
    std::int64_t file_bytes = 0;
    std::int64_t io_written = 0;
    std::chrono::steady_clock::time_point at;
};

Probe Take(const fs::path& path) {
    Probe probe;
    std::error_code ec;
    const std::uintmax_t size = fs::file_size(path, ec);
    probe.file_bytes = ec ? 0 : static_cast<std::int64_t>(size);
    IO_COUNTERS io{};
    if (GetProcessIoCounters(GetCurrentProcess(), &io)) probe.io_written = static_cast<std::int64_t>(io.WriteTransferCount);
    probe.at = std::chrono::steady_clock::now();
    return probe;
}

double Seconds(const Probe& from, const Probe& to) { return std::chrono::duration<double>(to.at - from.at).count(); }

/// Seconds rounded to microseconds, so the report does not carry clock noise digits.
Value Rounded(double seconds) { return Value(std::round(seconds * 1e6) / 1e6); }

Object Step(const Probe& from, const Probe& to) {
    return Object{{"seconds", Rounded(Seconds(from, to))},
                  {"file_growth_bytes", to.file_bytes - from.file_bytes},
                  {"io_bytes_written", to.io_written - from.io_written}};
}

/// {mean, max, total} of `values`.
Object Stats(const std::vector<double>& values, bool integral) {
    double total = 0, max = 0;
    for (double v : values) {
        total += v;
        max = std::max(max, v);
    }
    const double mean = values.empty() ? 0.0 : total / static_cast<double>(values.size());
    if (integral) {
        return Object{{"mean", Value(std::round(mean * 10) / 10)},
                      {"max", static_cast<std::int64_t>(max)},
                      {"total", static_cast<std::int64_t>(total)}};
    }
    return Object{{"mean", Rounded(mean)}, {"max", Rounded(max)}, {"total", Rounded(total)}};
}

std::int64_t Scalar(Container& container, const std::string& sql) {
    Statement q(container, sql);
    return q.Step() && !q.IsNull(0) ? q.Int(0) : 0;
}

/// Every 64-hex string `value` holds.
void Hashes(const Value& value, std::set<std::string, std::less<>>& out) {
    if (const auto* text = std::get_if<std::string>(&value.data)) {
        if (core::IsSha256Hex(*text)) out.insert(*text);
    } else if (const auto* array = std::get_if<Array>(&value.data)) {
        for (const Value& item : *array) Hashes(item, out);
    } else if (const auto* object = std::get_if<Object>(&value.data)) {
        for (const auto& [key, member] : *object) {
            if (core::IsSha256Hex(key)) out.insert(key);
            Hashes(member, out);
        }
    }
}

/// What the file keeps for history beyond the current revision: the other retained manifests,
/// the blobs only they reach and the operation rows.
Object RetainedHistory(Container& container) {
    const std::int64_t current = ReadCurrentRevision(container);
    const Value manifest = core::json::Parse(ReadManifestText(container, current));
    std::set<std::string, std::less<>> live;
    Hashes(manifest, live);
    for (const ManifestBinding& binding : ManifestPlaneBindings(manifest)) {
        if (!binding.version) continue;
        for (const ChunkRow& chunk : ReadChunkRows(container, binding.version->version_id)) live.insert(chunk.sha256);
    }
    std::int64_t blob_bytes = 0;
    Statement q(container, "SELECT sha256, zstd_size FROM blob");
    while (q.Step()) {
        if (live.count(q.Text(0)) == 0) blob_bytes += q.Int(1);
    }
    const std::int64_t revisions = Scalar(container, "SELECT COUNT(*) FROM revision") - 1;
    const std::int64_t manifests =
        Scalar(container, "SELECT SUM(LENGTH(manifest)) FROM revision WHERE revision <> " + std::to_string(current));
    const std::int64_t operations = Scalar(container, "SELECT SUM(LENGTH(outcome)) FROM operation");
    return Object{{"revisions", revisions},
                  {"manifest_bytes", manifests},
                  {"blob_bytes", blob_bytes},
                  {"operation_bytes", operations},
                  {"total_bytes", manifests + blob_bytes + operations}};
}

// ── The scripted project ───────────────────────────────────────────────────────────────────

struct Session {
    std::unique_ptr<ProjectStore> store;
    std::unique_ptr<core::Document> doc;

    void Close() {
        doc.reset();
        if (store) store->Close();
        store.reset();
    }
};

void Mutate(Session& s, const std::string& key, const std::function<void(core::Edit&)>& call) {
    const core::RequestOutcome outcome =
        s.store->Submit(*s.doc, core::MutationRequest{"census", core::json::Object{{"step", key}}, key, s.doc->revision()}, call);
    if (outcome.decision.admission != core::Admission::execute || !outcome.result ||
        outcome.result->status != core::ResultStatus::committed) {
        throw StoreError(StoreError::Code::conflict, "census: mutation " + key + " did not commit");
    }
}

core::ResourceMeta Meta(core::Project& project, const fs::path& path, std::int64_t size, const std::string& usage) {
    core::ResourceMeta meta;
    meta.id = project.AllocateId();
    meta.name = Utf8(path.filename());
    meta.mime = MimeOf(path);
    meta.size = size;
    meta.usage = usage;
    meta.origin = "import";
    meta.imported_at = UtcNow();
    meta.color_space = "Raw";
    return meta;
}

/// A disc of paint in the plane (`TexelBytes(format)` bytes per texel, every byte the same).
PlaneImage Disc(int edge, core::ChannelFormat format, double cx, double cy, double radius, const PlaneImage* base) {
    const std::size_t bpt = TexelBytes(format);
    PlaneImage image = base ? *base : PlaneImage{edge, edge, format, std::string(static_cast<std::size_t>(edge) * edge * bpt, '\0')};
    const int x0 = std::max(0, static_cast<int>(cx - radius)), x1 = std::min(edge - 1, static_cast<int>(cx + radius));
    const int y0 = std::max(0, static_cast<int>(cy - radius)), y1 = std::min(edge - 1, static_cast<int>(cy + radius));
    for (int y = y0; y <= y1; ++y) {
        for (int x = x0; x <= x1; ++x) {
            const double d = std::hypot(x - cx, y - cy) / radius;
            if (d > 1.0) continue;
            const char value = static_cast<char>(64 + static_cast<int>(160 * (1.0 - d)));
            std::fill_n(image.texels.data() + (static_cast<std::size_t>(y) * edge + x) * bpt, bpt, value);
        }
    }
    return image;
}

}  // namespace

std::vector<CensusProjectInput> ReadCensusInputs(const Value& inputs, const fs::path& assets_root) {
    if (RequiredText(inputs, "schema", "the document") != kCensusInputsSchema) {
        throw core::ValueError("census inputs: schema is not " + std::string(kCensusInputsSchema));
    }
    std::vector<CensusProjectInput> out;
    for (const Value& entry : RequiredList(inputs, "projects", "the document")) {
        CensusProjectInput project;
        project.id = RequiredText(entry, "id", "a project");
        // The id names the project's folder in the work dir, which the census replaces.
        if (project.id.empty() || !std::all_of(project.id.begin(), project.id.end(), [](char c) {
                return std::isalnum(static_cast<unsigned char>(c)) || c == '_' || c == '-';
            })) {
            throw core::ValueError("census inputs: project id '" + project.id + "' is not a plain name ([A-Za-z0-9_-]+)");
        }
        const std::string where = "project " + project.id;
        const std::string spp = RequiredText(entry, "spp", where);
        if (!spp.empty()) project.spp = assets_root / FromUtf8(spp);
        project.mesh = Existing(assets_root, RequiredText(entry, "mesh", where));
        for (const Value& set : RequiredList(entry, "texture_sets", where)) {
            CensusSetInput input;
            input.name = RequiredText(set, "name", where + " texture set");
            const Value& resolution = Required(set, "resolution", where + " texture set");
            if (!resolution.IsInt()) throw core::ValueError("census inputs: " + where + ": resolution is not an integer");
            input.resolution = static_cast<int>(std::get<std::int64_t>(resolution.data));
            const Value& maps = Required(set, "mesh_maps", where + " texture set");
            if (!maps.IsObject()) throw core::ValueError("census inputs: " + where + ": mesh_maps is not an object");
            for (const auto& [usage, file] : std::get<Object>(maps.data)) {
                const auto parsed = core::FromString<core::MeshMapUsage>(usage);
                if (!parsed || !file.IsString()) throw core::ValueError("census inputs: " + where + ": invalid mesh map " + usage);
                input.mesh_maps[*parsed] = Existing(assets_root, std::get<std::string>(file.data));
            }
            project.sets.push_back(std::move(input));
        }
        if (project.sets.empty()) throw core::ValueError("census inputs: " + where + " has no texture set");
        for (const Value& file : RequiredList(entry, "resources", where)) {
            if (!file.IsString()) throw core::ValueError("census inputs: " + where + ": a resource is not a string");
            const fs::path path = Existing(assets_root, std::get<std::string>(file.data));
            if (fs::is_directory(path)) {
                std::vector<fs::path> files;
                for (const fs::directory_entry& item : fs::directory_iterator(path)) {
                    if (item.is_regular_file()) files.push_back(item.path());
                }
                std::sort(files.begin(), files.end());
                project.resources.insert(project.resources.end(), files.begin(), files.end());
            } else {
                project.resources.push_back(path);
            }
        }
        for (const Value& id : RequiredList(entry, "not_measured", where)) {
            if (!id.IsString()) throw core::ValueError("census inputs: " + where + ": not_measured holds a non-string");
            project.not_measured.push_back(std::get<std::string>(id.data));
        }
        out.push_back(std::move(project));
    }
    return out;
}

Value CensusProject(const CensusProjectInput& input, const CensusOptions& options) {
    const fs::path dir = options.work_dir / FromUtf8(input.id);
    fs::remove_all(dir);
    fs::create_directories(dir);
    const fs::path path = dir / FromUtf8(input.id + ".uzp");

    // The initial project: every dependency embedded once (deduplicated by SHA-256).
    core::DocumentState state;
    state.project_uuid = UuidFor(input.id);
    core::Project& p = state.project;
    p.versions.app_version = "0.0.0";
    // New projects carry the evaluator's current profile (`evaluator::kCurrentProfile`,
    // src/evaluator/profile.h), spelled out because the store does not depend on the evaluator.
    p.versions.evaluator_profile = "painter-12.1-isolated-linear";
    CreateOptions create;
    std::set<std::string, std::less<>> embedded;
    std::int64_t dependency_files = 0, dependency_bytes = 0;
    auto add = [&](const fs::path& file, const std::string& usage) {
        std::string bytes = ReadFile(file);
        const std::string sha256 = core::Sha256Hex(bytes);
        p.resources[sha256].push_back(Meta(p, file, static_cast<std::int64_t>(bytes.size()), usage));
        if (embedded.insert(sha256).second) {
            ++dependency_files;
            dependency_bytes += static_cast<std::int64_t>(bytes.size());
            create.resources.push_back(PendingContent::Bytes{std::move(bytes), MimeOf(file)});
        }
        return sha256;
    };
    p.mesh = core::MeshReference{add(input.mesh, "MESH"), {}, {}};
    for (std::size_t i = 0; i < input.sets.size(); ++i) {
        const CensusSetInput& in = input.sets[i];
        core::TextureSet set;
        set.id = p.AllocateId();
        set.name = in.name;
        set.original_name = in.name;
        set.material_id = "material-" + std::to_string(i);
        set.resolution = core::Resolution{in.resolution, in.resolution, {}};
        set.uv_tiles = {core::UVTile{p.AllocateId(), 1001, {}}};
        core::Stack stack;
        stack.id = p.AllocateId();
        stack.channels[core::ChannelType::BaseColor] = core::Channel{core::ChannelFormat::sRGB8, "", {}};
        stack.channels[core::ChannelType::Roughness] = core::Channel{core::ChannelFormat::L8, "", {}};
        stack.channels[core::ChannelType::Metallic] = core::Channel{core::ChannelFormat::L8, "", {}};
        stack.channels[core::ChannelType::Normal] = core::Channel{core::ChannelFormat::RGB16F, "", {}};
        stack.channels[core::ChannelType::Height] = core::Channel{core::ChannelFormat::L16F, "", {}};
        set.stacks = {stack};
        for (const auto& [usage, file] : in.mesh_maps) {
            core::MeshMapBinding binding;
            binding.resource = add(file, "TEXTURE");
            binding.format = usage == core::MeshMapUsage::Normal ? core::ChannelFormat::RGB16 : core::ChannelFormat::L16;
            binding.color_space = "Raw";
            core::ImportedProvenance provenance;
            provenance.source_path = Utf8(file.filename());
            provenance.source_sha256 = binding.resource;
            binding.provenance = provenance;
            set.mesh_maps[usage] = binding;
        }
        p.texture_sets.push_back(std::move(set));
    }
    for (const fs::path& file : input.resources) add(file, "TEXTURE");
    const core::Id set_id = p.texture_sets.front().id;
    const core::Id stack_id = p.texture_sets.front().stacks.front().id;
    const int edge = input.sets.front().resolution;
    const core::InsertPosition top = core::InsertPosition::FromStack(set_id, stack_id);

    Object report{{"id", input.id}};
    std::error_code ec;
    const std::uintmax_t spp = input.spp.empty() ? 0 : fs::file_size(input.spp, ec);
    const bool has_spp = !input.spp.empty() && !ec;
    report["spp_bytes"] = has_spp ? Value(static_cast<std::int64_t>(spp)) : Value();
    Array not_measured;
    for (const std::string& id : input.not_measured) not_measured.push_back(id);
    report["dependencies"] = Object{{"files", dependency_files}, {"bytes", dependency_bytes}, {"not_measured", std::move(not_measured)}};

    Session s;
    // 1. First save.
    Probe before = Take(path);
    s.store = ProjectStore::Create(path, state, create);
    s.doc = std::make_unique<core::Document>(std::move(state));
    s.store->Attach(*s.doc);
    s.store->Save(*s.doc);
    report["first_save"] = Step(before, Take(path));

    // 2. One fill layer, then one-parameter edits of its BaseColor opacity.
    core::Id layer = core::kNoId;
    before = Take(path);
    Mutate(s, "layer-insert", [&](core::Edit& e) { layer = e.Insert(top, core::NodeType::FillLayer, "Census fill"); });
    report["layer_insert"] = Step(before, Take(path));
    std::vector<double> growth, written, seconds;
    const std::int64_t first_edit = s.doc->revision() + 1;
    for (int i = 0; i < options.one_parameter_edits; ++i) {
        before = Take(path);
        Mutate(s, "opacity-" + std::to_string(i), [&](core::Edit& e) {
            for (core::Layer& node : e.project().texture_sets.front().stacks.front().root_layers) {
                if (node.uid == layer) node.blending[core::ChannelType::BaseColor] = core::Blending{core::BlendingMode::Normal, 0.99 - 0.01 * i, {}};
            }
        });
        const Probe after = Take(path);
        growth.push_back(static_cast<double>(after.file_bytes - before.file_bytes));
        written.push_back(static_cast<double>(after.io_written - before.io_written));
        seconds.push_back(Seconds(before, after));
    }
    const std::int64_t manifest_mean =
        options.one_parameter_edits > 0
            ? Scalar(s.store->container(), "SELECT AVG(LENGTH(manifest)) FROM revision WHERE revision >= " + std::to_string(first_edit))
            : 0;
    report["one_parameter_edits"] = Object{{"count", std::int64_t{options.one_parameter_edits}},
                                           {"file_growth_bytes", Stats(growth, true)},
                                           {"io_bytes_written", Stats(written, true)},
                                           {"seconds", Stats(seconds, false)},
                                           {"manifest_stored_bytes_mean", manifest_mean}};

    // 3. A raster plane on the first set, then an edit inside chunk (0, 0) only.
    const core::ChannelFormat format = core::ChannelFormat::sRGB8;
    const PlaneImage painted = Disc(edge, format, edge * 0.3, edge * 0.3, edge * 0.15, nullptr);
    const double mark = std::min(edge, kChunkSize) / 2.0;
    const PlaneImage edited = Disc(edge, format, mark, mark, mark / 4.0, &painted);
    core::Id plane = core::kNoId;
    const std::int64_t chunk_bytes_before = Scalar(s.store->container(), "SELECT SUM(zstd_size) FROM blob WHERE mime = '" + std::string(kChunkMime) + "'");
    before = Take(path);
    Mutate(s, "plane-create", [&](core::Edit& e) {
        const core::Id paint = e.Insert(top, core::NodeType::PaintLayer, "Census paint");
        plane = s.store->CreatePlane(e, PlaneSpec{paint, core::ChannelType::BaseColor, 1001, format, edge, edge});
        s.store->WritePlane(e, plane, painted);
    });
    Object create_step = Step(before, Take(path));
    const std::int64_t chunk_bytes_created = Scalar(s.store->container(), "SELECT SUM(zstd_size) FROM blob WHERE mime = '" + std::string(kChunkMime) + "'");
    create_step["stored_chunk_bytes"] = chunk_bytes_created - chunk_bytes_before;
    before = Take(path);
    Mutate(s, "plane-edit", [&](core::Edit& e) { s.store->WritePlane(e, plane, edited); });
    Object edit_step = Step(before, Take(path));
    edit_step["stored_chunk_bytes"] =
        Scalar(s.store->container(), "SELECT SUM(zstd_size) FROM blob WHERE mime = '" + std::string(kChunkMime) + "'") - chunk_bytes_created;
    report["raster_plane"] = Object{{"format", std::string(core::ToString(format))},
                                    {"width", std::int64_t{edge}},
                                    {"height", std::int64_t{edge}},
                                    {"create", std::move(create_step)},
                                    {"edit", std::move(edit_step)}};

    // 4. Save, close, reopen, compact.
    s.store->Save(*s.doc);
    s.Close();
    before = Take(path);
    {
        ProjectStore::Opened opened = ProjectStore::Open(path);
        if (!opened.report.ok()) throw StoreError(StoreError::Code::corrupt, "census: the reopened project does not verify");
        s.store = std::move(opened.store);
        s.doc = std::make_unique<core::Document>(std::move(opened.state));
        s.store->Attach(*s.doc);
    }
    report["reopen_seconds"] = Rounded(Seconds(before, Take(path)));
    before = Take(path);
    const CompactResult compacted = s.store->Compact(*s.doc);
    const Probe after = Take(path);
    report["compaction"] = Object{{"seconds", Rounded(Seconds(before, after))},
                                  {"file_bytes_before", static_cast<std::int64_t>(compacted.bytes_before)},
                                  {"file_bytes_after", static_cast<std::int64_t>(compacted.bytes_after)},
                                  {"collapsed_revisions", static_cast<std::int64_t>(compacted.collapsed.size())}};

    // 5. Retained history and the project bytes.
    report["retained_history"] = RetainedHistory(s.store->container());
    s.Close();
    const auto project_bytes = static_cast<std::int64_t>(fs::file_size(path));
    report["project_bytes"] = project_bytes;
    report["external_dependency_bytes"] = std::int64_t{0};  // portable: every dependency is embedded
    if (has_spp && spp > 0) {
        const double ratio = static_cast<double>(project_bytes) / static_cast<double>(spp);
        report["ratio_to_spp"] = Value(std::round(ratio * 1e6) / 1e6);
        report["within_candidate_budget"] = ratio <= kCandidateBudget;
    } else {
        report["ratio_to_spp"] = Value();
        report["within_candidate_budget"] = Value();
    }
    return report;
}

Value RunCensus(const std::vector<CensusProjectInput>& inputs, const CensusOptions& options) {
    Array projects;
    for (const CensusProjectInput& input : inputs) projects.push_back(CensusProject(input, options));
    return Object{
        {"schema", std::string(kCensusSchema)},
        {"task", "phase1.7_store-inspect-census"},
        {"date", UtcNow().substr(0, 10)},
        {"candidate_budget_fraction", kCandidateBudget},
        {"procedure", Object{{"one_parameter_edits", std::int64_t{options.one_parameter_edits}},
                             {"raster_plane_format", "sRGB8"},
                             {"zstd_level", std::int64_t{3}},
                             {"portable", true}}},
        {"projects", std::move(projects)},
    };
}

}  // namespace uzp::store
