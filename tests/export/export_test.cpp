// Native tests of the export plan compiler (task phase1.15_export-plan-compiler, decisions 085
// and 086; src/export/). Driven by tests/export/test_export_plan.py:
//
//   uzp-export-tests plan <cases.json>
//       Each case {"project": <skeleton>, "config": <json_config>} is compiled; prints one JSON
//       line per case: {"plan": PlanJson, "list": [[set, stack, [paths]]]} or {"error": class,
//       "message": text}, class `ValueError` or `NotYetSupported`.
//   uzp-export-tests files <templates dir> <spec.json> <config.json> <out dir>
//       Builds the project of an evaluator spec, compiles the configuration and evaluates every
//       planned file on the CPU store (`EvaluateFileOn`); writes <out>/index.json and one raw
//       float32 file per planned file (<out>/<n>.f32).
//   uzp-export-tests export <templates dir> <spec.json> <config.json>
//       (phase1.16) Builds the project of a spec (with "mesh": an OBJ path, the texturing mesh whose
//       material per texture set gives the UV coverage), compiles the configuration and writes its
//       files with `WriteExport`; prints {"plan": PlanJson, "list": the dry run, "written":
//       [{rootPath, relativePath, path, size, sha256}]} or {"error": class, "message": text}.
//   uzp-export-tests reencode <list.txt>
//       (phase1.16) Each line a PNG or OpenEXR file: decoded at native depth (spng; DecodeExr) and
//       encoded again with EncodePng / EncodeExr; prints one JSON line per file {"path", "format",
//       "equal", "size", "encoded_size"} (whether the bytes are identical).
//   uzp-export-tests roundtrip <out dir>
//       (phase1.16) Encodes synthetic PNG16 and OpenEXR 32f images twice (ramps, runs, noise, signed
//       zero, infinities, NaN payloads, odd sizes), decodes them back and writes the files; prints
//       one JSON line per image {"name", "format", "decoded_equal", "repeat_equal", "sha256"}.
//
// A project skeleton: {"color_management"?, "workflow"?, "normal_map_format"?, "texture_sets":
// [{"name", "resolution"?: [w, h], "mesh_maps"?: [usage...], "stacks": [{"name", "channels":
// {type: format}, "layers"?: [uid...]}]}]}. A spec is the evaluator test spec
// (tests/evaluator/evaluator_test.cpp, `evaluate`) restricted to fill and group layers, plus
// "name" (the texture set's name) and "mesh_maps" ({usage: resource sha256}).

#include "evaluator/admission.h"
#include "evaluator/evaluator.h"
#include "evaluator/profile.h"
#include "evaluator/sources.h"
#include "evaluator/templates.h"
#include "evaluator/geometry_mask.h"
#include "export/config.h"
#include "export/exr_writer.h"
#include "export/plan.h"
#include "export/png_writer.h"
#include "export/virtual_maps.h"
#include "export/write.h"
#include "mesh/mesh_import.h"
#include "spng.h"
#include "uzp_core/document/nodes.h"
#include "uzp_core/manifest/json.h"
#include "uzp_core/manifest/sha256.h"
#include "uzp_core/types/errors.h"
#include "uzp_core/types/validation.h"

#include <algorithm>
#include <array>
#include <bit>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <iterator>
#include <limits>
#include <map>
#include <memory>
#include <string>
#include <vector>

