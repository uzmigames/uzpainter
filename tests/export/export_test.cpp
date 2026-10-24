// Native tests of the export plan compiler (task phase1.15_export-plan-compiler, decisions 085
// and 086; src/export/). Driven by tests/export/test_export_plan.py:
//
//   uzp-export-tests plan <cases.json>
//       Each case {"project": <skeleton>, "config": <json_config>, "project_path"?: <path>,
//       "uztexture"?: [relativePath...]} is compiled, then each listed file's `.uztexture` normal
//       derivative is requested (`RequestUzTextureNormal`); prints one JSON line per case: {"plan": PlanJson, "list": [[set, stack,
//       [paths]]]} (the dry run), {"plan": PlanJson, "list_error": text} (the dry run raises
//       ValueError: CheckExportable) or {"error": class, "message": text}, class `ValueError` or
//       `NotYetSupported`.
//       Optional "dds": [{"path": relativePath, "format": BcFormat ordinal,
//       "mips": DerivativeMips ordinal}] requests DDS after plan compilation.
//       Optional "presets": a directory the shipped presets are read from (an authored variant).
//       `publish` and `export` also accept --dds <requests.json> with this array.
//   uzp-export-tests files <templates dir> <spec.json> <config.json> <out dir>
//       Builds the project of an evaluator spec, compiles the configuration and evaluates every
//       planned file on the CPU store (`EvaluateFileOn`); writes <out>/index.json and one raw
//       float32 file per planned file (<out>/<n>.f32).
//   uzp-export-tests export <templates dir> <spec.json> <config.json>
//       (phase1.16) Builds the project of a spec (with "mesh": an OBJ path, the texturing mesh whose
//       material per texture set gives the UV coverage), compiles the configuration and writes its
//       files with `WriteExport`; prints {"plan": PlanJson, "list": the dry run, "written":
//       [{rootPath, relativePath, path, size, sha256}]} or {"error": class, "message": text}.
//   uzp-export-tests export-diagnostic <templates dir> <spec.json> <config.json>
//       (decisions 286, 308) As `export`, through the diagnostic measure export (`EncodeExport`
//       with `DiagnosticMeasure`): prints {"written": [{relativePath, path, bypassed: [refusal],
//       undecided: texels}]} or {"error": class, "message": text}. Not conformant.
//   uzp-export-tests export-backend <cpu|dx12|vulkan> <templates> <spec.json> <config.json>
//       Normal WriteExport using the requested tile store; Vulkan uses the qualified native
//       test seam only. Reports backend/adapter and real file hashes; unavailable GPU exits 77.
//   uzp-export-tests reencode <list.txt>
//       (phase1.16) Each line a PNG or OpenEXR file: decoded at native depth (spng; DecodeExr) and
//       encoded again with EncodePng / EncodeExr; prints one JSON line per file {"path", "format",
//       "equal", "size", "encoded_size"} (whether the bytes are identical).
//   uzp-export-tests process <cases.json>
//       (phase1.18) Each case {"source": a file Painter exported (OpenEXR 32f, or PNG 16 read as
//       UNORM operands), "target": Painter's file of the same map with another processing,
//       "format": png|exr, "bit_depth": 8|16|16f|32f, "dithering"?, "height"? (the channel is
//       Height), "srgb8_material"? (an sRGB8 BaseColor, Specular or Emissive: every channel
//       sRGB-encoded in a PNG), "l8_material"? (an L8 one, each channel read through its own letter:
//       `SrgbEncodedRead`), "append_opaque_alpha"? (an alpha of 1 appended), "ocio"? (OCIO with
//       Painter's substance config), "document_format"? (every channel a documentMap stored in that
//       ChannelFormat: a PNG source's codes read back as its operands, `DocumentOperands`)}: the
//       source's values as the
//       raster of an L, L+A, RGB or RGB+A file, encoded by EncodeFile; prints one JSON line per case
//       {"target", "equal", "layout", "size", "target_size"}.
//   uzp-export-tests ring <cases.json>
//       (phase1.25 item 2.7) A list of cases {"mesh": an OBJ path, "material", "width", "height",
//       "channels": 1 or 3, "values": raw float32 texels, rows top first, "out": a path}: the values
//       padded `infinite` over the material's coverage and triangles, measured (padding.h), written
//       raw to "out"; prints one JSON line per case {"ring": the measured ring (`RingJson`)}.
//   uzp-export-tests roundtrip <out dir>
//       (phase1.16) Encodes synthetic PNG16 and OpenEXR 32f images twice (ramps, runs, noise, signed
//       zero, infinities, NaN payloads, odd sizes), decodes them back and writes the files; prints
//       one JSON line per image {"name", "format", "decoded_equal", "repeat_equal", "sha256"}.
//   uzp-export-tests presets <preset dir> <references.json>
//       (phase1.17) {"references": [text...]}: each resolved to a shipped preset
//       (`ShippedPresetId`) and loaded from <preset dir> (`LoadShippedPreset`); prints one JSON line
//       per reference {"reference", "id": id or null, "name", "layout", "pending", "maps": [fileName]}
//       or {"reference", "error": class, "message": text}, class `ValueError`, `NotYetSupported` or
//       `ManifestError`.
//   uzp-export-tests aliases
//       (phase1.17) Prints {"shipped": [id...], "aliases": [[Painter name, id, [version...]]]}.
//   uzp-export-tests preflight <templates dir> <spec.json> <config.json>
//       (SUP-035, decision 091) The project of a spec as `export` builds it: the plan's preflight
//       (`PreflightExport` over the spec's mesh coverage, `PreflightJson`) with a resource provider
//       that counts every read, then the export (`WriteExport`); prints {"preflight", "plan":
//       PlanJson before and "plan_after" after the preflight, "resource_reads": reads during the
//       preflight, "written_before_export": whether exportPath existed after it, "export":
//       {"written": [relativePath...]} or {"error": class, "message": text}}. With "mesh_reference"
//       in the spec ("stored" or "missing"), the project records its "mesh" as its texturing mesh
//       and the preflight's coverage is `CoverageForPreflight` over it, the mesh's bytes read
//       ("stored") or not stored ("missing": the re-derive fails); "mesh_reads" counts their reads.
//       Without it the coverage is the spec's mesh, or a known-absent mesh.
//   uzp-export-tests [--fault <point>[:<n>]] publish <templates dir> <spec.json> <config.json>
//                    [--uztexture <relativePath>[:fail|:rgb]] [--presets <preset dir>]
//       (phase1.17) As `export`, through `PublishExport`: the files and the receipt published as a
//       new generation under exportPath; the spec's mesh is also the project's imported mesh (a
//       resource). Prints {"generation", "receipt_sha256", "files": [{rootPath, relativePath,
//       path, size, sha256}]} or {"error": class, "message": text}. `--fault` arms a test-only
//       fault hook (src/export/fault.h). `--uztexture` requests the `.uztexture` normal derivative
//       of the planned file `relativePath` with that negative-Z policy, `fail` when none is given
//       (`RequestUzTextureNormal`, decision 316). `--presets` reads the shipped presets from that
//       directory instead of the one beside the executable (an authored variant of a preset).
//       `--execution-error <reason>` uses a CPU-delegating test store whose Execution() fails;
//       the result includes execution_calls and tile_calls to detect work before that refusal.
//   uzp-export-tests [--fault <point>[:<n>]] fixed-copy <exportPath> <dir>
//       (phase1.17) `CopyFixedNames`; prints {"generation", "files": [path...]} or {"error"}.
//   uzp-export-tests project <spec.json> <out.uzp>
//       (phase1.18) The project of a spec (its "mesh" imported as the project's mesh, its bitmaps
//       as resources) created as a `.uzp` file by the project store; prints {"project"}.
//   uzp-export-tests cli <args>...
//       (phase1.18) `UzPainter.exe export <args>...` (src/export/cli.h): the same output and exit
//       status.
//   uzp-export-tests consume-pinned <exportPath>
//   uzp-export-tests consume-locked <exportPath> <dir>
//       (phase1.17) A fixed-name test consumer through the generation-pinning adapter
//       (`OpenPinnedDelivery`) or under the publication lock (`LockedFixedNames`): reads every
//       file of the delivery by its fixed name and prints {"generation", "files": {path:
//       sha256 of the bytes read}} or {"error": "Failure", "message"} when it fails before
//       consumption.
//   uzp-export-tests receipt <project skeleton.json> <config.json> [<preset dir>]
//       (phase1.17) `BuildReceipt` of the compiled plan, each file's bytes standing in as its
//       relativePath (no evaluation); prints the receipt. The shipped presets are read from
//       <preset dir> when it is given.
//   uzp-export-tests hold-lock <exportPath> <milliseconds>
//       (phase1.17) Takes the publication lock, prints "held", keeps it for the given time.
//   uzp-export-tests recover --recover <exportPath> [--fixed-names <dir>]...
//       (phase1.17) `UzPainter.exe export --recover ...` (src/export/cli.h): the same output.
//
// A project skeleton: {"color_management"?, "config_hash"?, "workflow"?, "normal_map_format"?, "mesh"?: <mesh file
// name>, "texture_sets": [{"name", "original_name"?, "resolution"?: [w, h], "mesh_maps"?:
// [usage...], "stacks": [{"name", "channels":
// {type: format}, "layers"?: [uid...]}]}]}. A spec is the evaluator test spec
// (tests/evaluator/evaluator_test.cpp, `evaluate`) restricted to fill and group layers, plus
// "name" (the texture set's name), "mesh_maps" ({usage: resource sha256}) and "color_management"
// and "config_hash" (the project's colour management, legacy when absent).

