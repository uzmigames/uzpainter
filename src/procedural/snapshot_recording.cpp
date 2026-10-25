#include "procedural/snapshot_recording.h"

#include "evaluator/arith.h"
#include "export/exr_writer.h"
#include "procedural/snapshot_backend.h"
#include "procedural/admission.h"
#include "store/bundle_codec.h"
#include "store/snapshots.h"
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
    std::string_view exportFile, std::string_view projectUuid, int64_t revision,
    const std::optional<store::SourceMetadata>& observed) {
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
    core::json::Object args{{"signature_sha256", key}, {"export_sha256", exportHash}};
    std::string operation = "snapshot-" + key + "-" + exportHash;
    if (observed) {
        const json::Value signature = SignatureJson(request);
        const json::Value metadata = store::SourceMetadataJson(signature, *observed);
        const std::string problem = store::SourceMetadataProblem(signature, metadata);
        if (!problem.empty()) return Result(std::unexpect, problem);
        const std::string metadataHash = core::Sha256Hex(json::WriteCanonical(metadata));
        args["source_metadata_sha256"] = metadataHash;
        operation += "-" + metadataHash;
    }
    return store.Submit(document, core::MutationRequest{"procedural_snapshot", std::move(args), operation, revision},
                        [&](core::Edit& edit) { RecordSnapshot(store, edit, request, *texels, observed); });
}

std::expected<std::vector<std::string>, std::string> ReceiptImageOutputs(
    const core::json::Value& receipt, std::string_view resource, const ProceduralRequest& request) {
    using Result = std::expected<std::vector<std::string>, std::string>;
    try {
        const auto& readback = Object(Object(receipt, "receipt").at("readback"), "readback");
        const auto sources = readback.find("sources");
        const auto* list = sources == readback.end() ? nullptr : std::get_if<json::Array>(&sources->second.data);
        if (list == nullptr || list->size() != 2) {
            throw std::invalid_argument("readback.sources must hold exactly the two paired sources");
        }
        std::optional<std::vector<std::string>> observed;
        for (const json::Value& item : *list) {
            const auto& source = Object(item, "readback source");
            if (String(source.at("resource"), "source resource") != resource) {
                throw std::invalid_argument("a paired source names another resource");
            }
            const auto* outputs = std::get_if<json::Array>(&source.at("outputs").data);
            if (outputs == nullptr) throw std::invalid_argument("source outputs must be an array");
            std::vector<std::string> names;
            for (const json::Value& output : *outputs) names.push_back(String(output, "source output"));
            if (observed && *observed != names) throw std::invalid_argument("paired sources observed different outputs");
            // The capture domain is a singleton output source (bridge.validate_readback); the
            // stored metadata may hold more outputs, but a capture never widens its domain.
            if (String(source.at("active_output"), "source active_output") != request.outputId ||
                names != std::vector<std::string>{request.outputId}) {
                throw std::invalid_argument("a paired source is not the singleton output " + request.outputId +
                                            " the capture signature names");
            }
            observed = std::move(names);
        }
        const json::Value signature = SignatureJson(request);
        const std::string problem = store::SourceMetadataProblem(signature, store::SourceMetadataJson(signature, *observed));
        if (!problem.empty()) throw std::invalid_argument(problem);
        return *observed;
    } catch (const std::out_of_range&) {
        return Result(std::unexpect, "readback source lacks resource, outputs or active_output");
    } catch (const std::exception& error) {
        return Result(std::unexpect, error.what());
    }
}

