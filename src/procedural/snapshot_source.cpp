#include "procedural/snapshot_source.h"

#include <cstring>

#include "evaluator/error.h"
#include "procedural/admission.h"
#include "procedural/snapshot_backend.h"
#include "store/snapshots.h"
#include "uzp_core/document/nodes.h"
#include "uzp_core/manifest/sha256.h"

namespace uzp::procedural {

SnapshotSourceProvider::SnapshotSourceProvider(store::ProjectStore& store, const core::Project& project)
    : store_(store), project_(project) {}

std::expected<std::pair<ProceduralRequest, SnapshotBackend>, std::string> SnapshotSourceProvider::Admitted(
    const core::Project& project, const core::TextureSet& set, core::ChannelType channel,
    core::ChannelFormat format, const core::FillContent& fill, const core::ProceduralRef& ref,
    core::Id node, bool mask) const {
    using Result = std::expected<std::pair<ProceduralRequest, SnapshotBackend>, std::string>;
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
    const auto snapshots = project.extra.find(std::string(store::kSnapshotsKey));
    const auto bound = project_.extra.find(std::string(store::kSnapshotsKey));
    if (snapshots == project.extra.end() || bound == project_.extra.end() || snapshots->second != bound->second) {
        return fail("the provider belongs to another snapshot revision");
    }
    UseContext context;
    context.meshClass = "quad";
    context.output = {128, ChannelFormat::F32, "raw", 1};
    context.outputId = output->second;
    context.settings = EvaluationSettings(project);
    if (const auto seed = ref.params.find("$randomseed"); seed != ref.params.end()) {
        if (!seed->second.IsInt()) return fail("effective random seed is not an integer");
        // Match snapshot capture: signed JSON seeds preserve all uint64 bits.
        context.seed = static_cast<uint64_t>(std::get<int64_t>(seed->second.data));
    }
    context.textureSetResolution = set.resolution;
    context.uvTileResolution = set.resolution;
    const AssetLibrary library;
    auto request = RequestFor(ref, context, library);
    if (!request) return fail(request.error().Describe());
    if (request->output.resolution != 128) return fail("effective source resolution must equal the 128px target");
    auto backend = SnapshotBackend::Load(store_, project);
    if (!backend) return fail(backend.error());
    ProceduralSeam seam(&*backend, nullptr);
    auto admitted = Admit(*request, library, seam);
    if (!admitted) return fail(admitted.error().Describe());
    return std::pair<ProceduralRequest, SnapshotBackend>{std::move(*request), std::move(*backend)};
}

std::expected<std::vector<std::string>, std::string> SnapshotSourceProvider::ImageOutputs(
    const core::Project& project, const core::TextureSet& set, core::ChannelType channel,
    core::ChannelFormat format, const core::FillContent& fill, const core::ProceduralRef& ref,
    core::Id node, bool mask) const {
    using Result = std::expected<std::vector<std::string>, std::string>;
    auto metadata = Metadata(project, set, channel, format, fill, ref, node, mask);
    if (!metadata) return Result(std::unexpect, metadata.error());
    return std::move(metadata->image_outputs);
}

std::expected<store::SourceMetadata, std::string> SnapshotSourceProvider::Metadata(
    const core::Project& project, const core::TextureSet& set, core::ChannelType channel,
    core::ChannelFormat format, const core::FillContent& fill, const core::ProceduralRef& ref,
    core::Id node, bool mask) const {
    using Result = std::expected<store::SourceMetadata, std::string>;
    auto admitted = Admitted(project, set, channel, format, fill, ref, node, mask);
    if (!admitted) return Result(std::unexpect, "procedural snapshot: " + admitted.error());
    auto metadata = admitted->second.Metadata(admitted->first);
    if (!metadata) return Result(std::unexpect, "procedural snapshot: " + metadata.error().Describe());
    return std::move(*metadata);
}

render::Result<std::shared_ptr<const evaluator::ProceduralImage>> SnapshotSourceProvider::Resolve(
    const core::Project& project, const core::TextureSet& set, core::ChannelType channel,
    core::ChannelFormat format, const core::FillContent& fill, const core::ProceduralRef& ref,
    core::Id node, bool mask) const {
    const auto fail = [node](std::string reason) {
        return evaluator::EvalFail(evaluator::EvalErrorKind::UnsupportedSource,
                                   "procedural snapshot: " + reason, node);
    };
    auto admittedSource = Admitted(project, set, channel, format, fill, ref, node, mask);
    if (!admittedSource) return fail(admittedSource.error());
    const ProceduralRequest* request = &admittedSource->first;
    const SnapshotBackend* backend = &admittedSource->second;
    auto stored = backend->Stored(*request);
    if (!stored) return fail(stored.error().Describe());
    auto image = std::make_shared<evaluator::ProceduralImage>();
    image->signature = SignatureHash(*request);
    image->rasterDigest = core::Sha256Hex((*stored)->bytes);
    image->image.width = image->image.height = 128;
    image->image.channels = 1;
    image->image.encoding = render::TexelEncoding::Float32;
    image->image.values.resize(128 * 128);
    std::memcpy(image->image.values.data(), (*stored)->bytes.data(), (*stored)->bytes.size());
    for (const auto& entry : store::ProjectSnapshots(project)) {
        if (entry.key != image->signature || !entry.version) continue;
        image->provenance = {{"signature_sha256", entry.key}, {"project_uuid", entry.project_uuid},
                             {"plane_id", entry.plane_id}, {"version_id", entry.version->version_id},
                             {"chunk_root", entry.version->chunk_root}, {"raster_sha256", image->rasterDigest}};
    }
    if (image->provenance.empty()) return fail("the snapshot has no authoritative plane version");
    return std::shared_ptr<const evaluator::ProceduralImage>(std::move(image));
}

bool SnapshotSourceProvider::Available(const evaluator::ProceduralImage& image) const {
    try {
        for (const auto& entry : store::ProjectSnapshots(project_)) {
            if (entry.key != image.signature || !entry.version ||
                !store::SnapshotProblem(entry, store_.project_uuid()).empty()) continue;
            const core::json::Object identity{{"signature_sha256", entry.key}, {"project_uuid", entry.project_uuid},
                                              {"plane_id", entry.plane_id}, {"version_id", entry.version->version_id},
                                              {"chunk_root", entry.version->chunk_root}, {"raster_sha256", image.rasterDigest}};
            if (identity != image.provenance) return false;
            const auto plane = store_.ReadPlane(project_, entry.plane_id);
            return plane.format == core::ChannelFormat::L32F && plane.width == 128 && plane.height == 128 &&
                   core::Sha256Hex(plane.texels) == image.rasterDigest;
        }
    } catch (const std::exception&) {
        return false;
    }
    return false;
}

}  // namespace uzp::procedural
