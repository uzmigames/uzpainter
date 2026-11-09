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

namespace {

/// The recorded capture domain shared by the split and material snapshot sources.
enum class Domain { Admitted, Settings, Projection };

/// Whether `fill` of `set` (node `node`) is inside the recorded capture domain: the recorded
/// 128px full-UV plane, tile 1001 and Legacy settings (`Settings` otherwise), then the identity UV
/// or Fill projection with BilinearHQ and Repeat (`Projection` otherwise).
Domain DomainOf(const core::Project& project, const core::TextureSet& set, const core::FillContent& fill,
                core::Id node) {
    // This is the recorder's authored full-UV plane, not a geometry-class guess.
    constexpr std::string_view plane = "7d3c5f616c2abf4b06050434fa943d19dcb15ec998245a211d1d4ca7e95197fe";
    const auto& settings = project.settings;
    const auto& colour = settings.color_management;
    const auto& uv = fill.projection.uv;
    const auto& transform = uv.uv_transformation;
    if (set.uv_tiles.size() != 1 || set.uv_tiles.front().udim != 1001 || set.resolution.width != 128 ||
        set.resolution.height != 128 || !project.mesh || project.mesh->resource != plane ||
        core::FindLayer(project, node) == nullptr || settings.workflow != core::ProjectWorkflow::Default ||
        settings.normal_map_format != core::NormalMapFormat::OpenGL ||
        settings.tangent_space != core::TangentSpace::PerVertex || settings.mesh_unit_scale != 1.0 ||
        (!colour.mode.empty() && colour.mode != "legacy") || !colour.config_hash.empty() ||
        !colour.working_space.empty() || !colour.io_rules.empty()) {
        return Domain::Settings;
    }
    if ((fill.projection.mode != core::ProjectionMode::UV && fill.projection.mode != core::ProjectionMode::Fill) ||
        transform.scale_mode != core::ScaleMode::Factors || transform.scale != std::array<double, 2>{1, 1} ||
        transform.rotation != 0 || transform.offset != std::array<double, 2>{0, 0} || fill.symmetry.enabled ||
        uv.filtering_mode != core::FilteringMode::BilinearHQ || uv.uv_wrapping_mode != core::UVWrapMode::Repeat) {
        return Domain::Projection;
    }
    return Domain::Admitted;
}

constexpr std::string_view kProjectionRefusal = "only the recorded identity projection, filter and wrap are admitted";

std::expected<ProceduralRequest, std::string> RequestOf(const core::Project& project, const core::TextureSet& set,
                                                        const core::ProceduralRef& ref, const std::string& output) {
    using Result = std::expected<ProceduralRequest, std::string>;
    const auto context = SnapshotUseContext(project, set, ref, output);
    if (!context) return Result(std::unexpect, context.error());
    const AssetLibrary library;
    auto request = RequestFor(ref, *context, library);
    if (!request) return Result(std::unexpect, request.error().Describe());
    if (request->output.resolution != 128) {
        return Result(std::unexpect, std::string("effective source resolution must equal the 128px target"));
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
        case Domain::Settings: return fail("only material fills on the recorded 128px full-UV plane under Legacy are admitted");
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
        return fail("only User L32F fills on the recorded 128px full-UV plane under Legacy are admitted");
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

}  // namespace uzp::procedural