std::expected<store::SourceMetadata, std::string> ReceiptSourceMetadata(
    const core::json::Value& receipt, std::string_view resource, const ProceduralRequest& request) {
    using Result = std::expected<store::SourceMetadata, std::string>;
    auto outputs = ReceiptImageOutputs(receipt, resource, request);
    if (!outputs) return Result(std::unexpect, outputs.error());
    try {
        const auto& sources = std::get<json::Array>(Object(Object(receipt, "receipt").at("readback"), "readback")
                                                        .at("sources")
                                                        .data);
        // Canonical JSON keeps what Value equality does not: the sign of zero and int versus double,
        // as SignatureJson does.
        if (json::WriteCanonical(sources[0]) != json::WriteCanonical(sources[1])) {
            throw std::invalid_argument("the paired sources' readbacks differ");
        }
        const auto& source = Object(sources[0], "readback source");
        // The recorded parameters are the request's effective parameters as the signature encodes
        // them (ParamJson: numbers by value, so 15.0 and 15, or -0.0 and 0.0, are one identity; a
        // string never equals a number). Comparing raw readback JSON would refuse real captures.
        const json::Object& recorded = Object(source.at("parameters"), "source parameters");
        if (recorded.size() != request.params.size()) {
            throw std::invalid_argument("the paired sources' parameters differ from the capture signature");
        }
        for (const auto& [name, value] : recorded) {
            const auto expected = request.params.find(name);
            const auto parsed = ParamFromJson(value);
            if (expected == request.params.end() || !parsed ||
                json::WriteCanonical(ParamJson(*parsed)) != json::WriteCanonical(ParamJson(expected->second))) {
                throw std::invalid_argument("the paired sources' parameter " + name + " differs from the capture signature");
            }
        }
        store::SourceMetadata metadata{std::move(*outputs), std::nullopt, std::nullopt, std::nullopt, std::nullopt, std::nullopt};
        const auto names = [&](std::string_view key) {
            std::vector<std::string> list;
            for (const json::Value& item : std::get<json::Array>(source.at(std::string(key)).data)) {
                list.push_back(String(item, "source " + std::string(key)));
            }
            return list;
        };
        if (!source.at("inputs").IsArray()) throw std::invalid_argument("source inputs must be an array");
        metadata.image_inputs = names("inputs");
        if (const auto presets = source.find("presets"); presets != source.end()) {
            if (!presets->second.IsArray()) throw std::invalid_argument("source presets must be an array");
            metadata.presets = names("presets");
        }
        if (const auto properties = source.find("properties"); properties != source.end()) {
            if (!properties->second.IsObject()) throw std::invalid_argument("source properties must be an object");
            metadata.properties = std::get<json::Object>(properties->second.data);
        }
        // Decision 361: the raw parameter map as get_parameters returned it, JSON types kept (the
        // paired sources are canonically identical above). A value outside the typed domain refuses
        // the capture rather than losing its type.
        for (const auto& [name, value] : recorded) {
            if (!store::ParamByValue(value)) {
                throw std::invalid_argument("the paired sources' parameter " + name +
                                            " is not an int64, finite double or string");
            }
        }
        metadata.typed_effective_parameters = recorded;
        // The ResourceID parts, only when the bridge observed them through the documented getters.
        if (const auto id = source.find("resource_id"); id != source.end()) {
            const auto& parts = Object(id->second, "source resource_id");
            if (parts.size() != 4) throw std::invalid_argument("source resource_id must hold exactly url, context, name and version");
            store::ObservedResourceId observed{String(parts.at("url"), "resource_id url"),
                                               String(parts.at("context"), "resource_id context"),
                                               String(parts.at("name"), "resource_id name"),
                                               String(parts.at("version"), "resource_id version")};
            if (observed.url != resource || observed.url != String(source.at("resource"), "source resource")) {
                throw std::invalid_argument("source resource_id url is not the requested resource");
            }
            metadata.observed_resource_id = std::move(observed);
        }
        const json::Value signature = SignatureJson(request);
        const std::string problem = store::SourceMetadataProblem(signature, store::SourceMetadataJson(signature, metadata));
        if (!problem.empty()) throw std::invalid_argument(problem);
        return metadata;
    } catch (const std::out_of_range&) {
        return Result(std::unexpect, "readback source lacks parameters or inputs");
    } catch (const std::exception& error) {
        return Result(std::unexpect, error.what());
    }
}

}  // namespace uzp::procedural
