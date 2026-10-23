#include "procedural/snapshot_recording.h"

#include "evaluator/arith.h"
#include "export/exr_writer.h"
#include "procedural/snapshot_backend.h"
#include "procedural/admission.h"
#include "store/bundle_codec.h"
#include "uzp_core/types/errors.h"
#include "uzp_core/manifest/sha256.h"

#include <algorithm>
#include <bit>
#include <cmath>
#include <limits>
#include <stdexcept>

namespace uzp::procedural {
namespace {
namespace json = core::json;

const json::Object& Object(const json::Value& value, std::string_view where) {
    if (!value.IsObject()) throw std::invalid_argument(std::string(where) + " must be an object");
    return std::get<json::Object>(value.data);
}

std::string String(const json::Value& value, std::string_view where) {
    if (!value.IsString()) throw std::invalid_argument(std::string(where) + " must be a string");
    return std::get<std::string>(value.data);
}

int64_t Integer(const json::Value& value, std::string_view where) {
    if (!value.IsInt()) throw std::invalid_argument(std::string(where) + " must be an integer");
    return std::get<int64_t>(value.data);
}

void Keys(const json::Object& object, std::initializer_list<std::string_view> names, std::string_view where) {
    if (object.size() != names.size() ||
        !std::all_of(names.begin(), names.end(), [&](std::string_view name) { return object.contains(name); })) {
        throw std::invalid_argument(std::string(where) + " has missing or extra fields");
    }
}

bool Hash(std::string_view value) {
    return value.size() == 64 && std::all_of(value.begin(), value.end(), [](char c) {
        return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f');
    });
}

Params Parameters(const json::Value& value, std::string_view where) {
    Params result;
    for (const auto& [name, item] : Object(value, where)) {
        auto parsed = ParamFromJson(item);
        if (!parsed) throw std::invalid_argument(std::string(where) + "." + name + ": " + parsed.error());
        result.emplace(name, std::move(*parsed));
    }
    return result;
}

RasterSpec Spec(const json::Object& object, bool output = false) {
    const int64_t resolution = Integer(object.at("resolution"), "resolution");
    const int64_t channels = Integer(object.at("channels"), "channels");
    const std::string format = String(object.at("format"), "format");
    RasterSpec spec;
    if (resolution < 1 || resolution > store::kMaxPlaneEdge || channels < 1 || channels > 4 ||
        (output && channels != 1 && channels != 3)) {
        throw std::invalid_argument("invalid snapshot raster dimensions or channel count");
    }
    spec.resolution = static_cast<uint32_t>(resolution);
    spec.channels = static_cast<uint32_t>(channels);
    spec.colourSpace = String(object.at("colour_space"), "colour_space");
    if (spec.colourSpace.empty()) throw std::invalid_argument("colour_space must not be empty");
    bool found = false;
    for (const auto candidate : {ChannelFormat::U8, ChannelFormat::U16, ChannelFormat::F16, ChannelFormat::F32}) {
        if (FormatName(candidate) == format) {
            spec.format = candidate;
            found = true;
        }
    }
    if (!found) throw std::invalid_argument("unknown snapshot raster format: " + format);
    return spec;
}

void LittleEndian(std::string& bytes, uint32_t value, unsigned count) {
    for (unsigned i = 0; i < count; ++i) bytes.push_back(static_cast<char>((value >> (8 * i)) & 255));
}

}  // namespace

std::expected<ProceduralRequest, std::string> RequestFromSignature(const core::json::Value& signature) {
    try {
        const auto& object = Object(signature, "signature");
        Keys(object, {"asset", "version", "params", "preset", "seed", "output", "inputs", "mesh", "settings"},
             "signature");
        ProceduralRequest request;
        const std::string asset = String(object.at("asset"), "asset");
        if (asset.find('@') != std::string::npos) throw std::invalid_argument("asset must not include a version");
        request.asset = core::ParseAssetUrl(asset + "@" +
                                           String(object.at("version"), "version"));
        request.params = Parameters(object.at("params"), "params");
        request.settings = Parameters(object.at("settings"), "settings");
        if (!object.at("preset").IsNull()) request.preset = String(object.at("preset"), "preset");
        // Decision 327 / SignatureJson encode all uint64 seeds as signed two's-complement JSON.
        request.seed = static_cast<uint64_t>(Integer(object.at("seed"), "seed"));
        const auto& output = Object(object.at("output"), "output");
        Keys(output, {"id", "resolution", "format", "colour_space", "channels"}, "output");
        request.output = Spec(output, true);
        request.outputId = String(output.at("id"), "output.id");
        const auto& mesh = Object(object.at("mesh"), "mesh");
        Keys(mesh, {"class", "uv_tiles"}, "mesh");
        request.meshClass = String(mesh.at("class"), "mesh.class");
        const int64_t tiles = Integer(mesh.at("uv_tiles"), "mesh.uv_tiles");
        if (request.meshClass.empty() || tiles < 1 || tiles > std::numeric_limits<uint32_t>::max()) {
            throw std::invalid_argument("mesh needs a nonempty class and a positive uint32 tile count");
        }
        request.uvTiles = static_cast<uint32_t>(tiles);
        for (const auto& [name, value] : Object(object.at("inputs"), "inputs")) {
            const auto& input = Object(value, "input");
            Keys(input, {"sha256", "resolution", "format", "colour_space", "channels"}, "input");
            const std::string hash = String(input.at("sha256"), "input.sha256");
            if (name.empty() || !Hash(hash)) throw std::invalid_argument("input needs a name and lowercase SHA-256");
            request.inputs.emplace(name, ImageInput{Spec(input), hash});
        }
        return request;
    } catch (const std::exception& error) {
        return std::expected<ProceduralRequest, std::string>::unexpected_type(error.what());
    }
}

std::expected<std::string, std::string> SnapshotExportTexels(std::string_view file, const RasterSpec& spec) {
    try {
        const auto format = SnapshotPlaneFormat(spec);
        if (!format) throw std::invalid_argument("snapshot has no matching plane format");
        if (spec.format == ChannelFormat::U8 || spec.format == ChannelFormat::U16) {
            const auto image = store::codec::DecodePng(file, *format);
            if (image.width != static_cast<int>(spec.resolution) || image.height != static_cast<int>(spec.resolution)) {
                throw std::invalid_argument("PNG dimensions differ from the signature");
            }
            return image.texels;
        }
        const auto image = exporter::DecodeExr(file);
        if (image.width != spec.resolution || image.height != spec.resolution || image.channels != spec.channels ||
            image.half != (spec.format == ChannelFormat::F16)) {
            throw std::invalid_argument("EXR dimensions, channels or precision differ from the signature");
        }
        std::string bytes;
        bytes.reserve(image.values.size() * (image.half ? 2 : 4));
        for (const float value : image.values) {
            if (!std::isfinite(value)) throw std::invalid_argument("non-finite export samples are not recordable");
            if (image.half) {
                const uint16_t half = evaluator::arith::HalfNearestEven(value);
                if (std::bit_cast<uint32_t>(evaluator::arith::HalfToFloat(half)) != std::bit_cast<uint32_t>(value)) {
                    throw std::invalid_argument("HALF export did not decode to an exact half value");
                }
                LittleEndian(bytes, half, 2);
            } else {
                LittleEndian(bytes, std::bit_cast<uint32_t>(value), 4);
            }
        }
        return bytes;
    } catch (const std::exception& error) {
        return std::expected<std::string, std::string>::unexpected_type(error.what());
    }
}

std::expected<core::RequestOutcome, std::string> RecordSnapshotExport(
    store::ProjectStore& store, core::Document& document, const ProceduralRequest& request,
    std::string_view exportFile, std::string_view projectUuid, int64_t revision) {
    using Result = std::expected<core::RequestOutcome, std::string>;
    const core::Snapshot snapshot = document.snapshot();
    if (projectUuid != store.project_uuid() || document.project_uuid() != store.project_uuid() ||
        revision != snapshot.revision) {
        return Result(std::unexpect, "snapshot recording belongs to another project or revision");
    }
    if (!document.HasCommitSink(&store)) {
        return Result(std::unexpect, "snapshot recording document is not attached to the destination store");
    }
    try {
        if (revision != store::ReadCurrentRevision(store.container())) {
            return Result(std::unexpect, "snapshot recording document is not at the stored revision");
        }
    } catch (const std::exception& error) {
        return Result(std::unexpect, error.what());
    }
    ProceduralRequest expected = request;
    expected.settings = EvaluationSettings(*snapshot.project);
    if (Signature(expected) != Signature(request)) {
        return Result(std::unexpect, "snapshot settings or mesh fingerprint differ from the destination project");
    }
    const auto texels = SnapshotExportTexels(exportFile, request.output);
    if (!texels) return Result(std::unexpect, texels.error());
    const std::string key = SignatureHash(request);
    const std::string exportHash = core::Sha256Hex(exportFile);
    return store.Submit(
        document,
        core::MutationRequest{"procedural_snapshot",
                              core::json::Object{{"signature_sha256", key}, {"export_sha256", exportHash}},
                              "snapshot-" + key + "-" + exportHash, revision},
        [&](core::Edit& edit) { RecordSnapshot(store, edit, request, *texels); });
}

}  // namespace uzp::procedural
