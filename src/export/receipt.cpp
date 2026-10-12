#include "export/receipt.h"

#include "evaluator/dag.h"
#include "uzp_core/document/nodes.h"
#include "uzp_core/manifest/sha256.h"
#include "uzp_core/types/errors.h"
#include "uzp_core/types/receipt.h"

#include <algorithm>
#include <filesystem>
#include <map>
#include <optional>

namespace uzp::exporter {

namespace {

namespace json = core::json;
using evaluator::DagLayer;
using evaluator::DagList;
using evaluator::DagSource;
using evaluator::DiagnosticSource;

/// The gap a consumer must close itself (08-export.md §4, §5.1 rows 2 and 8): SpecularWeight has
/// no slot in the consumers' materials, and its stated mapping belongs to the consumer.
constexpr std::string_view kSpecularWeightGap =
    "SpecularWeight has no slot in the consumer's material: its mapping (Specular = 0.5 x "
    "SpecularWeight in the hat v8 report) belongs to the consumer and is not applied by the export";

std::string BitDepthOf(const PlannedFile& file) {
    return file.parameters ? std::string(BitDepthName(file.parameters->bitDepth)) : std::string();
}

/// Assets3D's `map_format.bit_depth` (8, 16 or 32).
int ManifestBitDepth(BitDepth depth) {
    switch (depth) {
        case BitDepth::u8: return 8;
        case BitDepth::u16:
        case BitDepth::f16: return 16;
        case BitDepth::f32: return 32;
    }
    return 0;
}

/// Every image file this build writes holds linear values: legacy colour management, data
/// channels and normals linear, an sRGB8 User channel as its linear operand; an sRGB-encoded
/// export is refused before writing (encode.h, decision 090).
constexpr std::string_view kWrittenColourSpace = "linear";

/// A key of Assets3D's manifest `files` (`^[a-z0-9][a-z0-9_-]*$`) for `text`, unique in `used`.
std::string ManifestKey(std::string_view text, std::set<std::string>& used) {
    std::string key;
    for (const char c : text) {
        const char lower = (c >= 'A' && c <= 'Z') ? static_cast<char>(c - 'A' + 'a') : c;
        const bool keep =
            (lower >= 'a' && lower <= 'z') || (lower >= '0' && lower <= '9') || lower == '_' || lower == '-';
        key.push_back(keep ? lower : '-');
    }
    if (key.empty() || key.front() == '_' || key.front() == '-') key.insert(key.begin(), 'f');
    std::string unique = key;
    for (int n = 2; used.contains(unique); ++n) unique = key + "-" + std::to_string(n);
    used.insert(unique);
    return unique;
}

json::Object Sha256Field(const std::optional<std::string>& value, bool verified) {
    return json::Object{{"algorithm", "sha256"},
                        {"value", value ? json::Value(*value) : json::Value(nullptr)},
                        {"verification", verified ? "verified" : "not-verified"}};
}

json::Value NormalJson(const std::optional<evaluator::NormalTag>& tag) {
    if (!tag) return nullptr;
    json::Value relief = nullptr;
    if (tag->relief) {
        relief = json::Object{{"revision", tag->relief->revision},
                              {"height_hash", tag->relief->heightHash},
                              {"method", std::string(core::ToString(tag->relief->method))}};
    }
    return json::Object{{"role", std::string(core::ToString(tag->role))}, {"relief", std::move(relief)}};
}

json::Array ConsumerGaps(const PlannedFile& file) {
    json::Array gaps;
    for (const PlannedChannel& channel : file.channels) {
        if (channel.source.type == SourceType::documentMap &&
            channel.source.channel == core::ChannelType::SpecularWeight) {
            gaps.push_back(json::Object{{"channel", "SpecularWeight"}, {"gap", std::string(kSpecularWeightGap)}});
            break;
        }
    }
    return gaps;
}

/// The imported mesh's file name (its import report's source name), when it has one.
std::optional<std::string> MeshFileName(const core::Project& project) {
    if (!project.mesh) return std::nullopt;
    const auto source = project.mesh->import_report.find("source");
    if (source == project.mesh->import_report.end() || !source->second.IsObject()) return std::nullopt;
    const json::Object& o = std::get<json::Object>(source->second.data);
    const auto name = o.find("name");
    if (name == o.end() || !name->second.IsString()) return std::nullopt;
    const std::string& text = std::get<std::string>(name->second.data);
    return IsDeliveryPath(text) ? std::optional<std::string>(text) : std::nullopt;
}

// ── Resources read ──────────────────────────────────────────────────────────

struct ResourceWalk {
    std::set<std::string> hashes;
    bool geometry = false;

