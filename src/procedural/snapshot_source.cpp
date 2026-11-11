#include "procedural/snapshot_source.h"

#include <bit>
#include <cstring>

#include "evaluator/arith.h"
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
    const uint32_t size = request->output.resolution;
    if ((*stored)->bytes.size() != size_t{size} * size * sizeof(float)) {
        return fail("the stored raster is not the request's " + std::to_string(size) + "px float32 output");
    }
    image->image.width = image->image.height = size;
    image->image.channels = 1;
    image->image.encoding = render::TexelEncoding::Float32;
    image->image.values.resize(size_t{size} * size);
    std::memcpy(image->image.values.data(), (*stored)->bytes.data(), (*stored)->bytes.size());
    if (fill.source_mode == core::SourceMode::Material) {
        // A material fill's Height is the Height bitmap rule on the mapped output's L32F view
        // (P413-A, P413-C): the signed value float32(2 x - 1) (projection_uv.cpp RangeValue), as the
        // Height channel stores it (an L16F channel rounds toward zero to binary16, the tile store's
        // rule). The digest stays the stored bytes'; the DAG hash names the rule.
        const bool half = format == core::ChannelFormat::L16F;
        if (!half && format != core::ChannelFormat::L32F) {
            return fail("a material Height channel of format " + std::string(core::ToString(format)) +
                        " is not recorded (phase3.2_proc-material-families)");
        }
        for (uint32_t& bits : image->image.values) {
            const float twice = 2.0f * std::bit_cast<float>(bits);
            const float value = twice - 1.0f;
            bits = std::bit_cast<uint32_t>(half ? evaluator::arith::HalfToFloat(evaluator::arith::HalfTowardZero(value))
                                                : value);
        }
        if (half) image->image.encoding = render::TexelEncoding::Float16;
        image->materialHeight = true;
    } else if (mask) {
        // Inside a mask Painter reads the source as its 16-bit code (decision 431): the UNORM16
        // write rule of the stored float32 value, which gives back the code of every captured value.
        for (uint32_t& bits : image->image.values) bits = evaluator::arith::WriteUnorm(std::bit_cast<float>(bits), 16);
        image->image.encoding = render::TexelEncoding::Unorm16;
    }
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
            return plane.format == core::ChannelFormat::L32F && static_cast<uint32_t>(plane.width) == image.image.width &&
                   static_cast<uint32_t>(plane.height) == image.image.height && core::Sha256Hex(plane.texels) == image.rasterDigest;
        }
    } catch (const std::exception&) {
        return false;
    }
    return false;
}

}  // namespace uzp::procedural
