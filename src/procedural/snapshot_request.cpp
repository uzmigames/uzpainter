#include "procedural/snapshot_source.h"

#include <array>

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

std::expected<ProceduralRequest, std::string> SnapshotFillRequest(
    const core::Project& project, const core::TextureSet& set, core::ChannelType channel, core::ChannelFormat format,
    const core::FillContent& fill, const core::ProceduralRef& ref, core::Id node, bool mask) {
    using Result = std::expected<ProceduralRequest, std::string>;
    const auto fail = [](std::string reason) { return Result(std::unexpect, std::move(reason)); };
    // This is the recorder's authored full-UV plane, not a geometry-class guess.
    constexpr std::string_view plane = "7d3c5f616c2abf4b06050434fa943d19dcb15ec998245a211d1d4ca7e95197fe";
    const auto& settings = project.settings;
    const auto& colour = settings.color_management;
    const auto& uv = fill.projection.uv;
    const auto& transform = uv.uv_transformation;
    if (mask || !core::ToString(channel).starts_with("User") || format != core::ChannelFormat::L32F ||
        set.uv_tiles.size() != 1 || set.uv_tiles.front().udim != 1001 ||
        set.resolution.width != 128 || set.resolution.height != 128 || !project.mesh ||
        project.mesh->resource != plane || core::FindLayer(project, node) == nullptr ||
        settings.workflow != core::ProjectWorkflow::Default ||
        settings.normal_map_format != core::NormalMapFormat::OpenGL ||
        settings.tangent_space != core::TangentSpace::PerVertex || settings.mesh_unit_scale != 1.0 ||
        (!colour.mode.empty() && colour.mode != "legacy") || !colour.config_hash.empty() ||
        !colour.working_space.empty() || !colour.io_rules.empty()) {
        return fail("only User L32F fills on the recorded 128px full-UV plane under Legacy are admitted");
    }
    if ((fill.projection.mode != core::ProjectionMode::UV && fill.projection.mode != core::ProjectionMode::Fill) ||
        transform.scale_mode != core::ScaleMode::Factors || transform.scale != std::array<double, 2>{1, 1} ||
        transform.rotation != 0 || transform.offset != std::array<double, 2>{0, 0} || fill.symmetry.enabled ||
        uv.filtering_mode != core::FilteringMode::BilinearHQ || uv.uv_wrapping_mode != core::UVWrapMode::Repeat) {
        return fail("only the recorded identity projection, filter and wrap are admitted");
    }
    const auto output = ref.output_mapping.find(std::string(core::ToString(channel)));
    if (output == ref.output_mapping.end() || output->second.empty() || ref.preset || !ref.image_inputs.empty() ||
        ref.mask_output || ref.output_mapping.size() != 1) {
        return fail("an explicit scalar output mapping and effective parameters are required; no implicit output selection");
    }
    const auto context = SnapshotUseContext(project, set, ref, output->second);
    if (!context) return fail(context.error());
    const AssetLibrary library;
    auto request = RequestFor(ref, *context, library);
    if (!request) return fail(request.error().Describe());
    if (request->output.resolution != 128) return fail("effective source resolution must equal the 128px target");
    return std::move(*request);
}

}  // namespace uzp::procedural
