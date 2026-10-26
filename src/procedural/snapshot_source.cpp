#include "procedural/snapshot_source.h"

#include <cstring>

#include "evaluator/error.h"
#include "procedural/admission.h"
#include "procedural/snapshot_backend.h"
#include "store/snapshots.h"
#include "uzp_core/document/nodes.h"
#include "uzp_core/manifest/sha256.h"
#include "uzp_core/types/errors.h"
#include "uzp_core/types/resource_url.h"

namespace uzp::procedural {

SnapshotSourceProvider::SnapshotSourceProvider(store::ProjectStore& store, const core::Project& project)
    : store_(store), project_(project) {}

std::expected<std::pair<ProceduralRequest, SnapshotBackend>, std::string> SnapshotSourceProvider::Admitted(
    const core::Project& project, const core::TextureSet& set, core::ChannelType channel,
    core::ChannelFormat format, const core::FillContent& fill, const core::ProceduralRef& ref,
    core::Id node, bool mask, bool* unrecorded) const {
    using Result = std::expected<std::pair<ProceduralRequest, SnapshotBackend>, std::string>;
    const auto fail = [](std::string reason) { return Result(std::unexpect, std::move(reason)); };
    auto request = SnapshotFillRequest(project, set, channel, format, fill, ref, node, mask);
    if (!request) return fail(request.error());
    const auto snapshots = project.extra.find(std::string(store::kSnapshotsKey));
    const auto bound = project_.extra.find(std::string(store::kSnapshotsKey));
    if (snapshots == project.extra.end() || bound == project_.extra.end() || snapshots->second != bound->second) {
        return fail("the provider belongs to another snapshot revision");
    }
    const AssetLibrary library;
    auto backend = SnapshotBackend::Load(store_, project);
    if (!backend) return fail(backend.error());
    // Only this refusal is a legitimate absence (`Observations`): no snapshot holds the signature.
    if (unrecorded != nullptr && !backend->Stored(*request)) *unrecorded = true;
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

std::expected<std::optional<store::SourceMetadata>, std::string> SnapshotSourceProvider::Observations(
    const core::Project& project, const core::TextureSet& set, core::ChannelType channel,
    core::ChannelFormat format, const core::FillContent& fill, const core::ProceduralRef& ref,
    core::Id node, bool mask) const {
    using Result = std::expected<std::optional<store::SourceMetadata>, std::string>;
    try {
        if (core::ParseAssetUrl(ref.asset).family != "snapshot") return std::optional<store::SourceMetadata>();
    } catch (const core::ValueError& error) {
        return Result(std::unexpect, "procedural snapshot: " + std::string(error.what()));
    }
    // A project holding no snapshots at all, on both sides, records no observation; a map present on
    // one side only, unequal maps or malformed entries remain errors (Admitted, Load).
    const std::string key(store::kSnapshotsKey);
    if (!project.extra.contains(key) && !project_.extra.contains(key)) return std::optional<store::SourceMetadata>();
    bool unrecorded = false;
    auto admitted = Admitted(project, set, channel, format, fill, ref, node, mask, &unrecorded);
    if (!admitted) {
        if (unrecorded) return std::optional<store::SourceMetadata>();
        return Result(std::unexpect, "procedural snapshot: " + admitted.error());
    }
    auto metadata = admitted->second.Metadata(admitted->first);
    if (!metadata) {
        if (metadata.error().reason == kNoImageOutputs) return std::optional<store::SourceMetadata>();
        return Result(std::unexpect, "procedural snapshot: " + metadata.error().Describe());
    }
    return std::optional<store::SourceMetadata>(std::move(*metadata));
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
