#include "procedural/snapshot_source.h"

#include <array>
#include <map>
#include <utility>

#include "procedural/admission.h"
#include "procedural/asset_library.h"
#include "uzp_core/document/nodes.h"
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

/// Whether `fill` of `set` (node `node`) is inside the recorded capture domain: `SettingsAdmitted`
/// and an existing node (`Settings` otherwise), then the identity UV or Fill projection with
/// BilinearHQ and Repeat (`Projection` otherwise).
Domain DomainOf(const core::Project& project, const core::TextureSet& set, const core::FillContent& fill,
                core::Id node) {
    const auto& uv = fill.projection.uv;
    const auto& transform = uv.uv_transformation;
    if (!SettingsAdmitted(project, set) || core::FindLayer(project, node) == nullptr) return Domain::Settings;
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
    const Domain domain = DomainOf(project, set, fill, node);
    if (mask || !core::ToString(channel).starts_with("User") || format != core::ChannelFormat::L32F ||
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