namespace {

namespace fs = std::filesystem;
namespace json = uzp::core::json;
using namespace uzp;
using core::ChannelFormat;
using core::ChannelType;

const json::Object& Obj(const json::Value& v, const std::string& what) {
    if (!v.IsObject()) throw core::ManifestError(what + ": expected an object");
    return std::get<json::Object>(v.data);
}
const json::Array& Arr(const json::Value& v, const std::string& what) {
    if (!v.IsArray()) throw core::ManifestError(what + ": expected an array");
    return std::get<json::Array>(v.data);
}
const json::Value& Key(const json::Object& o, const std::string& key) {
    const auto it = o.find(key);
    if (it == o.end()) throw core::ManifestError("missing key '" + key + "'");
    return it->second;
}
std::string Str(const json::Value& v, const std::string& what) {
    if (!v.IsString()) throw core::ManifestError(what + ": expected a string");
    return std::get<std::string>(v.data);
}
double Num(const json::Value& v, const std::string& what) {
    if (v.IsInt()) return static_cast<double>(std::get<std::int64_t>(v.data));
    if (!v.IsDouble()) throw core::ManifestError(what + ": expected a number");
    return std::get<double>(v.data);
}
template <typename E>
E EnumOf(const std::string& name, const std::string& what) {
    const auto parsed = core::FromString<E>(name);
    if (!parsed) throw core::ManifestError(what + ": unknown member '" + name + "'");
    return *parsed;
}

std::string ReadText(const fs::path& path) {
    std::ifstream stream(path, std::ios::binary);
    if (!stream) throw core::ManifestError("cannot read " + path.string());
    return {std::istreambuf_iterator<char>(stream), std::istreambuf_iterator<char>()};
}

/// An imported mesh map of the resource `sha256`, declared in the project's convention.
core::MeshMapBinding Binding(const std::string& sha256, core::NormalMapFormat convention) {
    core::MeshMapBinding binding;
    binding.resource = sha256;
    binding.format = ChannelFormat::RGB16;
    binding.color_space = "Raw";
    binding.provenance =
        core::ImportedProvenance{"mesh-map.png", sha256, core::MeshMapRole::geometry_only, convention, "", {}};
    return binding;
}

core::Layer FillLayer(core::Id uid) {
    core::Layer layer;
    layer.uid = uid;
    layer.kind = core::LayerKind::fill;
    layer.name = "layer" + std::to_string(uid);
    layer.fill = core::FillContent{};
    return layer;
}

// ── Project skeletons (plan cases) ──────────────────────────────────────────

core::Project ParseSkeleton(const json::Value& value) {
    const json::Object& o = Obj(value, "project");
    core::Project project;
    project.versions.evaluator_profile = std::string(evaluator::kCurrentProfile);
    if (o.contains("color_management")) project.settings.color_management.mode = Str(o.at("color_management"), "cm");
    if (o.contains("workflow")) {
        project.settings.workflow = EnumOf<core::ProjectWorkflow>(Str(o.at("workflow"), "workflow"), "workflow");
    }
    if (o.contains("normal_map_format")) {
        project.settings.normal_map_format =
            EnumOf<core::NormalMapFormat>(Str(o.at("normal_map_format"), "normal_map_format"), "normal map format");
    }
    core::Id next = 1;
    for (const json::Value& s : Arr(Key(o, "texture_sets"), "texture_sets")) {
        const json::Object& so = Obj(s, "texture set");
        core::TextureSet set;
        set.id = next++;
        set.name = Str(Key(so, "name"), "name");
        set.original_name = set.name;
        set.material_id = set.name;
        set.resolution.width = 256;
        set.resolution.height = 256;
        if (so.contains("resolution")) {
            const json::Array& r = Arr(so.at("resolution"), "resolution");
            set.resolution.width = static_cast<int>(Num(r.at(0), "width"));
            set.resolution.height = static_cast<int>(Num(r.at(1), "height"));
        }
        set.uv_tiles.push_back(core::UVTile{next++, 1001, {}});
        if (so.contains("mesh_maps")) {
            for (const json::Value& m : Arr(so.at("mesh_maps"), "mesh_maps")) {
                set.mesh_maps.emplace(EnumOf<core::MeshMapUsage>(Str(m, "mesh map"), "mesh map"),
                                      Binding(std::string(64, 'a'), project.settings.normal_map_format));
            }
        }
        for (const json::Value& st : Arr(Key(so, "stacks"), "stacks")) {
            const json::Object& sto = Obj(st, "stack");
            core::Stack stack;
            stack.id = next++;
            stack.name = Str(Key(sto, "name"), "stack name");
            for (const auto& [type, format] : Obj(Key(sto, "channels"), "channels")) {
                core::Channel channel;
                channel.format = EnumOf<ChannelFormat>(Str(format, "format"), "format");
                stack.channels.emplace(EnumOf<ChannelType>(type, "channel"), channel);
            }
            if (sto.contains("layers")) {
                for (const json::Value& uid : Arr(sto.at("layers"), "layers")) {
                    stack.root_layers.push_back(FillLayer(static_cast<core::Id>(Num(uid, "uid"))));
                }
            }
            set.stacks.push_back(std::move(stack));
        }
        project.texture_sets.push_back(std::move(set));
    }
    project.next_id = next + 100000;
    return project;
}

json::Value ListJson(const std::vector<exporter::StackFiles>& list) {
    json::Array out;
    for (const exporter::StackFiles& s : list) {
        json::Array files;
        for (const std::string& f : s.files) files.emplace_back(f);
        out.push_back(json::Array{s.textureSet, s.stack, std::move(files)});
    }
    return out;
}

int RunPlan(const fs::path& casesPath) {
    const json::Value cases = json::Parse(ReadText(casesPath));
    for (const json::Value& c : Arr(cases, "cases")) {
        const json::Object& o = Obj(c, "case");
        json::Object result;
        try {
            const core::Project project = ParseSkeleton(Key(o, "project"));
            const json::Value& config = Key(o, "config");
            const exporter::ExportPlan plan =
                config.IsString() ? exporter::CompilePlan(project, Str(config, "config"))
                                  : exporter::CompilePlan(project, exporter::ParseConfig(config));
            result["plan"] = exporter::PlanJson(plan);
            result["list"] = ListJson(exporter::FilesByStack(plan));
            result["canonical_sha256"] = core::Sha256Hex(json::WriteCanonical(exporter::PlanJson(plan)));
        } catch (const core::ValueError& e) {
            result["error"] = "ValueError";
            result["message"] = std::string(e.what());
        } catch (const core::NotYetSupported& e) {
            result["error"] = "NotYetSupported";
            result["message"] = std::string(e.what());
        }
        std::cout << json::WriteCanonical(result) << "\n";
    }
    return 0;
}

// ── Evaluator specs (files cases) ───────────────────────────────────────────

core::Source ParseSource(const json::Object& s) {
    if (s.contains("uniform")) {
        const json::Array& rgb = Arr(s.at("uniform"), "uniform");
        core::UniformColorSource uniform;
        for (size_t i = 0; i < 3 && i < rgb.size(); ++i) uniform.rgb[i] = Num(rgb[i], "uniform component");
        uniform.color_space = s.contains("color_space") ? Str(s.at("color_space"), "color_space") : "Working";
        return core::Source{uniform};
    }
    core::BitmapSource bitmap;
    bitmap.resource.sha256 = Str(Key(s, "bitmap"), "bitmap");
    bitmap.color_space = s.contains("color_space") ? Str(s.at("color_space"), "color_space") : "Raw";
    return core::Source{bitmap};
}

std::map<ChannelType, core::Blending> ParseBlending(const json::Object& o) {
    std::map<ChannelType, core::Blending> blending;
    if (!o.contains("blending")) return blending;
    for (const auto& [channel, entry] : Obj(o.at("blending"), "blending")) {
        const json::Object& b = Obj(entry, "blending entry");
        core::Blending blend;
        blend.mode = EnumOf<core::BlendingMode>(Str(Key(b, "mode"), "mode"), "mode");
        blend.opacity = Num(Key(b, "opacity"), "opacity");
        blending[EnumOf<ChannelType>(channel, "blending channel")] = blend;
    }
    return blending;
}

core::Layer ParseLayer(const json::Value& value, core::Project& project) {
    const json::Object& o = Obj(value, "layer");
    const std::string kind = Str(Key(o, "kind"), "layer.kind");
    if (o.contains("mask") || o.contains("effects")) {
        throw core::ManifestError("masks and effects are not modelled by the export tests (phase1.11's tests cover them)");
    }
    core::Layer layer;
    layer.uid = o.contains("uid") ? static_cast<core::Id>(Num(o.at("uid"), "uid")) : project.AllocateId();
    layer.name = o.contains("name") ? Str(o.at("name"), "name") : kind;
    layer.blending = ParseBlending(o);
    if (o.contains("visible")) layer.visible = std::get<bool>(o.at("visible").data);
    if (kind == "fill") {
        layer.kind = core::LayerKind::fill;
        core::FillContent fill;
        fill.source_mode = core::SourceMode::Split;
        for (const auto& [channel, entry] : Obj(Key(o, "sources"), "sources")) {
            const ChannelType type = EnumOf<ChannelType>(channel, "source channel");
            fill.sources[type] = ParseSource(Obj(entry, "source"));
            fill.active_channels.insert(type);
        }
        if (o.contains("active_channels")) {
            fill.active_channels.clear();
            for (const json::Value& c : Arr(o.at("active_channels"), "active_channels")) {
                fill.active_channels.insert(EnumOf<ChannelType>(Str(c, "active channel"), "active channel"));
            }
        }
        if (o.contains("projection")) throw core::ManifestError("projections are not modelled by the export tests");
        layer.fill = std::move(fill);
    } else if (kind == "group") {
        layer.kind = core::LayerKind::group;
        for (const json::Value& child : Arr(Key(o, "children"), "children")) {
            layer.children.push_back(ParseLayer(child, project));
        }
    } else {
        throw core::ManifestError("layer kind '" + kind + "' is not modelled by the export tests");
    }
    return layer;
}

struct Spec {
    core::Project project;
    std::string templateId{evaluator::kDefaultTemplateId};
    std::shared_ptr<evaluator::DecodingResourceProvider> resources;
    /// The texturing mesh's coverage ("mesh": an OBJ path), null without one.
    std::shared_ptr<const evaluator::IGeometryMaskProvider> geometry;
};

Spec ParseSpec(const fs::path& path) {
    const json::Value document = json::Parse(ReadText(path));
    const json::Object& o = Obj(document, "spec");
    Spec spec;
    auto bytes = std::make_shared<std::map<std::string, std::string, std::less<>>>();
    spec.resources = std::make_shared<evaluator::DecodingResourceProvider>(
        [bytes](std::string_view sha) -> std::optional<std::string> {
            const auto it = bytes->find(sha);
            if (it == bytes->end()) return std::nullopt;
            return it->second;
        });
    core::Project& project = spec.project;
    project.versions.app_version = "uzp-export-tests";
    project.versions.evaluator_profile = std::string(evaluator::kCurrentProfile);
    if (o.contains("evaluator_profile")) project.versions.evaluator_profile = Str(o.at("evaluator_profile"), "profile");
    if (o.contains("template")) spec.templateId = Str(o.at("template"), "template");
    if (o.contains("normal_map_format")) {
        project.settings.normal_map_format =
            EnumOf<core::NormalMapFormat>(Str(o.at("normal_map_format"), "normal_map_format"), "normal map format");
    }
    core::TextureSet set;
    set.id = project.AllocateId();
    set.name = o.contains("name") ? Str(o.at("name"), "name") : "set";
    set.original_name = set.name;
    set.material_id = set.name;
    const json::Array& resolution = Arr(Key(o, "resolution"), "resolution");
    set.resolution.width = static_cast<int>(Num(resolution.at(0), "width"));
    set.resolution.height = static_cast<int>(Num(resolution.at(1), "height"));
    set.uv_tiles.push_back(core::UVTile{project.AllocateId(), 1001, {}});
    if (o.contains("mesh")) {
        auto mesh = std::make_shared<mesh::TexturingMesh>(mesh::ImportMeshFile(Str(o.at("mesh"), "mesh"), {}).mesh);
        spec.geometry = std::make_shared<evaluator::MeshGeometryMasks>(std::move(mesh));
    }
    if (o.contains("height_to_normal_method")) {
        set.height_to_normal_method = EnumOf<core::HeightToNormalMethod>(
            Str(o.at("height_to_normal_method"), "height_to_normal_method"), "height to normal method");
    }
    core::Stack stack;
    stack.id = project.AllocateId();
    for (const json::Value& entry : Arr(Key(o, "channels"), "channels")) {
        const json::Object& c = Obj(entry, "channel");
        core::Channel channel;
        channel.format = EnumOf<ChannelFormat>(Str(Key(c, "format"), "format"), "channel format");
        stack.channels.emplace(EnumOf<ChannelType>(Str(Key(c, "type"), "type"), "channel type"), channel);
    }
    for (const json::Value& entry : Arr(Key(o, "resources"), "resources")) {
        const json::Object& r = Obj(entry, "resource");
        const std::string sha = Str(Key(r, "sha256"), "sha256");
        std::string data = ReadText(path.parent_path() / Str(Key(r, "png"), "png"));
        core::ResourceMeta meta;
        meta.id = project.AllocateId();
        meta.name = "resource-" + sha.substr(0, 8);
        meta.mime = "image/png";
        meta.size = static_cast<std::int64_t>(data.size());
        meta.usage = "TEXTURE";
        meta.origin = "test";
        meta.imported_at = "2026-10-11T00:00:00Z";
        project.resources[sha].push_back(std::move(meta));
        (*bytes)[sha] = std::move(data);
    }
    if (o.contains("mesh_maps")) {
        for (const auto& [usage, sha] : Obj(o.at("mesh_maps"), "mesh_maps")) {
            set.mesh_maps.emplace(EnumOf<core::MeshMapUsage>(usage, "mesh map"),
                                  Binding(Str(sha, "mesh map sha256"), project.settings.normal_map_format));
        }
    }
    for (const json::Value& entry : Arr(Key(o, "layers"), "layers")) {
        stack.root_layers.push_back(ParseLayer(entry, project));  // top first, as stored
    }
    set.stacks.push_back(std::move(stack));
    project.texture_sets.push_back(std::move(set));
    core::Id maxId = project.next_id;
    core::ForEachNode(project, [&](const core::NodeVisit& visit) {
        maxId = std::max(maxId, (visit.layer ? visit.layer->uid : visit.effect->uid) + 1);
    });
    project.next_id = maxId;
    core::Validate(project);
    return spec;
}

int RunFiles(const fs::path& templatesDir, const fs::path& specPath, const fs::path& configPath, const fs::path& out) {
    const Spec spec = ParseSpec(specPath);
    const exporter::ExportPlan plan = exporter::CompilePlan(spec.project, ReadText(configPath));
    auto templates = std::make_shared<const evaluator::TemplateLibrary>(evaluator::TemplateLibrary::Load(templatesDir));
    evaluator::CpuEvaluator cpu(templates, evaluator::AdmissionLimits{64ull << 30, 1 << 20});
    exporter::SourceInputs inputs;
    inputs.templateId = spec.templateId;
    inputs.resources = spec.resources;
    fs::create_directories(out);
    json::Array files;
    for (size_t i = 0; i < plan.files.size(); ++i) {
        const exporter::PlannedFile& file = plan.files[i];
        json::Object entry{{"relativePath", file.relativePath}};
        render::Result<exporter::FileRaster> raster =
            exporter::EvaluateFileOn(spec.project, 1, file, inputs, *templates, cpu.store(), cpu.cache());
        if (!raster) {
            entry["error"] = raster.error().reason;
        } else {
            entry["width"] = static_cast<std::int64_t>(raster->width);
            entry["height"] = static_cast<std::int64_t>(raster->height);
            entry["channels"] = static_cast<std::int64_t>(raster->channels);
            if (raster->normalTag) entry["normal"] = std::string(core::ToString(raster->normalTag->role));
            if (raster->statistics) {
                entry["statistics"] = *raster->statistics;
            } else {
                const std::string name = std::to_string(i) + ".f32";
                std::ofstream stream(out / name, std::ios::binary);
                stream.write(reinterpret_cast<const char*>(raster->values.data()),
                             static_cast<std::streamsize>(raster->values.size() * sizeof(float)));
                entry["raw"] = name;
            }
        }
        files.push_back(std::move(entry));
    }
    std::ofstream index(out / "index.json", std::ios::binary);
    index << json::WriteCanonical(json::Object{{"plan", exporter::PlanJson(plan)}, {"files", std::move(files)}});
    return 0;
}

// ── Writers (phase1.16) ─────────────────────────────────────────────────────

int RunExport(const fs::path& templatesDir, const fs::path& specPath, const fs::path& configPath) {
    const Spec spec = ParseSpec(specPath);
    json::Object result;
    try {
        const exporter::ExportPlan plan = exporter::CompilePlan(spec.project, ReadText(configPath));
        auto templates = std::make_shared<const evaluator::TemplateLibrary>(evaluator::TemplateLibrary::Load(templatesDir));
        evaluator::CpuEvaluator cpu(templates, evaluator::AdmissionLimits{64ull << 30, 1 << 20});
        exporter::SourceInputs inputs;
        inputs.templateId = spec.templateId;
        inputs.resources = spec.resources;
        inputs.geometry = spec.geometry;
        render::Result<std::vector<exporter::WrittenFile>> written =
            exporter::WriteExport(spec.project, 1, plan, inputs, *templates, cpu.store(), cpu.cache());
        if (!written) {
            result["error"] = "Failure";
            result["message"] = written.error().reason;
        } else {
            json::Array files;
            for (const exporter::WrittenFile& f : *written) {
                files.push_back(json::Object{{"rootPath", f.rootPath},
                                             {"relativePath", f.relativePath},
                                             {"path", f.path},
                                             {"size", static_cast<std::int64_t>(f.size)},
                                             {"sha256", f.sha256}});
            }
            result["plan"] = exporter::PlanJson(plan);
            result["list"] = ListJson(exporter::FilesByStack(plan));
            result["written"] = std::move(files);
        }
    } catch (const core::ValueError& e) {
        result["error"] = "ValueError";
        result["message"] = std::string(e.what());
    } catch (const core::NotYetSupported& e) {
        result["error"] = "NotYetSupported";
        result["message"] = std::string(e.what());
    }
    std::cout << json::WriteCanonical(result) << "\n";
    return 0;
}

/// An 8- or 16-bit grey, RGB or RGBA PNG decoded at native depth with spng.
exporter::PngImage DecodePng(const std::string& data) {
    std::unique_ptr<spng_ctx, decltype(&spng_ctx_free)> ctx(spng_ctx_new(0), &spng_ctx_free);
    spng_ihdr ihdr{};
    size_t size = 0;
    if (spng_set_png_buffer(ctx.get(), data.data(), data.size()) != 0 || spng_get_ihdr(ctx.get(), &ihdr) != 0 ||
        (ihdr.bit_depth != 8 && ihdr.bit_depth != 16) ||
        (ihdr.color_type != SPNG_COLOR_TYPE_GRAYSCALE && ihdr.color_type != SPNG_COLOR_TYPE_TRUECOLOR &&
         ihdr.color_type != SPNG_COLOR_TYPE_TRUECOLOR_ALPHA) ||
        spng_decoded_image_size(ctx.get(), SPNG_FMT_PNG, &size) != 0) {
        throw core::ManifestError("not an 8- or 16-bit grey, RGB or RGBA PNG");
    }
    const uint32_t channels = ihdr.color_type == SPNG_COLOR_TYPE_GRAYSCALE ? 1u
                              : ihdr.color_type == SPNG_COLOR_TYPE_TRUECOLOR ? 3u
                                                                             : 4u;
    exporter::PngImage image{ihdr.width, ihdr.height, channels, ihdr.bit_depth, {}};
    // SPNG_FMT_PNG: the file's layout, 16-bit samples in host byte order.
    std::vector<uint8_t> bytes(size);
    if (spng_decode_image(ctx.get(), bytes.data(), size, SPNG_FMT_PNG, 0) != 0) {
        throw core::ManifestError("spng could not decode the PNG");
    }
    if (ihdr.bit_depth == 8) {
        image.samples.assign(bytes.begin(), bytes.end());
    } else {
        image.samples.resize(size / 2);
        std::memcpy(image.samples.data(), bytes.data(), size);
    }
    return image;
}

int RunReencode(const fs::path& listPath) {
    std::ifstream list(listPath);
    std::string line;
    while (std::getline(list, line)) {
        if (line.empty()) continue;
        const std::string data = ReadText(line);
        json::Object result{{"path", line}, {"size", static_cast<std::int64_t>(data.size())}};
        std::string encoded;
        if (data.starts_with("\x89PNG")) {
            result["format"] = "png";
            encoded = exporter::EncodePng(DecodePng(data));
        } else {
            result["format"] = "exr";
            encoded = exporter::EncodeExr(exporter::DecodeExr(data));
        }
        result["encoded_size"] = static_cast<std::int64_t>(encoded.size());
        result["equal"] = encoded == data;
        std::cout << json::WriteCanonical(result) << "\n";
    }
    return 0;
}

/// Synthetic PNG16 samples: a ramp through every code, a constant run and noise from a fixed LCG,
/// by rows in turn.
exporter::PngImage SyntheticPng(uint32_t width, uint32_t height, uint32_t channels) {
    exporter::PngImage image{width, height, channels, 16, {}};
    uint32_t state = 12345;
    const size_t perRow = size_t{width} * channels;
    for (size_t i = 0; i < perRow * height; ++i) {
        state = state * 1664525u + 1013904223u;
        const size_t kind = (i / perRow) % 3;
        image.samples.push_back(static_cast<uint16_t>(kind == 0 ? i % 65536 : kind == 1 ? 32768 : state >> 16));
    }
    return image;
}

/// Synthetic float32 values: a ramp with edge and special values bit for bit (signed zero,
/// subnormal, maximum, infinities, NaN payloads).
exporter::ExrImage SyntheticExr(uint32_t width, uint32_t height, uint32_t channels) {
    const std::array<float, 13> specials{0.0f,
                                         -0.0f,
                                         1.0f,
                                         -1.0f,
                                         std::numeric_limits<float>::denorm_min(),
                                         std::numeric_limits<float>::max(),
                                         -std::numeric_limits<float>::infinity(),
                                         std::numeric_limits<float>::infinity(),
                                         std::bit_cast<float>(0x7FC00001u),
                                         std::bit_cast<float>(0xFFA00000u),
                                         0.333333343f,
                                         65504.0f,
                                         1e-30f};
    exporter::ExrImage image{width, height, channels, {}};
    for (size_t i = 0; i < size_t{width} * height * channels; ++i) {
        const size_t k = i % 97;
        image.values.push_back(k < specials.size() ? specials[k] : static_cast<float>(i) / 4093.0f - 7.5f);
    }
    return image;
}

bool SameBits(const std::vector<float>& a, const std::vector<float>& b) {
    return a.size() == b.size() && std::equal(a.begin(), a.end(), b.begin(), [](float x, float y) {
               return std::bit_cast<uint32_t>(x) == std::bit_cast<uint32_t>(y);
           });
}

int RunRoundtrip(const fs::path& out) {
    fs::create_directories(out);
    const auto emit = [&](const std::string& name, const std::string& format, bool decodedEqual, const std::string& a,
                          const std::string& b) {
        std::ofstream(out / name, std::ios::binary).write(a.data(), static_cast<std::streamsize>(a.size()));
        std::cout << json::WriteCanonical(json::Object{{"name", name},
                                                       {"format", format},
                                                       {"decoded_equal", decodedEqual},
                                                       {"repeat_equal", a == b},
                                                       {"sha256", core::Sha256Hex(a)}})
                  << "\n";
    };
    const std::array<std::array<uint32_t, 3>, 5> sizes{
        {{1, 1, 1}, {257, 33, 3}, {64, 64, 1}, {300, 70, 3}, {33, 17, 4}}};
    for (const auto& [w, h, c] : sizes) {
        const std::string suffix = std::to_string(w) + "x" + std::to_string(h) + "x" + std::to_string(c);
        for (const uint32_t bits : {16u, 8u}) {
            exporter::PngImage png = SyntheticPng(w, h, c);
            png.bitDepth = bits;
            if (bits == 8) {
                for (uint16_t& sample : png.samples) sample &= 0xFF;
            }
            const std::string pngBytes = exporter::EncodePng(png);
            const exporter::PngImage back = DecodePng(pngBytes);
            emit("synthetic-" + suffix + (bits == 8 ? "-8" : "") + ".png", "png",
                 back.width == w && back.height == h && back.channels == c && back.bitDepth == bits &&
                     back.samples == png.samples,
                 pngBytes, exporter::EncodePng(png));
        }
        const exporter::ExrImage exr = SyntheticExr(w, h, c);
        const std::string exrBytes = exporter::EncodeExr(exr);
        const exporter::ExrImage exrBack = exporter::DecodeExr(exrBytes);
        emit("synthetic-" + suffix + ".exr", "exr",
             exrBack.width == w && exrBack.height == h && exrBack.channels == c && SameBits(exrBack.values, exr.values),
             exrBytes, exporter::EncodeExr(exr));
    }
    return 0;
}

}  // namespace

int main(int argc, char** argv) {
    const std::vector<std::string> args(argv + 1, argv + argc);
    try {
        if (args.size() == 2 && args[0] == "plan") return RunPlan(args[1]);
        if (args.size() == 5 && args[0] == "files") return RunFiles(args[1], args[2], args[3], args[4]);
        if (args.size() == 4 && args[0] == "export") return RunExport(args[1], args[2], args[3]);
        if (args.size() == 2 && args[0] == "reencode") return RunReencode(args[1]);
        if (args.size() == 2 && args[0] == "roundtrip") return RunRoundtrip(args[1]);
    } catch (const std::exception& e) {
        std::cerr << "uzp-export-tests: " << e.what() << "\n";
        return 2;
    }
    std::cerr << "usage: uzp-export-tests plan <cases.json> | files <templates> <spec.json> <config.json> <out> | "
                 "export <templates> <spec.json> <config.json> | reencode <list.txt> | roundtrip <out>\n";
    return 2;
}
