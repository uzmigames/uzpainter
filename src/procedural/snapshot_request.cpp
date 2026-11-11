#include "procedural/snapshot_source.h"

#include <algorithm>
#include <array>
#include <map>
#include <utility>

#include "procedural/admission.h"
#include "procedural/asset_library.h"
#include "uzp_core/document/nodes.h"
#include "uzp_core/types/errors.h"
#include "uzp_core/types/resource_url.h"

// The pure part of the snapshot fill source (snapshot_source.h): the use context and the request a
// fill asks for, from the project alone. No store or evaluator call, so the procedural targets
// that do not link the evaluator (the V2 Filter observation lookup) share it.

namespace uzp::procedural {

std::expected<UseContext, std::string> SnapshotUseContext(const core::Project& project, const core::TextureSet& set,
                                                         const core::ProceduralRef& ref, const std::string& outputId) {
    using Result = std::expected<UseContext, std::string>;
    if (set.resolution.width != set.resolution.height || set.uv_tiles.empty()) {
        return Result(std::unexpect, "a snapshot fill source needs a square texture set with UV tiles");
    }
    UseContext context;
    context.meshClass = "quad";
    context.uvTiles = static_cast<uint32_t>(set.uv_tiles.size());
    context.output = {static_cast<uint32_t>(set.resolution.width), ChannelFormat::F32, "raw", 1};
    context.outputId = outputId;
    context.settings = EvaluationSettings(project);
    if (const auto seed = ref.params.find("$randomseed"); seed != ref.params.end()) {
        if (!seed->second.IsInt()) return Result(std::unexpect, "effective random seed is not an integer");
        // Match snapshot capture: signed JSON seeds preserve all uint64 bits.
        context.seed = static_cast<uint64_t>(std::get<int64_t>(seed->second.data));
    }
    context.textureSetResolution = set.resolution;
    context.uvTileResolution = set.resolution;
    return context;
}

namespace {

/// The recorded capture domain shared by the split and material snapshot sources.
enum class Domain { Admitted, Settings, Projection };

/// Whether the project and texture set lie inside the recorded capture domain (decision 428): one
/// square texture set of one UV tile 1001 at a power-of-two resolution from 128 to 4096 on an
/// imported mesh, under the default workflow, Legacy colour management, OpenGL normals, PerVertex
/// tangents and mesh scale 1. The mesh itself is not checked here: its identity (the mesh and
/// import report hashes of `EvaluationSettings`) is a signature field, so another mesh is refused
/// by the signature, naming that field.
bool SettingsAdmitted(const core::Project& project, const core::TextureSet& set) {
    const auto& settings = project.settings;
    const auto& colour = settings.color_management;
    const int size = set.resolution.width;
    return set.uv_tiles.size() == 1 && set.uv_tiles.front().udim == 1001 && size == set.resolution.height &&
           size >= 128 && size <= 4096 && (size & (size - 1)) == 0 && project.mesh &&
           settings.workflow == core::ProjectWorkflow::Default &&
           settings.normal_map_format == core::NormalMapFormat::OpenGL &&
           settings.tangent_space == core::TangentSpace::PerVertex && settings.mesh_unit_scale == 1.0 &&
           (colour.mode.empty() || colour.mode == "legacy") && colour.config_hash.empty() &&
           colour.working_space.empty() && colour.io_rules.empty();
}

/// Whether `node` is a fill effect of a layer's mask stack.
bool MaskFillEffect(const core::Project& project, core::Id node) {
    bool found = false;
    core::ForEachNode(project, [&](const core::NodeVisit& visit) {
        if (visit.effect != nullptr && visit.effect->uid == node && visit.owner_stack == core::NodeStack::Mask &&
            visit.effect->kind == core::EffectKind::fill) {
            found = true;
        }
    });
    return found;
}

/// Whether `fill` of `set` (node `node`) is inside the recorded capture domain: `SettingsAdmitted`
/// and an existing layer, or with `maskEffect` a fill effect of a mask stack (`Settings`
/// otherwise), then the identity UV or Fill projection with BilinearHQ and Repeat (`Projection`
/// otherwise).
Domain DomainOf(const core::Project& project, const core::TextureSet& set, const core::FillContent& fill,
                core::Id node, bool maskEffect = false) {
    const auto& uv = fill.projection.uv;
    const auto& transform = uv.uv_transformation;
    const bool exists = maskEffect ? MaskFillEffect(project, node) : core::FindLayer(project, node) != nullptr;
    if (!SettingsAdmitted(project, set) || !exists) return Domain::Settings;
    if ((fill.projection.mode != core::ProjectionMode::UV && fill.projection.mode != core::ProjectionMode::Fill) ||
        transform.scale_mode != core::ScaleMode::Factors || transform.scale != std::array<double, 2>{1, 1} ||
        transform.rotation != 0 || transform.offset != std::array<double, 2>{0, 0} || fill.symmetry.enabled ||
        uv.filtering_mode != core::FilteringMode::BilinearHQ || uv.uv_wrapping_mode != core::UVWrapMode::Repeat) {
        return Domain::Projection;
    }
    return Domain::Admitted;
}

constexpr std::string_view kProjectionRefusal = "only the recorded identity projection, filter and wrap are admitted";
constexpr std::string_view kSettingsRefusal =
    "only one texture set of one UV tile 1001, square at 128 to 4096 px, on an imported mesh under Legacy, "
    "OpenGL, PerVertex, the default workflow and mesh scale 1 is admitted";

std::expected<ProceduralRequest, std::string> RequestOf(const core::Project& project, const core::TextureSet& set,
                                                        const core::ProceduralRef& ref, const std::string& output) {
    using Result = std::expected<ProceduralRequest, std::string>;
    const auto context = SnapshotUseContext(project, set, ref, output);
    if (!context) return Result(std::unexpect, context.error());
    const AssetLibrary library;
    auto request = RequestFor(ref, *context, library);
    if (!request) return Result(std::unexpect, request.error().Describe());
    if (request->output.resolution != static_cast<uint32_t>(set.resolution.width)) {
        return Result(std::unexpect, std::string("effective source resolution must equal the texture set's resolution"));
    }
    return std::move(*request);
}

/// The snapshot asset ids (`uzasset://snapshot/<SHA-256 of the resource URL>`) a mask fill effect
/// may read: Painter 12.2.0's fixed grunge textures `grunge_rock` and `grunge_dirt_large`
/// (decision 427 §1), which follow no seed and whose every recording in a mask equals its capture
/// (decision 431). A seeded grunge differs from its capture on a few texels in other Painter
/// instances of it, the capturing session included, so it stays refused.
constexpr std::array<std::string_view, 2> kMaskSnapshotAssets{
    // resource://starter_assets/grunge_rock/grunge_rock?version=5d95a51fa6ba5ebce1af058642b8bac869b72a70.sbsar
    "801dc06d7db24281d9e5b86df33f252752a81a759fe5d4f2894af489cd468ac0",
    // resource://starter_assets/grunge_dirt_large/grunge_dirt_large?version=a3422c5859b29fa52c778829320ec8aa6a39f724.sbsar
    "c59f8fc2041f50089195d595dd0fa2718e9fbdd13acb2c930ce928f2db231a5e",
};

constexpr std::string_view kMaskAssetRefusal =
    "a mask reads only the fixed grunges grunge/rock and grunge/dirt-large as snapshots; a seeded snapshot "
    "differs from its capture in other Painter instances (phase3.3_procedural-families item 2.15, decision 431)";

/// The request a mask fill effect's procedural source asks for (decision 431): a fill effect of a
/// mask stack in the capture domain and identity projection, a snapshot of `kMaskSnapshotAssets`,
/// no preset, image input or plugged source, and its output named by `mask_output` (a mask-stack
/// procedural maps no channel).
std::expected<ProceduralRequest, std::string> SnapshotMaskRequest(const core::Project& project, const core::TextureSet& set,
                                                                  const core::FillContent& fill,
                                                                  const core::ProceduralRef& ref, core::Id node) {
    using Result = std::expected<ProceduralRequest, std::string>;
    const auto fail = [](std::string_view reason) { return Result(std::unexpect, std::string(reason)); };
    switch (DomainOf(project, set, fill, node, true)) {
        case Domain::Settings: return fail(kSettingsRefusal);
        case Domain::Projection: return fail(kProjectionRefusal);
        case Domain::Admitted: break;
    }
    core::AssetUrl asset;
    try {
        asset = core::ParseAssetUrl(ref.asset);
    } catch (const core::ValueError&) {
        return fail(kMaskAssetRefusal);
    }
    if (asset.family != "snapshot" ||
        std::find(kMaskSnapshotAssets.begin(), kMaskSnapshotAssets.end(), asset.id) == kMaskSnapshotAssets.end()) {
        return fail(kMaskAssetRefusal);
    }
    if (ref.preset || !ref.image_inputs.empty() || !ref.input_sources.empty()) {
        return fail("a mask snapshot source takes no preset, image input or plugged source");
    }
    if (!ref.output_mapping.empty() || !ref.mask_output || ref.mask_output->empty()) {
        return fail("a mask snapshot source names its output by mask_output only");
    }
    return RequestOf(project, set, ref, *ref.mask_output);
}

}  // namespace

std::expected<ProceduralRequest, std::string> SnapshotMaterialRequest(const core::Project& project,
                                                                      const core::TextureSet& set,
                                                                      const core::FillContent& fill,
                                                                      const core::ProceduralRef& ref, core::Id node) {
    using Result = std::expected<ProceduralRequest, std::string>;
    const auto fail = [](std::string_view reason) { return Result(std::unexpect, std::string(reason)); };
    if (fill.source_mode != core::SourceMode::Material) return fail("the fill is not in Material source mode");
    switch (DomainOf(project, set, fill, node)) {
        case Domain::Settings: return fail(kSettingsRefusal);
        case Domain::Projection: return fail(kProjectionRefusal);
        case Domain::Admitted: break;
    }
    if (!fill.active_channels.contains(core::ChannelType::Height)) {
        return fail("a material fill is evaluated through its recorded Height channel only");
    }
    const auto height = ref.output_mapping.find("Height");
    if (height == ref.output_mapping.end() || height->second.empty()) {
        return fail("a material fill without an output mapped to Height is not recorded");
    }
    if (!ref.image_inputs.empty()) return fail("a material fill takes no raster image inputs");
    // P413-C: a mask output equal to Height's output leaves Height unchanged in every recording;
    // another one is exact in the same session only (its save/reopen value differs).
    if (ref.mask_output && *ref.mask_output != height->second) return fail(kMaterialMaskRefusal);
    return RequestOf(project, set, ref, height->second);
}

std::expected<ProceduralRequest, std::string> SnapshotFillRequest(
    const core::Project& project, const core::TextureSet& set, core::ChannelType channel, core::ChannelFormat format,
    const core::FillContent& fill, const core::ProceduralRef& ref, core::Id node, bool mask) {
    using Result = std::expected<ProceduralRequest, std::string>;
    const auto fail = [](std::string_view reason) { return Result(std::unexpect, std::string(reason)); };
    if (fill.source_mode == core::SourceMode::Material) {
        if (mask || channel != core::ChannelType::Height) {
            return fail("a material fill is evaluated through its recorded Height channel only");
        }
        return SnapshotMaterialRequest(project, set, fill, ref, node);
    }
    if (mask) return SnapshotMaskRequest(project, set, fill, ref, node);
    const Domain domain = DomainOf(project, set, fill, node);
    if (!core::ToString(channel).starts_with("User") || format != core::ChannelFormat::L32F ||
        domain == Domain::Settings) {
        return fail(std::string("only User L32F fills; ") + std::string(kSettingsRefusal));
    }
    if (domain == Domain::Projection) return fail(kProjectionRefusal);
    const auto output = ref.output_mapping.find(std::string(core::ToString(channel)));
    // A preset and plugged input sources join the signature (decision 413: the multi-output capture
    // records each state through these very User L32F split sources); raster inputs and a mask
    // output stay outside the split domain.
    if (output == ref.output_mapping.end() || output->second.empty() || !ref.image_inputs.empty() ||
        ref.mask_output || ref.output_mapping.size() != 1) {
        return fail("an explicit scalar output mapping and effective parameters are required; no implicit output selection");
    }
    return RequestOf(project, set, ref, output->second);
}

std::expected<ProceduralRequest, std::string> SnapshotSetRequest(const core::Project& project, const core::TextureSet& set,
                                                                 const core::ProceduralRef& ref, const std::string& outputId) {
    if (!SettingsAdmitted(project, set)) return std::expected<ProceduralRequest, std::string>(std::unexpect, std::string(kSettingsRefusal));
    return RequestOf(project, set, ref, outputId);
}

namespace {

/// The sample type and channel count of a mesh-map binding's stored format, as `MeshMapSpec`
/// (generators.h) gives them: `L8`, `RGB8` and `sRGB8` as u8, `L16` and `RGB16` as u16, `L16F` and
/// `RGB16F` as f16, `L32F` and `RGB32F` as f32.
std::pair<ChannelFormat, uint32_t> MeshMapFormat(core::ChannelFormat format) {
    switch (format) {
        case core::ChannelFormat::L8: return {ChannelFormat::U8, 1};
        case core::ChannelFormat::sRGB8:
        case core::ChannelFormat::RGB8: return {ChannelFormat::U8, 3};
        case core::ChannelFormat::L16: return {ChannelFormat::U16, 1};
        case core::ChannelFormat::RGB16: return {ChannelFormat::U16, 3};
        case core::ChannelFormat::L16F: return {ChannelFormat::F16, 1};
        case core::ChannelFormat::RGB16F: return {ChannelFormat::F16, 3};
        case core::ChannelFormat::L32F: return {ChannelFormat::F32, 1};
        case core::ChannelFormat::RGB32F: return {ChannelFormat::F32, 3};
    }
    return {ChannelFormat::F32, 0};
}

}  // namespace

std::expected<std::map<std::string, ImageInput>, std::string> SnapshotMeshMapInputs(const core::TextureSet& set) {
    using Result = std::expected<std::map<std::string, ImageInput>, std::string>;
    std::map<std::string, ImageInput> inputs;
    for (const auto& [usage, binding] : set.mesh_maps) {
        const std::string name(core::ToString(usage));
        if (binding.invalid) return Result(std::unexpect, "the " + name + " mesh map of texture set " + set.name + " is invalid");
        const auto [format, channels] = MeshMapFormat(binding.format);
        inputs[name] = ImageInput{RasterSpec{static_cast<uint32_t>(set.resolution.width), format, binding.color_space, channels},
                                  binding.resource};
    }
    return inputs;
}

std::expected<ProceduralRequest, std::string> SnapshotGeneratorRequest(const core::Project& project, const core::TextureSet& set,
                                                                       const core::ProceduralRef& ref, const std::string& outputId) {
    using Result = std::expected<ProceduralRequest, std::string>;
    if (!ref.image_inputs.empty() || !ref.input_sources.empty()) {
        return Result(std::unexpect, std::string("a generator reads its mesh maps from the texture set, not from image inputs"));
    }
    auto request = SnapshotSetRequest(project, set, ref, outputId);
    if (!request) return request;
    auto inputs = SnapshotMeshMapInputs(set);
    if (!inputs) return Result(std::unexpect, inputs.error());
    request->inputs = std::move(*inputs);
    return request;
}

}  // namespace uzp::procedural