    void Source(const std::optional<DagSource>& source) {
        if (source && source->kind == DagSource::Kind::Bitmap) hashes.insert(source->sha256);
    }
    void Effects(const std::vector<evaluator::DagEffect>& effects) {
        for (const evaluator::DagEffect& effect : effects) Source(effect.source);
    }
    void Layer(const DagLayer& layer) {
        if (layer.maskStack) {
            Effects(layer.maskStack->effects);
            if (layer.maskStack->geometry) geometry = true;
        }
        Source(layer.source);
        Effects(layer.effects);
        if (layer.group) List(*layer.group);
    }
    void List(const DagList& list) {
        for (const DagLayer& layer : list.layers) Layer(layer);
    }
};

/// The layers from a root layer of `layers` to `uid`, outermost first.
bool PathTo(const std::vector<core::Layer>& layers, core::Id uid, std::vector<core::Id>& path) {
    for (const core::Layer& layer : layers) {
        path.push_back(layer.uid);
        if (layer.uid == uid || PathTo(layer.children, uid, path)) return true;
        path.pop_back();
    }
    return false;
}

}  // namespace

bool IsDeliveryPath(std::string_view path) {
    if (path.empty() || path.front() == '/' || path.find('\\') != std::string_view::npos ||
        path.find(':') != std::string_view::npos) {
        return false;
    }
    size_t start = 0;
    while (start <= path.size()) {
        const size_t end = std::min(path.find('/', start), path.size());
        const std::string_view part = path.substr(start, end - start);
        if (part.empty() || part == "." || part == "..") return false;
        start = end + 1;
    }
    return true;
}

render::Result<std::set<std::string>> ReadResourceHashes(const core::Project& project, const ExportPlan& plan,
                                                         const evaluator::TemplateLibrary& templates,
                                                         std::string_view templateId) {
    ResourceWalk walk;
    std::set<std::tuple<core::Id, core::Id, core::ChannelType>> walked;
    const auto channel = [&](const PlannedFile& file, core::ChannelType type) -> render::Result<void> {
        if (!walked.insert({file.textureSetId, file.stackId, type}).second) return {};
        render::Result<evaluator::ChannelDag> dag =
            evaluator::BuildDag(project, file.textureSetId, file.stackId, type, templates, templateId);
        if (!dag) return render::Unexpected(dag.error());
        walk.List(dag->root);
        return {};
    };
    const auto normals = [&](const PlannedFile& file) -> render::Result<void> {
        const core::Stack* stack = core::FindStack(project, file.textureSetId, file.stackId);
        for (const core::ChannelType type : {core::ChannelType::Height, core::ChannelType::Normal}) {
            if (stack == nullptr || !stack->channels.contains(type)) continue;
            render::Result<void> read = channel(file, type);
            if (!read) return read;
        }
        return {};
    };
    const auto map = [&](const PlannedFile& file, const evaluator::DiagnosticMapId& id) -> render::Result<void> {
        return id.kind == evaluator::DiagnosticMapId::Kind::Channel ? channel(file, id.channel) : normals(file);
    };
    const auto meshMap = [&](const PlannedFile& file, core::MeshMapUsage usage) {
        for (const core::TextureSet& set : project.texture_sets) {
            if (set.id != file.textureSetId) continue;
            if (const auto binding = set.mesh_maps.find(usage); binding != set.mesh_maps.end()) {
                walk.hashes.insert(binding->second.resource);
            }
        }
    };
    // The masks of a diagnostic's material and of every group enclosing it.
    const auto materialMasks = [&](const PlannedFile& file, core::Id material) -> render::Result<void> {
        const core::Stack* stack = core::FindStack(project, file.textureSetId, file.stackId);
        std::vector<core::Id> path;
        if (stack == nullptr || stack->channels.empty() || !PathTo(stack->root_layers, material, path)) return {};
        render::Result<evaluator::ChannelDag> frame = evaluator::BuildDag(
            project, file.textureSetId, file.stackId, stack->channels.begin()->first, templates, templateId);
        if (!frame) return render::Unexpected(frame.error());
        for (const core::Id uid : path) {
            render::Result<DagLayer> layer = evaluator::BuildLayerMask(project, *frame, uid);
            if (!layer) return render::Unexpected(layer.error());
            walk.Layer(*layer);
        }
        return {};
    };
    for (const PlannedFile& file : plan.files) {
        if (file.layout != FileLayout::Statistics) walk.geometry = true;  // the padding's UV coverage
        for (const PlannedChannel& planned : file.channels) {
            const PlannedSource& s = planned.source;
            render::Result<void> read{};
            switch (s.type) {
                case SourceType::documentMap: read = channel(file, *s.channel); break;
                case SourceType::virtualMap: read = normals(file); break;
                case SourceType::meshMap: meshMap(file, *s.meshMap); break;
                case SourceType::defaultMap: break;
                case SourceType::diagnosticMap: {
                    const DiagnosticSource& d = *s.diagnostic;
                    switch (d.kind) {
                        case DiagnosticSource::Kind::Isolated:
                        case DiagnosticSource::Kind::Contribution: read = map(file, d.map); break;
                        case DiagnosticSource::Kind::RegionStats:
                            read = map(file, d.map);
                            if (read) read = materialMasks(file, d.node);
                            break;
                        case DiagnosticSource::Kind::MaterialMask: read = materialMasks(file, d.node); break;
                        case DiagnosticSource::Kind::MaterialView:
                        case DiagnosticSource::Kind::MaterialLeaks:
                            read = materialMasks(file, d.node);
                            if (!read) break;
                            if (d.view == evaluator::MaterialViewKind::ID) {
                                meshMap(file, core::MeshMapUsage::ID);
                            } else {
                                read = channel(file, evaluator::MaterialViewChannel(d.view));
                            }
                            break;
                    }
                    break;
                }
            }
            if (!read) return render::Unexpected(read.error());
        }
    }
    if (walk.geometry && project.mesh) walk.hashes.insert(project.mesh->resource);
    return std::move(walk.hashes);
}

json::Object BuildReceipt(const ReceiptInputs& in) {
    const ExportPlan& plan = in.plan;
    core::ResultRecordHeader header;
    header.revision = in.revision;
    header.evaluator_profile = in.project.versions.evaluator_profile;
    header.compat_profile = in.project.versions.compat_profile;
    header.app_version = in.identity.appVersion;
    header.resource_hashes = in.resourceHashes;
    json::Object receipt = core::HeaderToJson(header);

    const std::string planText = json::WriteCanonical(PlanJson(plan));
    std::set<std::string> used{"project", "mesh", "export-plan"};
    json::Object manifestFiles;
    manifestFiles["export-plan"] = json::Object{{"path", "plan.json"},
                                                {"role", "configuration"},
                                                {"sha256", Sha256Field(core::Sha256Hex(planText), true)},
                                                {"bytes", static_cast<std::int64_t>(planText.size())}};
    const std::string projectName =
        in.projectPath.empty() ? std::string("Untitled")
                               : std::filesystem::path(in.projectPath).filename().generic_string();
    manifestFiles["project"] = json::Object{{"path", projectName},
                                            {"role", "painter-project"},
                                            {"sha256", Sha256Field(std::nullopt, false)},
                                            {"bytes", nullptr},
                                            {"revision", std::to_string(in.revision)}};
    json::Array sources{"project"};
    if (const std::optional<std::string> mesh = MeshFileName(in.project)) {
        manifestFiles["mesh"] = json::Object{{"path", *mesh},
                                             {"role", "source"},
                                             {"sha256", Sha256Field(in.project.mesh->resource, false)},
                                             {"bytes", nullptr}};
        sources.emplace_back("mesh");
    }

    json::Array files;
    json::Array outputs;
    json::Object maps;
    json::Array openItems;
    std::set<std::string> presets;
    for (size_t i = 0; i < plan.files.size(); ++i) {
        const PlannedFile& file = plan.files[i];
        const EncodedFile& encoded = in.encoded[i];
        const bool statistics = file.layout == FileLayout::Statistics;
        const std::string sha = core::Sha256Hex(encoded.bytes);
        const std::string key = ManifestKey(file.relativePath, used);
        json::Array channels;
        for (const PlannedChannel& c : file.channels) {
            // A dropped all-opaque alpha is not a channel of the file.
            if (c.dest == ChannelLetter::A && encoded.layout != file.layout) continue;
            channels.push_back(json::Object{{"dest_channel", std::string(ChannelLetterName(c.dest))},
                                            {"src_channel", std::string(ChannelLetterName(c.src))},
                                            {"src_map_type", std::string(SourceTypeName(c.source.type))},
                                            {"src_map_name", c.source.name}});
        }
        json::Array gaps = ConsumerGaps(file);
        for (const json::Value& gap : gaps) {
            openItems.emplace_back(file.relativePath + ": " +
                                   std::get<std::string>(std::get<json::Object>(gap.data).at("gap").data));
        }
        const json::Array size{static_cast<std::int64_t>(file.width), static_cast<std::int64_t>(file.height)};
        files.push_back(json::Object{
            {"path", file.relativePath},
            {"key", key},
            {"root_path", file.rootPath},
            {"preset", file.preset},
            {"bytes", static_cast<std::int64_t>(encoded.bytes.size())},
            {"sha256", sha},
            {"format", statistics ? std::string("json") : std::string(FileFormatName(file.parameters->fileFormat))},
            {"bit_depth", statistics ? json::Value(nullptr) : json::Value(BitDepthOf(file))},
            {"colour_space", statistics ? json::Value(nullptr) : json::Value(kWrittenColourSpace)},
            {"size", size},
            {"layout", std::string(FileLayoutName(encoded.layout))},
            {"channels", std::move(channels)},
            {"normal", NormalJson(encoded.normalTag)},
            {"consumer_gaps", std::move(gaps)},
        });
        manifestFiles[key] = json::Object{{"path", "files/" + file.relativePath},
                                          {"role", statistics ? "report" : "map"},
                                          {"sha256", Sha256Field(sha, true)},
                                          {"bytes", static_cast<std::int64_t>(encoded.bytes.size())}};
        outputs.emplace_back(key);
        if (!statistics) {
            maps[key] = json::Object{{"resolution", size},
                                     {"bit_depth", ManifestBitDepth(file.parameters->bitDepth)},
                                     {"color_space", kWrittenColourSpace}};
        }
        presets.insert(file.preset);
    }
    json::Array skipped;
    for (const SkippedMap& s : plan.skipped) {
        skipped.push_back(json::Object{{"root_path", s.rootPath},
                                       {"preset", s.preset},
                                       {"file_name", s.fileName},
                                       {"kind", std::string(SkipKindName(s.kind))},
                                       {"reason", s.reason}});
        openItems.emplace_back(s.rootPath + " " + s.fileName + ": not written (" + std::string(SkipKindName(s.kind)) +
                               "): " + s.reason);
    }

    json::Value preset = nullptr;
    if (presets.size() == 1) {
        preset = json::Object{{"file", "export-plan"}, {"selector", "/files/0/preset"}};
    } else if (presets.size() > 1) {
        openItems.emplace_back("the files use " + std::to_string(presets.size()) +
                               " presets: each file's preset is in the receipt's files[].preset");
    }
    // An export that writes no file has no outputs, and Assets3D's export block needs one.
    json::Value manifestExport = nullptr;
    if (!outputs.empty()) {
        manifestExport = json::Object{
            {"sources", std::move(sources)},
            {"outputs", std::move(outputs)},
            {"moment", in.moment},
            {"preset", std::move(preset)},
            {"maps", std::move(maps)},
            {"comparison",
             json::Object{
                 {"result", "pending"}, {"report", nullptr}, {"tolerance", nullptr}, {"differences", json::Array{}}}},
            {"evidence", json::Array{json::Object{{"file", "export-plan"}}}},
            {"open_items", std::move(openItems)},
        };
    }

    receipt["schema"] = std::string(kReceiptSchema);
    receipt["build"] = in.identity.build;
    receipt["generation"] = in.generation;
    receipt["moment"] = in.moment;
    receipt["plan"] = "plan.json";
    receipt["plan_hash"] = plan.hash;
    receipt["files"] = std::move(files);
    receipt["skipped"] = std::move(skipped);
    receipt["manifest_files"] = std::move(manifestFiles);
    receipt["manifest_export"] = std::move(manifestExport);
    return receipt;
}

ReceiptSummary ReadReceipt(std::string_view text) {
    const auto fail = [](const std::string& what) -> core::ManifestError {
        return core::ManifestError("receipt: " + what);
    };
    json::Value value;
    try {
        value = json::Parse(text);
    } catch (const json::ParseError& e) {
        throw fail(e.what());
    }
    if (!value.IsObject()) throw fail("expected an object");
    const json::Object& o = std::get<json::Object>(value.data);
    const auto string = [&](const json::Object& object, const std::string& key, const std::string& where) {
        const auto it = object.find(key);
        if (it == object.end() || !it->second.IsString()) throw fail(where + key + ": expected a string");
        return std::get<std::string>(it->second.data);
    };
    if (string(o, "schema", "") != kReceiptSchema) throw fail("schema: expected " + std::string(kReceiptSchema));
    ReceiptSummary summary;
    summary.generation = string(o, "generation", "");
    summary.planHash = string(o, "plan_hash", "");
    if (!core::IsSha256Hex(summary.planHash)) throw fail("plan_hash: not a lower-case SHA-256");
    const auto files = o.find("files");
    if (files == o.end() || !files->second.IsArray()) throw fail("files: expected an array");
    for (const json::Value& item : std::get<json::Array>(files->second.data)) {
        if (!item.IsObject()) throw fail("files[]: expected an object");
        const json::Object& f = std::get<json::Object>(item.data);
        ReceiptFile file;
        file.path = string(f, "path", "files[].");
        file.sha256 = string(f, "sha256", "files[].");
        const auto bytes = f.find("bytes");
        if (bytes == f.end() || !bytes->second.IsInt() || std::get<std::int64_t>(bytes->second.data) < 0) {
            throw fail("files[].bytes: expected a non-negative integer");
        }
        file.bytes = static_cast<std::uint64_t>(std::get<std::int64_t>(bytes->second.data));
        if (!IsDeliveryPath(file.path)) throw fail("files[].path: '" + file.path + "' is not a relative delivery path");
        if (!core::IsSha256Hex(file.sha256)) throw fail("files[].sha256: not a lower-case SHA-256");
        summary.files.push_back(std::move(file));
    }
    return summary;
}

}  // namespace uzp::exporter