#include "evaluator/admission.h"
#include "evaluator/arith.h"
#include "evaluator/cpu_store.h"
#include "evaluator/evaluator.h"
#include "evaluator/formats.h"
#include "evaluator/gpu_store.h"
#include "evaluator/profile.h"
#include "evaluator/sources.h"
#include "evaluator/templates.h"
#include "evaluator/geometry_mask.h"
#include "export/config.h"
#include "export/encode.h"
#include "export/cli.h"
#include "export/exr_writer.h"
#include "export/fault.h"
#include "export/fixed_names.h"
#include "export/guards.h"
#include "export/padding.h"
#include "export/plan.h"
#include "export/png_writer.h"
#include "export/tga_writer.h"
#include "export/preset_aliases.h"
#include "export/publish.h"
#include "export/virtual_maps.h"
#include "export/write.h"
#include "mesh/mesh_import.h"
#include "render/vulkan_backend.h"
#include "spng.h"
#include "store/project_store.h"
#include "uzp_core/document/nodes.h"
#include "uzp_core/manifest/json.h"
#include "uzp_core/manifest/manifest.h"
#include "uzp_core/manifest/sha256.h"
#include "uzp_core/types/errors.h"
#include "uzp_core/types/validation.h"

#include <algorithm>
#include <array>
#include <bit>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <iterator>
#include <limits>
#include <map>
#include <memory>
#include <optional>
#include <string>
#include <thread>
#include <vector>
#include "../no_error_dialogs.h"

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
    if (o.contains("config_hash")) project.settings.color_management.config_hash = Str(o.at("config_hash"), "hash");
    if (o.contains("workflow")) {
        project.settings.workflow = EnumOf<core::ProjectWorkflow>(Str(o.at("workflow"), "workflow"), "workflow");
    }
    if (o.contains("normal_map_format")) {
        project.settings.normal_map_format =
            EnumOf<core::NormalMapFormat>(Str(o.at("normal_map_format"), "normal_map_format"), "normal map format");
    }
    if (o.contains("mesh")) {
        // The imported mesh's file name, as its import report records it.
        project.mesh = core::MeshReference{
            std::string(64, 'b'), json::Object{{"source", json::Object{{"name", Str(o.at("mesh"), "mesh")}}}}, {}};
    }
    core::Id next = 1;
    for (const json::Value& s : Arr(Key(o, "texture_sets"), "texture_sets")) {
        const json::Object& so = Obj(s, "texture set");
        core::TextureSet set;
        set.id = next++;
        set.name = Str(Key(so, "name"), "name");
        set.original_name = so.contains("original_name") ? Str(so.at("original_name"), "original_name") : set.name;
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

void ApplyDdsRequests(exporter::ExportPlan& plan, const core::Project& project,
                      const json::Value& value) {
    for (const auto& entry : Arr(value, "dds")) {
        const auto& request = Obj(entry, "dds request");
        exporter::RequestDds(plan, project, Str(Key(request, "path"), "dds path"),
            static_cast<exporter::BcFormat>(static_cast<unsigned>(Num(Key(request, "format"), "dds format"))),
            static_cast<exporter::DerivativeMips>(static_cast<unsigned>(Num(Key(request, "mips"), "dds mips"))));
    }
}

int RunPlan(const fs::path& casesPath) {
    const json::Value cases = json::Parse(ReadText(casesPath));
    for (const json::Value& c : Arr(cases, "cases")) {
        const json::Object& o = Obj(c, "case");
        json::Object result;
        try {
            const core::Project project = ParseSkeleton(Key(o, "project"));
            const json::Value& config = Key(o, "config");
            exporter::PlanContext context;
            if (o.contains("project_path")) context.projectPath = Str(o.at("project_path"), "project_path");
            // Optional "presets": a directory read for the shipped presets instead of the installed one.
            exporter::ExportPlan plan =
                config.IsString()        ? exporter::CompilePlan(project, Str(config, "config"), context)
                : o.contains("presets") ? exporter::CompilePlan(
                                              project, exporter::ParseConfig(config, fs::path(Str(o.at("presets"), "presets"))),
                                              context)
                                        : exporter::CompilePlan(project, exporter::ParseConfig(config), context);
            // Optional "uztexture": [relativePath...], each requested after compilation
            // (`RequestUzTextureNormal`, policy fail).
            if (o.contains("uztexture")) {
                for (const json::Value& path : Arr(o.at("uztexture"), "uztexture")) {
                    exporter::RequestUzTextureNormal(plan, Str(path, "uztexture"));
                }
            }
            if (o.contains("dds")) ApplyDdsRequests(plan, project, o.at("dds"));
            result["plan"] = exporter::PlanJson(plan);
            try {
                exporter::CheckExportable(plan);
                result["list"] = ListJson(exporter::FilesByStack(plan));
            } catch (const core::ValueError& e) {
                result["list_error"] = std::string(e.what());
            }
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

/// A spec projection {"mode"?, "filtering_mode"?, "uv_wrapping_mode"?, "scale_mode"?, "scale"?,
/// "rotation"?, "offset"?} (as uzp-evaluator-tests reads it).
void ParseProjection(const json::Object& p, core::Projection& projection) {
    if (p.contains("mode")) projection.mode = EnumOf<core::ProjectionMode>(Str(p.at("mode"), "mode"), "projection mode");
    core::UVProjectionParams& uv = projection.uv;
    if (p.contains("filtering_mode")) {
        uv.filtering_mode = EnumOf<core::FilteringMode>(Str(p.at("filtering_mode"), "filtering_mode"), "filtering mode");
    }
    if (p.contains("uv_wrapping_mode")) {
        uv.uv_wrapping_mode = EnumOf<core::UVWrapMode>(Str(p.at("uv_wrapping_mode"), "uv_wrapping_mode"), "wrap mode");
    }
    core::UVTransformation& t = uv.uv_transformation;
    if (p.contains("scale_mode")) t.scale_mode = EnumOf<core::ScaleMode>(Str(p.at("scale_mode"), "scale_mode"), "scale mode");
    if (p.contains("scale")) {
        const json::Array& scale = Arr(p.at("scale"), "scale");
        t.scale = {Num(scale.at(0), "scale u"), Num(scale.at(1), "scale v")};
    }
    if (p.contains("rotation")) t.rotation = Num(p.at("rotation"), "rotation");
    if (p.contains("offset")) {
        const json::Array& offset = Arr(p.at("offset"), "offset");
        t.offset = {Num(offset.at(0), "offset u"), Num(offset.at(1), "offset v")};
    }
}

/// A spec mask {"background", "effects"?: [mask fill effect {"kind": "fill", "uid"?, "source"?,
/// "mode"?, "opacity"?, "projection"?}], top first} (as uzp-evaluator-tests reads it); other mask
/// effects are not modelled here.
core::Mask ParseMask(const json::Object& m, core::Project& project) {
    core::Mask mask;
    mask.background = EnumOf<core::MaskBackground>(Str(Key(m, "background"), "background"), "background");
    if (!m.contains("effects")) return mask;
    for (const json::Value& value : Arr(m.at("effects"), "mask.effects")) {
        const json::Object& e = Obj(value, "mask effect");
        if (Str(Key(e, "kind"), "effect.kind") != "fill") {
            throw core::ManifestError("mask effects other than fill are not modelled by the export tests");
        }
        core::Effect effect;
        effect.uid = e.contains("uid") ? static_cast<core::Id>(Num(e.at("uid"), "uid")) : project.AllocateId();
        effect.name = "fill";
        effect.kind = core::EffectKind::fill;
        core::FillContent fill;
        if (e.contains("projection")) ParseProjection(Obj(e.at("projection"), "projection"), fill.projection);
        if (e.contains("source")) fill.mono_source = ParseSource(Obj(e.at("source"), "source"));
        core::Blending blending;
        if (e.contains("mode")) blending.mode = EnumOf<core::BlendingMode>(Str(e.at("mode"), "mode"), "mode");
        if (e.contains("opacity")) blending.opacity = Num(e.at("opacity"), "opacity");
        effect.mono_blending = blending;
        effect.fill = std::move(fill);
        mask.effects.push_back(std::move(effect));
    }
    return mask;
}

core::Layer ParseLayer(const json::Value& value, core::Project& project) {
    const json::Object& o = Obj(value, "layer");
    const std::string kind = Str(Key(o, "kind"), "layer.kind");
    if (o.contains("effects")) {
        throw core::ManifestError("content effects are not modelled by the export tests (phase1.11's tests cover them)");
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
        if (o.contains("projection")) ParseProjection(Obj(o.at("projection"), "projection"), fill.projection);
        layer.fill = std::move(fill);
    } else if (kind == "group") {
        layer.kind = core::LayerKind::group;
        for (const json::Value& child : Arr(Key(o, "children"), "children")) {
            layer.children.push_back(ParseLayer(child, project));
        }
    } else {
        throw core::ManifestError("layer kind '" + kind + "' is not modelled by the export tests");
    }
    if (o.contains("mask")) layer.mask = ParseMask(Obj(o.at("mask"), "mask"), project);
    return layer;
}

struct Spec {
    core::Project project;
    std::string templateId{evaluator::kDefaultTemplateId};
    std::shared_ptr<evaluator::DecodingResourceProvider> resources;
    /// The texturing mesh's coverage ("mesh": an OBJ path), null without one.
    std::shared_ptr<const evaluator::IGeometryMaskProvider> geometry;
    /// That mesh, null without one.
    std::shared_ptr<const mesh::TexturingMesh> mesh;
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
    if (o.contains("color_management")) project.settings.color_management.mode = Str(o.at("color_management"), "cm");
    if (o.contains("config_hash")) project.settings.color_management.config_hash = Str(o.at("config_hash"), "hash");
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
        spec.mesh = mesh;
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

int RunExport(const fs::path& templatesDir, const fs::path& specPath, const fs::path& configPath,
              const std::optional<fs::path>& dds = std::nullopt, const std::string& backend = "cpu") {
    const Spec spec = ParseSpec(specPath);
    json::Object result;
    try {
        exporter::ExportPlan plan = exporter::CompilePlan(spec.project, ReadText(configPath));
        if (dds) ApplyDdsRequests(plan, spec.project, json::Parse(ReadText(*dds)));
        auto templates = std::make_shared<const evaluator::TemplateLibrary>(evaluator::TemplateLibrary::Load(templatesDir));
        evaluator::CpuEvaluator cpu(templates, evaluator::AdmissionLimits{64ull << 30, 1 << 20});
        exporter::SourceInputs inputs;
        inputs.templateId = spec.templateId;
        inputs.resources = spec.resources;
        inputs.geometry = spec.geometry;
        const auto write = [&](evaluator::ITileStore& store, evaluator::TileCache& cache) {
            return exporter::WriteExport(spec.project, 1, plan, inputs, *templates, store, cache);
        };
        auto written = [&]() -> render::Result<std::vector<exporter::WrittenFile>> {
            if (backend == "cpu") return write(cpu.store(), cpu.cache());
            if (backend != "dx12" && backend != "vulkan") throw std::invalid_argument("unknown export backend");
            render::EngineOptions options;
            options.kernelCacheRoot = configPath.parent_path() / ("kernel-cache-" + backend);
            if (backend == "vulkan") {
                options.device.backend = render::Backend::Vulkan;
                // Native diagnostic seam only; the product factory still refuses Vulkan.
                options.createDevice = []() -> render::Result<std::unique_ptr<render::IDevice>> {
                    const auto survey = render::SurveyVulkan();
                    const auto qualification = render::QualifyVulkan(survey, 0);
                    auto device = render::CreateQualifiedVulkanDevice(survey, qualification);
                    if (!device) return render::Unexpected(device.error());
                    return std::unique_ptr<render::IDevice>(std::move(*device));
                };
            }
            render::Engine engine(options);
            if (engine.DeviceError()) return render::Unexpected(*engine.DeviceError());
            const auto capabilities = engine.Capabilities();
            if (!capabilities) return render::Unexpected(capabilities.error());
            result["driver"] = capabilities->driver;
            return engine.Submit(std::make_shared<const int>(0),
                [&](render::EngineContext& context, const int&) -> render::Result<std::vector<exporter::WrittenFile>> {
                    result["adapter"] = context.Device().AdapterName();
                    evaluator::GpuTileStore gpu(context.Device());
                    evaluator::TileCache cache(evaluator::AdmissionLimits{64ull << 30, 1 << 20});
                    gpu.BeginRequest(context);
                    auto files = write(gpu, cache);
                    auto flushed = gpu.Flush();
                    gpu.EndRequest();
                    if (!flushed) return render::Unexpected(flushed.error());
                    return files;
                }).get();
        }();
        result["backend"] = backend;
        result["project_uuid"] = "00000000-0000-4000-8000-000000000118";
        result["revision"] = 1;
        result["project_sha256"] = core::Sha256Hex(json::WriteCanonical(core::ProjectToJson(spec.project)));
        result["evaluator_profile"] = spec.project.versions.evaluator_profile;
        json::Object resourceHashes;
        for (const auto& [hash, metadata] : spec.project.resources) resourceHashes[hash] = hash;
        if (spec.mesh) {
            const auto source = json::Parse(ReadText(specPath));
            resourceHashes["texturing_mesh"] = core::Sha256Hex(ReadText(
                fs::path(Str(Key(Obj(source, "spec"), "mesh"), "mesh"))));
        }
        result["resource_hashes"] = std::move(resourceHashes);
        if (!written && written.error().code == render::ErrorCode::GpuBackendUnavailable) {
            result["error"] = "GpuBackendUnavailable";
            result["message"] = written.error().reason;
            std::cout << json::WriteCanonical(result) << "\n";
            return 77;
        }
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
            json::Array bundleFiles;
            for (const auto& f : *written) {
                const auto planned = std::find_if(plan.files.begin(), plan.files.end(),
                    [&](const auto& p) { return p.relativePath == f.relativePath; });
                if (planned != plan.files.end())
                    bundleFiles.push_back(json::Object{{"texture_set", planned->textureSet},
                        {"map", planned->relativePath}, {"path", f.path}, {"sha256", f.sha256}});
            }
            result["files"] = std::move(bundleFiles);
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

/// `export-diagnostic`: as `export`, through `EncodeExport` with the diagnostic measure export
/// (write.h, decisions 286 and 308), each file written under exportPath at its relativePath.
int RunExportDiagnostic(const fs::path& templatesDir, const fs::path& specPath, const fs::path& configPath) {
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
        const exporter::DiagnosticMeasure diagnostic{spec.mesh};
        render::Result<std::vector<exporter::EncodedFile>> encoded = exporter::EncodeExport(
            spec.project, 1, plan, inputs, *templates, cpu.store(), cpu.cache(), &diagnostic);
        if (!encoded) {
            result["error"] = "Failure";
            result["message"] = encoded.error().reason;
        } else {
            json::Array files;
            for (size_t i = 0; i < plan.files.size(); ++i) {
                const fs::path path = fs::path(plan.exportPath) / fs::path(plan.files[i].relativePath);
                fs::create_directories(path.parent_path());
                std::ofstream(path, std::ios::binary)
                    .write((*encoded)[i].bytes.data(), static_cast<std::streamsize>((*encoded)[i].bytes.size()));
                json::Array bypassed;
                for (const std::string& refusal : (*encoded)[i].bypassed) bypassed.push_back(refusal);
                files.push_back(json::Object{{"relativePath", plan.files[i].relativePath},
                                             {"path", path.generic_string()},
                                             {"bypassed", std::move(bypassed)},
                                             {"undecided", static_cast<std::int64_t>((*encoded)[i].undecided)}});
            }
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

/// An 8- or 16-bit grey, grey and alpha, RGB or RGBA PNG decoded at native depth with spng.
exporter::PngImage DecodePng(const std::string& data) {
    std::unique_ptr<spng_ctx, decltype(&spng_ctx_free)> ctx(spng_ctx_new(0), &spng_ctx_free);
    spng_ihdr ihdr{};
    size_t size = 0;
    if (spng_set_png_buffer(ctx.get(), data.data(), data.size()) != 0 || spng_get_ihdr(ctx.get(), &ihdr) != 0 ||
        (ihdr.bit_depth != 8 && ihdr.bit_depth != 16) ||
        (ihdr.color_type != SPNG_COLOR_TYPE_GRAYSCALE && ihdr.color_type != SPNG_COLOR_TYPE_GRAYSCALE_ALPHA &&
         ihdr.color_type != SPNG_COLOR_TYPE_TRUECOLOR && ihdr.color_type != SPNG_COLOR_TYPE_TRUECOLOR_ALPHA) ||
        spng_decoded_image_size(ctx.get(), SPNG_FMT_PNG, &size) != 0) {
        throw core::ManifestError("not an 8- or 16-bit grey, grey and alpha, RGB or RGBA PNG");
    }
    const uint32_t channels = ihdr.color_type == SPNG_COLOR_TYPE_GRAYSCALE         ? 1u
                              : ihdr.color_type == SPNG_COLOR_TYPE_GRAYSCALE_ALPHA ? 2u
                              : ihdr.color_type == SPNG_COLOR_TYPE_TRUECOLOR       ? 3u
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

/// The measured ring (padding.h `MeasuredRing`): per ring texel {"x", "y", "taps", "triangles",
/// "fractions": [float32 bits], "candidates": [[x, y, distance, far]], "alternatives": [[...]],
/// "undecided": the flags of the rule that are set (padding.h `RingTexel`), of "fold-bracket",
/// "on-far-plane", "mixed-gates", "reach-bracket", "corner-reach-bracket", "window-side",
/// "own-far-tie", "own-order", "far-fold", "far-order", "multi-facet"}.
json::Value RingJson(const std::vector<exporter::RingTexel>& ring) {
    const auto taps = [](const std::vector<exporter::RingTap>& list) {
        json::Array out;
        for (const exporter::RingTap& t : list) {
            out.push_back(json::Array{static_cast<std::int64_t>(t.x), static_cast<std::int64_t>(t.y), t.distance,
                                      t.across_seam});
        }
        return out;
    };
    json::Array out;
    for (const exporter::RingTexel& r : ring) {
        json::Array fractions;
        for (const float t : r.fractions) fractions.push_back(static_cast<std::int64_t>(std::bit_cast<uint32_t>(t)));
        json::Array alternatives;
        for (const auto& list : r.alternatives) alternatives.push_back(taps(list));
        json::Array undecided;
        if (r.foldBracket) undecided.push_back("fold-bracket");
        if (r.onFarPlane) undecided.push_back("on-far-plane");
        if (r.mixedGates) undecided.push_back("mixed-gates");
        if (r.reachBracket) undecided.push_back("reach-bracket");
        if (r.cornerReachBracket) undecided.push_back("corner-reach-bracket");
        if (r.windowSide) undecided.push_back("window-side");
        if (r.ownFarTie) undecided.push_back("own-far-tie");
        if (r.ownOrder) undecided.push_back("own-order");
        if (r.farFold) undecided.push_back("far-fold");
        if (r.farOrder) undecided.push_back("far-order");
        if (r.multiFacet) undecided.push_back("multi-facet");
        out.push_back(json::Object{{"x", static_cast<std::int64_t>(r.x)},
                                   {"y", static_cast<std::int64_t>(r.y)},
                                   {"taps", static_cast<std::int64_t>(r.taps)},
                                   {"triangles", static_cast<std::int64_t>(r.triangles)},
                                   {"fractions", std::move(fractions)},
                                   {"candidates", taps(r.candidates)},
                                   {"alternatives", std::move(alternatives)},
                                   {"undecided", std::move(undecided)}});
    }
    return out;
}

/// `ring`: synthetic measured `infinite` padding over a mesh (test_export_encoders.py).
int RunRing(const fs::path& casesPath) {
    for (const json::Value& value : Arr(json::Parse(ReadText(casesPath)), "cases")) {
        const json::Object& c = Obj(value, "case");
        const auto width = static_cast<uint32_t>(Num(Key(c, "width"), "width"));
        const auto height = static_cast<uint32_t>(Num(Key(c, "height"), "height"));
        const auto channels = static_cast<uint32_t>(Num(Key(c, "channels"), "channels"));
        const std::string material = Str(Key(c, "material"), "material");
        const mesh::TexturingMesh mesh = mesh::ImportMeshFile(Str(Key(c, "mesh"), "mesh"), {}).mesh;
        const auto mask =
            evaluator::RasterizeGeometryMask(mesh, evaluator::GeometryMaskQuery{material, false, {}, width, height});
        exporter::Coverage coverage{width, height, {}};
        for (const uint16_t v : mask->values) coverage.covered.push_back(v != 0 ? 1 : 0);
        exporter::IslandTriangles(coverage, mesh, material);
        const std::string raw = ReadText(Str(Key(c, "values"), "values"));
        std::vector<float> values(raw.size() / sizeof(float));
        std::memcpy(values.data(), raw.data(), values.size() * sizeof(float));
        exporter::PlannedFile file;
        file.relativePath = "ring";
        file.width = width;
        file.height = height;
        file.layout = channels == 1 ? exporter::FileLayout::L : exporter::FileLayout::RGB;
        exporter::ResolvedParameters parameters;
        parameters.fileFormat = exporter::FileFormat::exr;
        parameters.bitDepth = exporter::BitDepth::f32;
        file.parameters = parameters;
        exporter::ApplyPadding(file, coverage, channels, values, exporter::InexactPadding::measure);
        std::ofstream(Str(Key(c, "out"), "out"), std::ios::binary)
            .write(reinterpret_cast<const char*>(values.data()),
                   static_cast<std::streamsize>(values.size() * sizeof(float)));
        std::cout << json::WriteCanonical(json::Object{{"ring", RingJson(exporter::MeasuredRing(coverage))}}) << "\n";
    }
    return 0;
}

/// The values of `png`, which `file` writes from documentMap channels stored as `format`: per
/// channel and code, the operand of `format` that EncodeFile writes as that code (each UNORM or
/// sRGB8 code's operand, or each finite half, written once through the channel's encode). When
/// several write one code (a 16-bit float Height near 0), the one nearest the code's UNORM operand
/// u (2u - 1 for a Height) is taken, the lower on a tie. Throws when a code has none.
std::vector<float> DocumentOperands(const exporter::PlannedFile& file, const std::vector<uint8_t>& srgbEncoded,
                                    bool ocio, ChannelFormat format, const exporter::PngImage& png) {
    const uint32_t bits = file.parameters->bitDepth == exporter::BitDepth::u8 ? 8 : 16;
    if (file.parameters->fileFormat != exporter::FileFormat::png || png.bitDepth != bits ||
        png.channels != file.channels.size()) {
        throw std::invalid_argument("process: document_format reads a PNG source of the case's depth and channels");
    }
    const evaluator::TileFormat tile = evaluator::TileFormatOf(format);
    std::vector<float> candidates;
    switch (tile.encoding) {
        case render::TexelEncoding::Unorm8:
        case render::TexelEncoding::Unorm16:
            for (uint32_t k = 0; k < (tile.encoding == render::TexelEncoding::Unorm8 ? 256u : 65536u); ++k) {
                candidates.push_back(evaluator::OperandOf(k, tile, 0));
            }
            break;
        case render::TexelEncoding::Float16:
            for (uint32_t h = 0; h < 65536; ++h) {
                const float v = evaluator::arith::HalfToFloat(static_cast<uint16_t>(h));
                if (std::isfinite(v)) candidates.push_back(v);
            }
            break;
        case render::TexelEncoding::Float32:
            throw std::invalid_argument("process: a 32-bit float document_format needs an OpenEXR source");
    }
    std::vector<float> values(png.samples.size());
    for (uint32_t c = 0; c < png.channels; ++c) {
        exporter::PlannedFile one = file;
        one.width = static_cast<uint32_t>(candidates.size());
        one.height = 1;
        one.layout = exporter::FileLayout::L;
        one.channels = {file.channels[c]};
        const exporter::FileRaster row{one.width, 1, 1, candidates, std::nullopt, std::nullopt,
                                       {srgbEncoded[c]}, ocio, {}};
        const exporter::PngImage written = DecodePng(exporter::EncodeFile(one, row).bytes);
        const bool height = file.channels[c].source.channel == ChannelType::Height;
        std::map<uint32_t, float> operand;
        for (size_t i = 0; i < candidates.size(); ++i) {
            const uint32_t code = written.samples[i];
            const double u = evaluator::arith::UnormOperand(code, bits);
            const double target = height ? 2.0 * u - 1.0 : u;
            const auto it = operand.find(code);
            if (it == operand.end() || std::abs(candidates[i] - target) < std::abs(it->second - target) ||
                (std::abs(candidates[i] - target) == std::abs(it->second - target) && candidates[i] < it->second)) {
                operand[code] = candidates[i];
            }
        }
        for (size_t t = 0; t < size_t{png.width} * png.height; ++t) {
            const uint32_t code = png.samples[t * png.channels + c];
            const auto it = operand.find(code);
            if (it == operand.end()) {
                throw std::invalid_argument("process: the code " + std::to_string(code) + " of " + file.relativePath +
                                            " is not written from any " + std::string(core::ToString(format)) +
                                            " operand");
            }
            values[t * png.channels + c] = it->second;
        }
    }
    return values;
}

/// `process`: Painter's own file of a map as the raster, through EncodeFile with the case's
/// processing; compared with Painter's file of that processing.
int RunProcess(const fs::path& casesPath) {
    for (const json::Value& value : Arr(json::Parse(ReadText(casesPath)), "cases")) {
        const json::Object& c = Obj(value, "case");
        const std::string source = ReadText(Str(Key(c, "source"), "source"));
        uint32_t width = 0;
        uint32_t height = 0;
        uint32_t channels = 0;
        std::vector<float> values;
        if (source.starts_with("\x89PNG")) {
            const exporter::PngImage png = DecodePng(source);
            width = png.width;
            height = png.height;
            channels = png.channels;
            for (const uint16_t sample : png.samples) values.push_back(evaluator::arith::UnormOperand(sample, png.bitDepth));
        } else {
            exporter::ExrImage exr = exporter::DecodeExr(source);
            width = exr.width;
            height = exr.height;
            channels = exr.channels;
            values = std::move(exr.values);
        }
        const bool opaque = c.contains("append_opaque_alpha") && std::get<bool>(c.at("append_opaque_alpha").data);
        if (opaque) {
            std::vector<float> withAlpha;
            for (size_t t = 0; t < size_t{width} * height; ++t) {
                withAlpha.insert(withAlpha.end(), values.begin() + static_cast<std::ptrdiff_t>(t * channels),
                                 values.begin() + static_cast<std::ptrdiff_t>((t + 1) * channels));
                withAlpha.push_back(1.0f);
            }
            values = std::move(withAlpha);
            ++channels;
        }
        static constexpr std::array<exporter::FileLayout, 5> kLayouts{
            exporter::FileLayout::L, exporter::FileLayout::L, exporter::FileLayout::LA, exporter::FileLayout::RGB,
            exporter::FileLayout::RGBA};
        static constexpr std::array<std::array<exporter::ChannelLetter, 4>, 5> kLetters{{
            {},
            {exporter::ChannelLetter::L},
            {exporter::ChannelLetter::L, exporter::ChannelLetter::A},
            {exporter::ChannelLetter::R, exporter::ChannelLetter::G, exporter::ChannelLetter::B},
            {exporter::ChannelLetter::R, exporter::ChannelLetter::G, exporter::ChannelLetter::B,
             exporter::ChannelLetter::A},
        }};
        exporter::PlannedFile file;
        file.relativePath = Str(Key(c, "target"), "target");
        file.width = width;
        file.height = height;
        file.layout = kLayouts.at(channels);
        const bool heightChannel = c.contains("height") && std::get<bool>(c.at("height").data);
        for (uint32_t i = 0; i < channels; ++i) {
            exporter::PlannedChannel channel;
            channel.dest = kLetters[channels][i];
            channel.source.type = exporter::SourceType::documentMap;
            if (heightChannel && i == 0) channel.source.channel = ChannelType::Height;
            file.channels.push_back(channel);
        }
        exporter::ResolvedParameters parameters;
        parameters.fileFormat = Str(Key(c, "format"), "format") == "exr" ? exporter::FileFormat::exr : exporter::FileFormat::png;
        const std::string depth = Str(Key(c, "bit_depth"), "bit_depth");
        parameters.bitDepth = depth == "8"     ? exporter::BitDepth::u8
                              : depth == "16"  ? exporter::BitDepth::u16
                              : depth == "16f" ? exporter::BitDepth::f16
                                               : exporter::BitDepth::f32;
        parameters.dithering = c.contains("dithering") && std::get<bool>(c.at("dithering").data);
        file.parameters = parameters;
        const bool srgb8Material = c.contains("srgb8_material") && std::get<bool>(c.at("srgb8_material").data);
        const bool l8Material = c.contains("l8_material") && std::get<bool>(c.at("l8_material").data);
        std::vector<uint8_t> srgbEncoded(channels, srgb8Material ? 1 : 0);
        for (uint32_t i = 0; l8Material && i < channels; ++i) {
            srgbEncoded[i] = exporter::SrgbEncodedRead(ChannelType::Specular, ChannelFormat::L8, kLetters[channels][i]);
        }
        const bool ocio = c.contains("ocio") && std::get<bool>(c.at("ocio").data);
        // `document_format` (with a PNG source): every channel reads a documentMap stored in that
        // format (decision 274's padding domain), so each code is read back as the operand of that
        // format whose write gives it (`DocumentOperands`).
        std::vector<std::optional<ChannelFormat>> documentFormat;
        if (c.contains("document_format")) {
            const std::string name = Str(c.at("document_format"), "document_format");
            const std::optional<ChannelFormat> format = core::FromString<ChannelFormat>(name);
            if (!format) throw std::invalid_argument("process: unknown document_format " + name);
            documentFormat.assign(channels, *format);
            if (source.starts_with("\x89PNG")) {
                values = DocumentOperands(file, srgbEncoded, ocio, *format, DecodePng(source));
            }
        }
        const exporter::FileRaster raster{width,
                                          height,
                                          channels,
                                          std::move(values),
                                          std::nullopt,
                                          std::nullopt,
                                          std::move(srgbEncoded),
                                          ocio,
                                          std::move(documentFormat)};
        // `mesh` (and `material`): the case is padded `infinite` over that mesh's texel-centre
        // coverage and triangles first (padding.h), measured: the export refuses that padding
        // (decision 259); `coverage_out` receives the coverage, one byte per texel, and `ring_out`
        // the measured ring (`RingJson`).
        std::int64_t coveredTexels = -1;
        std::optional<exporter::Coverage> padding;
        if (c.contains("mesh")) {
            const mesh::TexturingMesh mesh = mesh::ImportMeshFile(Str(c.at("mesh"), "mesh"), {}).mesh;
            const auto mask = evaluator::RasterizeGeometryMask(
                mesh, evaluator::GeometryMaskQuery{Str(Key(c, "material"), "material"), false, {}, width, height});
            exporter::Coverage coverage{width, height, {}};
            for (const uint16_t value : mask->values) coverage.covered.push_back(value != 0 ? 1 : 0);
            exporter::IslandTriangles(coverage, mesh, Str(Key(c, "material"), "material"));
            coveredTexels = std::count(coverage.covered.begin(), coverage.covered.end(), uint8_t{1});
            if (c.contains("coverage_out")) {
                std::ofstream(Str(c.at("coverage_out"), "coverage_out"), std::ios::binary)
                    .write(reinterpret_cast<const char*>(coverage.covered.data()),
                           static_cast<std::streamsize>(coverage.covered.size()));
            }
            if (c.contains("ring_out") && !coverage.Complete()) {
                std::ofstream(Str(c.at("ring_out"), "ring_out"), std::ios::binary)
                    << json::WriteCanonical(RingJson(exporter::MeasuredRing(coverage)));
            }
            padding = std::move(coverage);
        }
        const exporter::EncodedImage encoded =
            exporter::EncodeFile(file, raster, padding ? &*padding : nullptr, exporter::InexactPadding::measure);
        if (c.contains("out")) {
            std::ofstream(Str(c.at("out"), "out"), std::ios::binary)
                .write(encoded.bytes.data(), static_cast<std::streamsize>(encoded.bytes.size()));
        }
        const std::string target = ReadText(file.relativePath);
        std::cout << json::WriteCanonical(json::Object{{"target", file.relativePath},
                                                       {"covered_texels", coveredTexels},
                                                       {"equal", encoded.bytes == target},
                                                       {"layout", std::string(exporter::FileLayoutName(encoded.layout))},
                                                       {"size", static_cast<std::int64_t>(encoded.bytes.size())},
                                                       {"target_size", static_cast<std::int64_t>(target.size())}})
                  << "\n";
    }
    return 0;
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

// ── Publication and fixed-name delivery (phase1.17) ─────────────────────────

json::Object FailureJson(const render::Error& error) {
    return json::Object{{"error", "Failure"}, {"message", error.reason}};
}

class ExecutionFaultStore final : public evaluator::ITileStore {
public:
    ExecutionFaultStore(evaluator::ITileStore& delegate, std::string reason)
        : delegate_(delegate), reason_(std::move(reason)) {}
    render::Result<evaluator::ExecutionIdentity> Execution() const override {
        ++executionCalls;
        return render::Fail(render::ErrorCode::RequestFailed, std::nullopt, reason_);
    }
    render::Result<evaluator::TileHandle> Allocate(const evaluator::TileFormat& format,
                                                  uint32_t width, uint32_t height) override {
        ++tileCalls;
        return delegate_.Allocate(format, width, height);
    }
    void Release(evaluator::TileHandle tile) override { ++tileCalls; delegate_.Release(tile); }
    render::Result<void> Upload(evaluator::TileHandle tile, const evaluator::DecodedImage& image,
                                uint32_t x0, uint32_t y0) override {
        ++tileCalls;
        return delegate_.Upload(tile, image, x0, y0);
    }
    render::Result<void> Project(const evaluator::ProjectOp& op) override {
        ++tileCalls; return delegate_.Project(op);
    }
    render::Result<void> Blend(const evaluator::BlendOp& op) override {
        ++tileCalls; return delegate_.Blend(op);
    }
    render::Result<void> Levels(const evaluator::LevelsOp& op) override {
        ++tileCalls; return delegate_.Levels(op);
    }
    render::Result<void> VirtualNormal(const evaluator::VirtualNormalOp& op) override {
        ++tileCalls; return delegate_.VirtualNormal(op);
    }
    render::Result<void> Flush() override { ++tileCalls; return delegate_.Flush(); }
    render::Result<evaluator::TileImage> Read(evaluator::TileHandle tile) override {
        ++tileCalls; return delegate_.Read(tile);
    }
    uint64_t AllocatedBytes() const override { ++tileCalls; return delegate_.AllocatedBytes(); }
    mutable std::int64_t executionCalls = 0;
    mutable std::int64_t tileCalls = 0;
private:
    evaluator::ITileStore& delegate_;
    std::string reason_;
};

int RunPublish(const fs::path& templatesDir, const fs::path& specPath, const fs::path& configPath,
               const std::optional<std::string>& uztexture, const std::optional<fs::path>& presets,
               const std::optional<fs::path>& dds, const std::optional<std::string>& executionError,
               const std::optional<std::string>& publicationCheckpoint) {
    Spec spec = ParseSpec(specPath);
    const json::Value document = json::Parse(ReadText(specPath));
    const json::Object& o = Obj(document, "spec");
    if (o.contains("mesh")) {
        const fs::path meshPath(Str(o.at("mesh"), "mesh"));
        const std::string bytes = ReadText(meshPath);
        const std::string sha = core::Sha256Hex(bytes);
        core::ResourceMeta meta;
        meta.id = spec.project.AllocateId();
        meta.name = meshPath.filename().string();
        meta.mime = "model/obj";
        meta.size = static_cast<std::int64_t>(bytes.size());
        meta.usage = "mesh";
        meta.origin = "test";
        meta.imported_at = "2026-10-12T00:00:00Z";
        spec.project.resources[sha].push_back(std::move(meta));
        spec.project.mesh = core::MeshReference{
            sha, json::Object{{"source", json::Object{{"name", meshPath.filename().string()}}}}, {}};
        core::Validate(spec.project);
    }
    json::Object result;
    try {
        const json::Value configJson = json::Parse(ReadText(configPath));
        exporter::ExportPlan plan = exporter::CompilePlan(
            spec.project, presets ? exporter::ParseConfig(configJson, *presets) : exporter::ParseConfig(configJson));
        if (uztexture) {
            const size_t colon = uztexture->rfind(':');
            const exporter::NegativeZPolicy policy = colon == std::string::npos
                                                         ? exporter::NegativeZPolicy::fail
                                                         : exporter::ParseNegativeZPolicy(uztexture->substr(colon + 1));
            exporter::RequestUzTextureNormal(plan, uztexture->substr(0, colon), policy);
        }
        if (dds) ApplyDdsRequests(plan, spec.project, json::Parse(ReadText(*dds)));
        auto templates = std::make_shared<const evaluator::TemplateLibrary>(evaluator::TemplateLibrary::Load(templatesDir));
        evaluator::CpuEvaluator cpu(templates, evaluator::AdmissionLimits{64ull << 30, 1 << 20});
        exporter::SourceInputs inputs;
        inputs.templateId = spec.templateId;
        inputs.resources = spec.resources;
        inputs.geometry = spec.geometry;
        exporter::PublishRequest request;
        request.identity = {"0.0.0-test", "uzp-export-tests"};
        request.projectPath = "C:/projects/fixture.uzp";
        std::int64_t checkpointCalls = 0;
        if (publicationCheckpoint) {
            const int failAt = std::stoi(*publicationCheckpoint);
            request.beforePublish = [&, failAt]() -> render::Result<void> {
                if (++checkpointCalls == failAt) {
                    return render::Fail(render::ErrorCode::RequestFailed, std::nullopt,
                                        "test-only publication checkpoint failure");
                }
                return {};
            };
        }
        ExecutionFaultStore faultStore(cpu.store(), executionError.value_or(""));
        evaluator::ITileStore& tileStore = executionError ? static_cast<evaluator::ITileStore&>(faultStore) : cpu.store();
        render::Result<exporter::Publication> published =
            exporter::PublishExport(spec.project, 1, plan, inputs, *templates, tileStore, cpu.cache(), request);
        if (!published) {
            result = FailureJson(published.error());
        } else {
            json::Array files;
            for (const exporter::WrittenFile& f : published->files) {
                files.push_back(json::Object{{"rootPath", f.rootPath},
                                             {"relativePath", f.relativePath},
                                             {"path", f.path},
                                             {"size", static_cast<std::int64_t>(f.size)},
                                             {"sha256", f.sha256}});
            }
            result["generation"] = published->generation;
            result["receipt_sha256"] = published->receiptSha256;
            result["files"] = std::move(files);
        }
        if (publicationCheckpoint) result["checkpoint_calls"] = checkpointCalls;
        if (executionError) {
            result["execution_calls"] = faultStore.executionCalls;
            result["tile_calls"] = faultStore.tileCalls;
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

/// `project`: the project of a spec, with its mesh as the imported mesh, created as a `.uzp` file.
int RunProject(const fs::path& specPath, const fs::path& out) {
    Spec spec = ParseSpec(specPath);
    const json::Value document = json::Parse(ReadText(specPath));
    const json::Object& o = Obj(document, "spec");
    store::CreateOptions options;
    for (const json::Value& entry : Arr(Key(o, "resources"), "resources")) {
        const json::Object& r = Obj(entry, "resource");
        options.resources.push_back({ReadText(specPath.parent_path() / Str(Key(r, "png"), "png")), "image/png"});
    }
    if (o.contains("mesh")) {
        const fs::path meshPath(Str(o.at("mesh"), "mesh"));
        std::string bytes = ReadText(meshPath);
        const std::string sha = core::Sha256Hex(bytes);
        const mesh::ImportResult imported = mesh::ImportMeshFile(meshPath, {});
        core::ResourceMeta meta;
        meta.id = spec.project.AllocateId();
        meta.name = meshPath.filename().string();
        meta.mime = "model/obj";
        meta.size = static_cast<std::int64_t>(bytes.size());
        meta.usage = "mesh";
        meta.origin = meshPath.generic_string();
        meta.imported_at = "2026-10-12T00:00:00Z";
        spec.project.resources[sha].push_back(std::move(meta));
        spec.project.mesh = core::MeshReference{sha, imported.report, {}};
        options.resources.push_back({std::move(bytes), "model/obj"});
    }
    core::Validate(spec.project);
    core::DocumentState state;
    state.project_uuid = "00000000-0000-4000-8000-000000000118";
    state.project = std::move(spec.project);
    store::ProjectStore::Create(out, state, options)->Close();
    std::cout << json::WriteCanonical(json::Object{{"project", out.generic_string()}}) << "\n";
    return 0;
}

int RunFixedCopy(const fs::path& exportPath, const fs::path& directory) {
    render::Result<exporter::Delivery> delivery = exporter::CopyFixedNames(exportPath, directory);
    json::Object result;
    if (!delivery) {
        result = FailureJson(delivery.error());
    } else {
        json::Array files;
        for (const exporter::ReceiptFile& f : delivery->files) files.emplace_back(f.path);
        result["generation"] = delivery->generation;
        result["files"] = std::move(files);
    }
    std::cout << json::WriteCanonical(result) << "\n";
    return 0;
}

/// The fixed-name test consumer: every file of the delivery read by its fixed name.
int RunConsume(const fs::path& exportPath, const std::optional<fs::path>& directory) {
    json::Object result;
    const auto consume = [&](const exporter::Delivery& delivery) {
        json::Object files;
        for (const exporter::ReceiptFile& f : delivery.files) {
            files[f.path] = core::Sha256Hex(ReadText(delivery.directory / exporter::Utf8Path(f.path)));
        }
        result["generation"] = delivery.generation;
        result["files"] = std::move(files);
    };
    if (directory) {
        render::Result<exporter::LockedFixedNames> locked = exporter::LockedFixedNames::Open(exportPath, *directory);
        if (!locked) {
            result = FailureJson(locked.error());
        } else {
            consume(locked->delivery());
        }
    } else {
        render::Result<exporter::Delivery> pinned = exporter::OpenPinnedDelivery(exportPath);
        if (!pinned) {
            result = FailureJson(pinned.error());
        } else {
            consume(*pinned);
        }
    }
    std::cout << json::WriteCanonical(result) << "\n";
    return 0;
}

int RunReceipt(const fs::path& projectPath, const fs::path& configPath, const std::optional<fs::path>& presets) {
    const core::Project project = ParseSkeleton(json::Parse(ReadText(projectPath)));
    const exporter::ExportPlan plan =
        presets ? exporter::CompilePlan(project, exporter::ParseConfig(json::Parse(ReadText(configPath)), *presets))
                : exporter::CompilePlan(project, ReadText(configPath));
    std::vector<exporter::EncodedFile> encoded;
    for (const exporter::PlannedFile& file : plan.files) encoded.push_back({file.relativePath, std::nullopt, file.layout});
    std::cout << json::WriteCanonical(exporter::BuildReceipt(
                     {project, 1, plan, encoded, "000001", "2026-10-12T00:00:00Z", "", {"0.0.0-test", "uzp-export-tests"}, {}}))
              << "\n";
    return 0;
}

int RunHoldLock(const fs::path& exportPath, const std::string& milliseconds) {
    render::Result<exporter::PublicationLock> lock = exporter::PublicationLock::Acquire(exportPath);
    if (!lock) {
        std::cout << json::WriteCanonical(FailureJson(lock.error())) << std::endl;
        return 1;
    }
    std::cout << "held" << std::endl;
    std::this_thread::sleep_for(std::chrono::milliseconds(std::stoll(milliseconds)));
    return 0;
}

}  // namespace

// ── Dry-run preflight (SUP-035) ─────────────────────────────────────────────

namespace {

int RunPreflight(const fs::path& templatesDir, const fs::path& specPath, const fs::path& configPath) {
    const Spec spec = ParseSpec(specPath);
    const exporter::ExportPlan plan = exporter::CompilePlan(spec.project, ReadText(configPath));
    json::Object result{{"plan", exporter::PlanJson(plan)}};
    // The preflight reads the coverage only: every resource read is counted.
    auto reads = std::make_shared<size_t>(0);
    exporter::SourceInputs counted;
    counted.resources = std::make_shared<evaluator::DecodingResourceProvider>(
        [reads](std::string_view) -> std::optional<std::string> {
            ++*reads;
            return std::nullopt;
        });
    counted.geometry = spec.geometry;
    exporter::CoverageGap gap{!spec.geometry, "the spec has no mesh"};
    const json::Value document = json::Parse(ReadText(specPath));
    const json::Object& o = Obj(document, "spec");
    if (o.contains("mesh_reference")) {
        const std::string stored = Str(o.at("mesh_reference"), "mesh_reference");
        const fs::path meshPath(Str(Key(o, "mesh"), "mesh"));
        std::string bytes = ReadText(meshPath);
        const std::string sha = core::Sha256Hex(bytes);
        core::Project project = spec.project;
        project.mesh = core::MeshReference{sha, mesh::ImportMeshFile(meshPath, {}).report, {}};
        size_t meshReads = 0;
        exporter::PreflightCoverage coverage =
            exporter::CoverageForPreflight(project, [&](const std::string& wanted) -> std::string {
                ++meshReads;
                if (stored != "stored" || wanted != sha) {
                    throw std::runtime_error("resource " + wanted + " is not stored");
                }
                return bytes;
            });
        result["mesh_reads"] = static_cast<std::int64_t>(meshReads);
        counted.geometry = coverage.inputs.geometry;
        gap = coverage.gap;
    }
    result["preflight"] = exporter::PreflightJson(exporter::PreflightExport(spec.project, plan, counted, gap));
    result["resource_reads"] = static_cast<std::int64_t>(*reads);
    result["plan_after"] = exporter::PlanJson(plan);
    result["written_before_export"] = fs::exists(exporter::Utf8Path(plan.exportPath));
    json::Object exported;
    try {
        auto templates = std::make_shared<const evaluator::TemplateLibrary>(evaluator::TemplateLibrary::Load(templatesDir));
        evaluator::CpuEvaluator cpu(templates, evaluator::AdmissionLimits{64ull << 30, 1 << 20});
        exporter::SourceInputs inputs;
        inputs.templateId = spec.templateId;
        inputs.resources = spec.resources;
        inputs.geometry = spec.geometry;
        render::Result<std::vector<exporter::WrittenFile>> written =
            exporter::WriteExport(spec.project, 1, plan, inputs, *templates, cpu.store(), cpu.cache());
        if (!written) {
            exported["error"] = "Failure";
            exported["message"] = written.error().reason;
        } else {
            json::Array files;
            for (const exporter::WrittenFile& f : *written) files.emplace_back(f.relativePath);
            exported["written"] = std::move(files);
        }
    } catch (const core::NotYetSupported& e) {
        exported["error"] = "NotYetSupported";
        exported["message"] = std::string(e.what());
    }
    result["export"] = std::move(exported);
    std::cout << json::WriteCanonical(result) << "\n";
    return 0;
}

}  // namespace

// ── Shipped presets (phase1.17) ─────────────────────────────────────────────

std::string_view LayoutName(exporter::PresetLayout layout) {
    switch (layout) {
        case exporter::PresetLayout::pipeline: return "pipeline";
        case exporter::PresetLayout::confirmed: return "confirmed";
        case exporter::PresetLayout::unconfirmed: return "unconfirmed";
        case exporter::PresetLayout::consumer: return "consumer";
    }
    return "";
}

int RunPresets(const fs::path& directory, const fs::path& referencesPath) {
    const json::Value document = json::Parse(ReadText(referencesPath));
    for (const json::Value& r : Arr(Key(Obj(document, "document"), "references"), "references")) {
        const std::string reference = Str(r, "reference");
        json::Object result{{"reference", reference}};
        try {
            const std::optional<std::string> id = exporter::ShippedPresetId(reference);
            if (!id) {
                result["id"] = nullptr;
            } else {
                const exporter::ShippedPreset preset = exporter::LoadShippedPreset(directory, *id);
                result["id"] = *id;
                result["name"] = preset.spec.name;
                result["layout"] = LayoutName(preset.layout);
                json::Array pending;
                for (const std::string& recording : preset.pendingRecordings) pending.emplace_back(recording);
                result["pending"] = std::move(pending);
                json::Array maps;
                for (const exporter::MapSpec& map : preset.spec.maps) maps.emplace_back(map.fileName);
                result["maps"] = std::move(maps);
            }
        } catch (const core::ValueError& e) {
            result["error"] = "ValueError";
            result["message"] = std::string(e.what());
        } catch (const core::NotYetSupported& e) {
            result["error"] = "NotYetSupported";
            result["message"] = std::string(e.what());
        } catch (const core::ManifestError& e) {
            result["error"] = "ManifestError";
            result["message"] = std::string(e.what());
        }
        std::cout << json::WriteCanonical(result) << "\n";
    }
    return 0;
}

int RunAliases() {
    json::Array shipped;
    for (std::string_view id : exporter::ShippedPresetIds()) shipped.emplace_back(id);
    json::Array aliases;
    for (const exporter::PresetAlias& alias : exporter::PresetAliases()) {
        json::Array versions;
        for (std::string_view v : alias.versions) versions.emplace_back(v);
        aliases.push_back(json::Array{alias.painterName, alias.presetId, std::move(versions)});
    }
    std::cout << json::WriteCanonical(json::Object{{"shipped", std::move(shipped)}, {"aliases", std::move(aliases)}})
              << "\n";
    return 0;
}

int RunTga(const std::vector<std::string>& args) {
    const std::string raw = ReadText(args[4]);
    exporter::TgaImage image{static_cast<uint32_t>(std::stoul(args[1])),
                             static_cast<uint32_t>(std::stoul(args[2])),
                             static_cast<uint32_t>(std::stoul(args[3])),
                             std::vector<uint8_t>(raw.begin(), raw.end())};
    const std::string bytes = exporter::EncodeTga(image);
    if (bytes != exporter::EncodeTga(image)) throw std::runtime_error("TGA8: nondeterministic encoding");
    std::ofstream output(args[5], std::ios::binary);
    output.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
    if (!output) throw std::runtime_error("TGA8: test output write failed");
    return 0;
}

int RunSnapshotSource(const std::filesystem::path& path, std::optional<int64_t> seed);
int RunProceduralEffects(const std::filesystem::path& path);

int main(int argc, char** argv) {
    std::vector<std::string> args(argv + 1, argv + argc);
    try {
        if ((args.size() == 2 || args.size() == 3) && args[0] == "snapshot-source")
            return RunSnapshotSource(args[1], args.size() == 3 ? std::optional<int64_t>(std::stoll(args[2])) : std::nullopt);
        if (args.size() == 2 && args[0] == "procedural-effects") return RunProceduralEffects(args[1]);
        if (args.size() == 6 && args[0] == "tga") return RunTga(args);
        if (args.size() >= 2 && args[0] == "--fault") {
            exporter::fault::Arm(args[1]);
            args.erase(args.begin(), args.begin() + 2);
        }
        if (args.size() >= 4 && args.size() % 2 == 0 && args[0] == "publish") {
            std::optional<std::string> uztexture;
            std::optional<fs::path> presets;
            std::optional<fs::path> dds;
            std::optional<std::string> executionError;
            std::optional<std::string> publicationCheckpoint;
            bool known = true;
            for (size_t i = 4; i < args.size(); i += 2) {
                if (args[i] == "--uztexture") uztexture = args[i + 1];
                else if (args[i] == "--presets") presets = fs::path(args[i + 1]);
                else if (args[i] == "--dds") dds = fs::path(args[i + 1]);
                else if (args[i] == "--execution-error") executionError = args[i + 1];
                else if (args[i] == "--publication-checkpoint") publicationCheckpoint = args[i + 1];
                else known = false;
            }
            if (known) return RunPublish(args[1], args[2], args[3], uztexture, presets, dds, executionError, publicationCheckpoint);
        }
        if (args.size() == 3 && args[0] == "fixed-copy") return RunFixedCopy(args[1], args[2]);
        if (args.size() == 3 && args[0] == "project") return RunProject(args[1], args[2]);
        if (!args.empty() && args[0] == "cli") {
            std::vector<std::string> verb(args);
            verb[0] = "export";
            return exporter::RunExportCommand(verb, stdout, stderr);
        }
        if (args.size() == 2 && args[0] == "consume-pinned") return RunConsume(args[1], std::nullopt);
        if (args.size() == 3 && args[0] == "consume-locked") return RunConsume(args[1], fs::path(args[2]));
        if (args.size() == 3 && args[0] == "receipt") return RunReceipt(args[1], args[2], std::nullopt);
        if (args.size() == 4 && args[0] == "receipt") return RunReceipt(args[1], args[2], fs::path(args[3]));
        if (args.size() == 3 && args[0] == "hold-lock") return RunHoldLock(args[1], args[2]);
        if (!args.empty() && args[0] == "recover") {
            std::vector<std::string> verb(args);
            verb[0] = "export";
            return exporter::RunExportCommand(verb, stdout, stderr);
        }
        if (args.size() == 2 && args[0] == "plan") return RunPlan(args[1]);
        if (args.size() == 5 && args[0] == "files") return RunFiles(args[1], args[2], args[3], args[4]);
        if (args.size() == 4 && args[0] == "export") return RunExport(args[1], args[2], args[3]);
        if (args.size() == 5 && args[0] == "export-backend")
            return RunExport(args[2], args[3], args[4], std::nullopt, args[1]);
        if (args.size() == 6 && args[0] == "export" && args[4] == "--dds") {
            return RunExport(args[1], args[2], args[3], fs::path(args[5]));
        }
        if (args.size() == 4 && args[0] == "export-diagnostic") return RunExportDiagnostic(args[1], args[2], args[3]);
        if (args.size() == 2 && args[0] == "reencode") return RunReencode(args[1]);
        if (args.size() == 2 && args[0] == "roundtrip") return RunRoundtrip(args[1]);
        if (args.size() == 2 && args[0] == "process") return RunProcess(args[1]);
        if (args.size() == 2 && args[0] == "ring") return RunRing(args[1]);
        if (args.size() == 3 && args[0] == "presets") return RunPresets(args[1], args[2]);
        if (args.size() == 4 && args[0] == "preflight") return RunPreflight(args[1], args[2], args[3]);
        if (args.size() == 1 && args[0] == "aliases") return RunAliases();
    } catch (const std::exception& e) {
        std::cerr << "uzp-export-tests: " << e.what() << "\n";
        return 2;
    }
    std::cerr << "usage: uzp-export-tests plan <cases.json> | files <templates> <spec.json> <config.json> <out> | "
                 "export <templates> <spec.json> <config.json> | "
                 "export-diagnostic <templates> <spec.json> <config.json> | reencode <list.txt> | roundtrip <out> | "
                 "[--fault <point>[:<n>]] publish <templates> <spec.json> <config.json> "
                 "[--uztexture <relativePath>[:fail|:rgb]] [--presets <dir>] [--dds <requests.json>] "
                 "[--execution-error <reason>] [--publication-checkpoint <call>] | "
                 "[--fault <point>[:<n>]] fixed-copy <exportPath> <dir> | consume-pinned <exportPath> | "
                 "consume-locked <exportPath> <dir> | receipt <project.json> <config.json> [<preset dir>] | hold-lock <exportPath> <ms> | recover --recover <exportPath> [--fixed-names <dir>]... | "
                 "presets <preset dir> <references.json> | aliases\n";
    return 2;
}
