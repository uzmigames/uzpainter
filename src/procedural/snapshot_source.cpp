#include "procedural/snapshot_source.h"

#include <bit>
#include <cmath>
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

namespace {

/// `image`, a material output's float32 view, as the value `channel` stores (item 2.16; the
/// 2026-11-11 material channel survey, default felt and leather grain fills alone over the empty
/// stack of the plane at 128 px, where each rule misses no texel), or why it is not recorded:
/// - BaseMetalness, SpecularRoughness (L8): ((x16 >> 4) 255 + 2047) >> 12 of the 16-bit code
///   x16 = round(65535 x) of the scalar view x, recorded on views within 1 / 64 of a code only (for
///   x exactly float32(x16 / 65535) it is the tile store's L8 write rule `WriteUnorm(x, 8)`). The
///   image holds the 8-bit codes.
/// - BaseColor (sRGB8): the code round(255 v) of each component v of the RGB view, with no transfer,
///   recorded on binary16 views in [0, 1] only. The image holds the 8-bit codes.
/// - Normal (RGB16F): (tz16 r, tz16(1 - g), tz16 b) of the RGB view (r, g, b), float32 subtraction,
///   tz16 binary16 rounding toward zero. The image holds the float32 values of the halves.
std::expected<std::string, std::string> MaterialChannelRule(core::ChannelType channel, evaluator::DecodedImage& image) {
    using Result = std::expected<std::string, std::string>;
    namespace arith = evaluator::arith;
    const std::string owner = " (" + std::string(kMaterialChannelOwner) + ")";
    if (channel == core::ChannelType::BaseMetalness || channel == core::ChannelType::SpecularRoughness) {
        for (uint32_t& bits : image.values) {
            const float x = std::bit_cast<float>(bits);
            const double scaled = static_cast<double>(x) * 65535.0;
            const double code = std::nearbyint(scaled);
            // The 16-bit code x16 the view stands for. Painter's views are within 0.003 of a code
            // (felt exactly k / 65535, leather grain up to 252 float32 ulps from it, the
            // 2026-11-11 captures); anything farther than 1 / 64 of a code is not recorded.
            if (!(code >= 0.0 && code <= 65535.0) || std::fabs(scaled - code) > 1.0 / 64.0) {
                return Result(std::unexpect, "a material L8 channel is recorded from 16-bit views only" + owner);
            }
            const auto x16 = static_cast<uint32_t>(code);
            bits = ((x16 >> 4) * 255u + 2047u) >> 12;
        }
        image.encoding = render::TexelEncoding::Unorm8;
        return "l8";
    }
    if (channel == core::ChannelType::BaseColor) {
        for (uint32_t& bits : image.values) {
            const float v = std::bit_cast<float>(bits);
            if (!(v >= 0.0f && v <= 1.0f) || arith::HalfToFloat(arith::HalfNearestEven(v)) != v) {
                return Result(std::unexpect, "a material sRGB8 BaseColor is recorded from binary16 views in [0, 1] only" + owner);
            }
            bits = static_cast<uint32_t>(std::floor(255.0 * static_cast<double>(v) + 0.5));
        }
        image.encoding = render::TexelEncoding::Unorm8;
        return "srgb8";
    }
    if (channel == core::ChannelType::Normal) {
        for (size_t i = 0; i < image.values.size(); ++i) {
            float v = std::bit_cast<float>(image.values[i]);
            if (!std::isfinite(v)) return Result(std::unexpect, "a material Normal view holds a non-finite value" + owner);
            if (i % 3 == 1) v = 1.0f - v;
            image.values[i] = std::bit_cast<uint32_t>(arith::HalfToFloat(arith::HalfTowardZero(v)));
        }
        image.encoding = render::TexelEncoding::Float16;
        return "normal";
    }
    return Result(std::unexpect, "a material fill's " + std::string(core::ToString(channel)) + " channel is not recorded" + owner);
}

}  // namespace

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
    const uint32_t channels = request->output.channels;
    if ((*stored)->bytes.size() != size_t{size} * size * channels * sizeof(float)) {
        return fail("the stored raster is not the request's " + std::to_string(size) + "px float32 output");
    }
    image->image.width = image->image.height = size;
    image->image.channels = channels;
    image->image.encoding = render::TexelEncoding::Float32;
    image->image.values.resize(size_t{size} * size * channels);
    std::memcpy(image->image.values.data(), (*stored)->bytes.data(), (*stored)->bytes.size());
    if (fill.source_mode == core::SourceMode::Material && channel != core::ChannelType::Height) {
        // A material fill's other channels (item 2.16, the 2026-11-11 material channel survey, one
        // default material fill over the empty stack): the provider gives the value the channel
        // stores, so the fill's Normal blend at opacity 1 writes it unchanged.
        auto rule = MaterialChannelRule(channel, image->image);
        if (!rule) return fail(rule.error());
        image->materialRule = *rule;
    } else if (fill.source_mode == core::SourceMode::Material) {
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
        image->materialRule = "height";
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
            // A snapshot's plane holds its output view: L32F, or RGB32F for a material's RGB view.
            const core::ChannelFormat format =
                image.image.channels == 3 ? core::ChannelFormat::RGB32F : core::ChannelFormat::L32F;
            return plane.format == format && static_cast<uint32_t>(plane.width) == image.image.width &&
                   static_cast<uint32_t>(plane.height) == image.image.height && core::Sha256Hex(plane.texels) == image.rasterDigest;
        }
    } catch (const std::exception&) {
        return false;
    }
    return false;
}

}  // namespace uzp::procedural
