#include "procedural/filter_observation_import_v2.h"

#include <algorithm>
#include <bit>
#include <cmath>
#include <cstring>
#include <initializer_list>
#include <set>
#include <stdexcept>
#include <utility>
#include <variant>

#include "procedural/filter_observation_source.h"
#include "procedural/frozen_host_proof.h"
#include "procedural/seam.h"
#include "procedural/snapshot_recording.h"
#include "procedural/snapshot_source.h"
#include "store/filter_observations.h"
#include "store/observation_inventory.h"
#include "store/snapshots.h"
#include "uzp_core/manifest/manifest.h"
#include "uzp_core/manifest/sha256.h"

namespace uzp::procedural {
namespace {

using core::json::Array;
using core::json::Object;
using core::json::Value;

/// A refusal raised inside a step.
struct ImportRefused {
    ImportRefusal refusal;
};

[[noreturn]] void RefuseImport(std::string_view reason, const std::string& detail) {
    throw ImportRefused{ImportRefusal{std::string(reason), detail}};
}

void Require(bool condition, std::string_view reason, const std::string& detail) {
    if (!condition) RefuseImport(reason, detail);
}

const Object& ClosedObject(const Value& value, std::string_view reason, const std::string& path,
                           std::initializer_list<std::string_view> members) {
    const auto* object = std::get_if<Object>(&value.data);
    Require(object != nullptr && object->size() == members.size(), reason, path + ": expected exactly its members");
    for (const std::string_view name : members) {
        Require(object->contains(name), reason, path + ": missing member '" + std::string(name) + "'");
    }
    return *object;
}

const Value& At(const Object& object, std::string_view name) { return object.find(name)->second; }

const std::string& StringAt(const Object& object, std::string_view name, std::string_view reason, const std::string& path) {
    const auto* text = std::get_if<std::string>(&At(object, name).data);
    Require(text != nullptr, reason, path + "." + std::string(name) + ": expected a string");
    return *text;
}

const Array& ArrayAt(const Object& object, std::string_view name, std::string_view reason, const std::string& path) {
    const auto* array = std::get_if<Array>(&At(object, name).data);
    Require(array != nullptr, reason, path + "." + std::string(name) + ": expected an array");
    return *array;
}

bool SameTyped(const Value& a, const Value& b) { return core::json::WriteCanonical(a) == core::json::WriteCanonical(b); }

/// A JSON number equal by value to `expected` (the bridge compares Python numbers by value).
bool NumberIs(const Value& value, double expected) {
    if (const auto* integer = std::get_if<std::int64_t>(&value.data)) return static_cast<double>(*integer) == expected;
    if (const auto* real = std::get_if<double>(&value.data)) return *real == expected;
    return false;
}

bool NumbersAre(const Value& value, std::initializer_list<double> expected) {
    const auto* array = std::get_if<Array>(&value.data);
    if (array == nullptr || array->size() != expected.size()) return false;
    std::size_t i = 0;
    for (const double item : expected) {
        if (!NumberIs((*array)[i++], item)) return false;
    }
    return true;
}

Value Parse(const std::string& bytes, std::string_view reason, const std::string& what) {
    try {
        return core::json::Parse(bytes);
    } catch (const std::exception& error) {
        RefuseImport(reason, what + " is not JSON: " + error.what());
    }
}

/// The bytes of an artifact reference `{kind, sha256, size_bytes}` of `kind`, resolved through the
/// transport and verified by hash and size.
std::string Resolve(const Value& reference, std::string_view kind, const ArtifactBytes& artifacts, const std::string& path) {
    const Object& ref = ClosedObject(reference, kHostCaptureInvalid, path, {"kind", "sha256", "size_bytes"});
    Require(StringAt(ref, "kind", kHostCaptureInvalid, path) == kind, kHostCaptureInvalid, path + ": expected kind " + std::string(kind));
    const std::string& sha = StringAt(ref, "sha256", kHostCaptureInvalid, path);
    const auto* size = std::get_if<std::int64_t>(&At(ref, "size_bytes").data);
    Require(size != nullptr && *size >= 0, kHostCaptureInvalid, path + ".size_bytes: expected a nonnegative integer");
    const std::optional<std::string> bytes = artifacts ? artifacts(sha) : std::nullopt;
    Require(bytes.has_value(), kHostCaptureInvalid, path + ": the artifact transport does not hold " + sha);
    Require(core::Sha256Hex(*bytes) == sha && static_cast<std::int64_t>(bytes->size()) == *size, kHostCaptureInvalid,
            path + ": the artifact bytes do not match their hash and size");
    return *bytes;
}

/// The bridge's scalar parameter domain (`scalar_parameters`): int64, finite double or string.
bool ScalarParameters(const Value& value, bool booleans_as_integers) {
    const auto* map = std::get_if<Object>(&value.data);
    if (map == nullptr) return false;
    for (const auto& [name, item] : *map) {
        const auto* real = std::get_if<double>(&item.data);
        const bool scalar = item.IsInt() || item.IsString() || (real != nullptr && std::isfinite(*real)) ||
                            (booleans_as_integers && item.IsBool());
        if (!scalar) return false;
    }
    return true;
}

/// An int64 and a double are equal in Python only when the double is exactly that integer.
bool IntegerEqualsDouble(std::int64_t integer, double real) {
    if (!std::isfinite(real) || real != std::floor(real) || real < -9223372036854775808.0 || real >= 9223372036854775808.0) {
        return false;
    }
    return static_cast<std::int64_t>(real) == integer;
}

/// A number as Python sees it: an integer (a boolean is its integer) or a float.
std::optional<std::variant<std::int64_t, double>> PythonNumber(const Value& value) {
    if (const auto* flag = std::get_if<bool>(&value.data)) return std::variant<std::int64_t, double>(std::int64_t{*flag ? 1 : 0});
    if (const auto* integer = std::get_if<std::int64_t>(&value.data)) return std::variant<std::int64_t, double>(*integer);
    if (const auto* real = std::get_if<double>(&value.data)) return std::variant<std::int64_t, double>(*real);
    return std::nullopt;
}

/// The bridge's scalar export configuration (`bridge.export_config`) of `export_path`.
Object ExportConfig(const std::string& export_path) {
    Array maps;
    for (const auto& [name, channels] : {std::pair<const char*, const char*>{"user0", "L"}, {"user1", "RGB"}}) {
        Array list;
        for (const char* c = channels; *c != '\0'; ++c) {
            list.push_back(Object{{"destChannel", std::string(1, *c)},
                                  {"srcChannel", std::string(1, *c)},
                                  {"srcMapType", std::string("documentMap")},
                                  {"srcMapName", std::string(name)}});
        }
        maps.push_back(Object{{"fileName", std::string(name)}, {"channels", std::move(list)}});
    }
    return Object{{"exportPath", export_path},
                  {"exportShaderParams", false},
                  {"defaultExportPreset", std::string("uzp_snapshot")},
                  {"exportPresets", Array{Object{{"name", std::string("uzp_snapshot")}, {"maps", std::move(maps)}}}},
                  {"exportList", Array{Object{{"rootPath", std::string("uzp_plane")}}}},
                  {"exportParameters",
                   Array{Object{{"parameters", Object{{"fileFormat", std::string("exr")},
                                                      {"bitDepth", std::string("32f")},
                                                      {"dithering", false},
                                                      {"paddingAlgorithm", std::string("passthrough")}}}}}}};
}

bool LowercaseSha256(const Value& value) {
    const auto* text = std::get_if<std::string>(&value.data);
    return text != nullptr && text->size() == 64 &&
           std::all_of(text->begin(), text->end(), [](char c) { return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'); });
}

/// The receipt's capture protocol as the bridge writes it: the recorder pins, the Legacy host
/// identity with no project open, two `Success` exports of the raw export configuration into
/// `export1` and `export2`, and `files` naming the scalar and RGB artifacts of each round.
void CheckReceiptProtocol(const Object& receipt, const Array& scalar, const Array& rgb) {
    const Object& recorder = ClosedObject(At(receipt, "recorder"), kHostCaptureInvalid, "receipt.recorder",
                                          {"bridge_sha256", "painter_side_sha256"});
    Require(LowercaseSha256(At(recorder, "bridge_sha256")) && LowercaseSha256(At(recorder, "painter_side_sha256")),
            kHostCaptureInvalid, "receipt.recorder: expected the bridge and Painter-side SHA-256 pins");
    const Object& identity = ClosedObject(At(receipt, "identity"), kHostCaptureInvalid, "receipt.identity",
                                          {"pid", "version", "version_info", "OCIO", "PAINTER_ACE_CONFIG", "project_open", "mesh"});
    const auto* pid = std::get_if<std::int64_t>(&At(identity, "pid").data);
    const auto* version = std::get_if<std::string>(&At(identity, "version").data);
    const auto* versionInfo = std::get_if<Array>(&At(identity, "version_info").data);
    Require(pid != nullptr && *pid > 0 && version != nullptr && !version->empty() && versionInfo != nullptr &&
                !versionInfo->empty() &&
                std::all_of(versionInfo->begin(), versionInfo->end(), [](const Value& part) { return part.IsInt(); }),
            kHostCaptureInvalid, "receipt.identity: expected the Painter process and version");
    // The bridge refuses a truthy OCIO or PAINTER_ACE_CONFIG (`os.environ.get`): unset (null) or an
    // empty string is Legacy, and no other value or type is.
    const auto legacy = [](const Value& value) { return value.IsNull() || value == Value(std::string()); };
    Require(legacy(At(identity, "OCIO")) && legacy(At(identity, "PAINTER_ACE_CONFIG")) &&
                At(identity, "project_open") == Value(false) && At(identity, "mesh").IsNull(),
            kHostCaptureInvalid, "receipt.identity: the capture requires Legacy colour management and no open project");
    const Array& exports = ArrayAt(receipt, "exports", kHostCaptureInvalid, "receipt");
    Require(exports.size() == 2, kHostCaptureInvalid, "receipt.exports: expected exactly two export rounds");
    for (std::size_t i = 0; i < 2; ++i) {
        const std::string path = "receipt.exports[" + std::to_string(i) + "]";
        const Object& round = ClosedObject(exports[i], kHostCaptureInvalid, path, {"config", "result"});
        const auto* config = std::get_if<Object>(&At(round, "config").data);
        Require(config != nullptr && config->contains("exportPath") && config->at("exportPath").IsString(), kHostCaptureInvalid,
                path + ".config: expected the export configuration");
        std::string directory = std::get<std::string>(config->at("exportPath").data);
        Require(directory.ends_with("/export" + std::to_string(i + 1)) && SameTyped(At(round, "config"), ExportConfig(directory)),
                kHostCaptureInvalid, path + ".config: not the bridge's raw export configuration of round " + std::to_string(i + 1));
        const Object& result = ClosedObject(At(round, "result"), kHostCaptureInvalid, path + ".result", {"status", "message", "files"});
        Require(At(result, "status") == Value(std::string("Success")) && At(result, "message").IsString(), kHostCaptureInvalid,
                path + ".result: the export did not succeed");
        std::set<std::string> files;
        for (const Value& file : ArrayAt(result, "files", kHostCaptureInvalid, path + ".result")) {
            Require(file.IsString(), kHostCaptureInvalid, path + ".result.files: expected paths");
            std::string normal = std::get<std::string>(file.data);
            std::replace(normal.begin(), normal.end(), '\\', '/');
            files.insert(normal);
        }
        Require(files == std::set<std::string>{directory + "/user0.exr", directory + "/user1.exr"}, kHostCaptureInvalid,
                path + ".result.files: expected exactly user0.exr and user1.exr");
    }
    const Object& hashes = ClosedObject(At(receipt, "files"), kHostCaptureInvalid, "receipt.files",
                                        {"export1/user0.exr", "export1/user1.exr", "export2/user0.exr", "export2/user1.exr"});
    for (std::size_t i = 0; i < 2; ++i) {
        const std::string round = "export" + std::to_string(i + 1);
        const auto refSha = [](const Value& ref) { return std::get<Object>(ref.data).at("sha256"); };
        Require(LowercaseSha256(At(hashes, round + "/user0.exr")) && At(hashes, round + "/user0.exr") == refSha(scalar[i]) &&
                    LowercaseSha256(At(hashes, round + "/user1.exr")) && At(hashes, round + "/user1.exr") == refSha(rgb[i]),
                kHostCaptureInvalid, "receipt.files: the " + round + " exports are not the scalar and RGB artifacts of that round");
    }
}

/// An exact versioned `resource://` URL: scheme, authority, path, the single nonempty `version`
/// query and no fragment (`capture_request`).
bool VersionedResource(const std::string& url) {
    constexpr std::string_view scheme = "resource://";
    if (!url.starts_with(scheme) || url.find('#') != std::string::npos) return false;
    const std::string rest = url.substr(scheme.size());
    const auto slash = rest.find('/');
    const auto query = rest.find('?');
    if (slash == std::string::npos || slash == 0 || query == std::string::npos || query <= slash + 1) return false;
    const std::string parameters = rest.substr(query + 1);
    return parameters.starts_with("version=") && parameters.size() > 8 && parameters.find('&') == std::string::npos &&
           parameters.find('=', 8) == std::string::npos;
}

/// The bridge's capture readback predicates (`validate_readback`): the isolated paired User0 L32F /
/// User1 RGB32F layer in the input-free scalar domain of the requested resource and overrides.
void CheckReadback(const Value& value, const std::string& resource, const Object& overrides) {
    const std::string path = "receipt.readback";
    const auto* readback = std::get_if<Object>(&value.data);
    Require(readback != nullptr, kHostCaptureInvalid, path + ": expected an object");
    const auto member = [&](std::string_view name) -> const Value& {
        const auto it = readback->find(name);
        Require(it != readback->end(), kHostCaptureInvalid, path + ": missing " + std::string(name));
        return it->second;
    };
    Require(SameTyped(member("channel_formats"), Object{{"User0", std::string("L32F")}, {"User1", std::string("RGB32F")}}),
            kHostCaptureInvalid, path + ": the capture channels changed native precision");
    Require(member("source_mode") == Value(std::string("Split")) && member("projection_mode") == Value(std::string("UV")) &&
                member("active_channels") == Value(Array{std::string("User0"), std::string("User1")}),
            kHostCaptureInvalid, path + ": the capture layer is not the isolated split User0/User1 layer");
    const auto* projection = std::get_if<Object>(&member("projection").data);
    const auto field = [&](const Object& object, std::string_view name) -> const Value* {
        const auto it = object.find(name);
        return it == object.end() ? nullptr : &it->second;
    };
    Require(projection != nullptr && projection->size() == 6 && field(*projection, "filtering") &&
                *field(*projection, "filtering") == Value(std::string("Nearest")) && field(*projection, "wrapping") &&
                *field(*projection, "wrapping") == Value(std::string("RepeatNone")) && field(*projection, "scale_mode") &&
                *field(*projection, "scale_mode") == Value(std::string("Factors")) && field(*projection, "scale") &&
                NumbersAre(*field(*projection, "scale"), {1, 1}) && field(*projection, "rotation") &&
                NumberIs(*field(*projection, "rotation"), 0) && field(*projection, "offset") &&
                NumbersAre(*field(*projection, "offset"), {0, 0}),
            kHostCaptureInvalid, path + ": the capture projection changed");
    const auto* tree = std::get_if<Object>(&member("isolated_tree").data);
    Require(tree != nullptr && tree->size() == 6 && field(*tree, "fill") && field(*tree, "roots") &&
                *field(*tree, "roots") == Value(Array{*field(*tree, "fill")}) && field(*tree, "visible") &&
                *field(*tree, "visible") == Value(true) && field(*tree, "mask") && *field(*tree, "mask") == Value(false) &&
                field(*tree, "content_effects") && *field(*tree, "content_effects") == Value(Array{}) &&
                field(*tree, "mask_effects") && *field(*tree, "mask_effects") == Value(Array{}),
            kHostCaptureInvalid, path + ": the capture layer tree is not isolated");
    const auto* sets = std::get_if<Array>(&member("sets").data);
    const auto* set = sets != nullptr && sets->size() == 1 ? std::get_if<Object>(&sets->front().data) : nullptr;
    Require(set != nullptr && set->size() == 3 && field(*set, "name") && *field(*set, "name") == Value(std::string("uzp_plane")) &&
                field(*set, "resolution") && NumbersAre(*field(*set, "resolution"), {128, 128}) &&
                field(*set, "has_uv_tiles") && *field(*set, "has_uv_tiles") == Value(false),
            kHostCaptureInvalid, path + ": the capture texture set or resolution changed");
    const auto* sources = std::get_if<Array>(&member("sources").data);
    Require(sources != nullptr && sources->size() == 2 && SameTyped((*sources)[0], (*sources)[1]), kHostCaptureInvalid,
            path + ": the paired source states differ");
    const auto* source = std::get_if<Object>(&sources->front().data);
    Require(source != nullptr, kHostCaptureInvalid, path + ".sources[0]: expected an object");
    const auto sourceField = [&](std::string_view name) -> const Value& {
        const Value* found = field(*source, name);
        Require(found != nullptr, kHostCaptureInvalid, path + ".sources[0]: missing " + std::string(name));
        return *found;
    };
    const auto* activeOutput = std::get_if<std::string>(&sourceField("active_output").data);
    const auto* resolution = std::get_if<Object>(&sourceField("resolution").data);
    Require(sourceField("resource") == Value(resource) && sourceField("inputs") == Value(Array{}) && activeOutput != nullptr &&
                !activeOutput->empty() && sourceField("outputs") == Value(Array{*activeOutput}) &&
                NumberIs(sourceField("opacity"), 1) && sourceField("blending") == Value(std::string("Normal")) &&
                resolution != nullptr && field(*resolution, "mode") && *field(*resolution, "mode") == Value(std::string("Auto")) &&
                field(*resolution, "log2_offset") && NumberIs(*field(*resolution, "log2_offset"), 0),
            kHostCaptureInvalid, path + ": the source lies outside the input-free scalar capture domain");
    if (const Value* identifier = field(*source, "resource_id")) {
        const auto* parts = std::get_if<Object>(&identifier->data);
        bool complete = parts != nullptr && parts->size() == 4;
        for (const char* name : {"url", "context", "name", "version"}) {
            const Value* part = complete ? field(*parts, name) : nullptr;
            complete = complete && part != nullptr && part->IsString() && !std::get<std::string>(part->data).empty();
        }
        Require(complete && *field(*parts, "url") == Value(resource), kHostCaptureInvalid,
                path + ": the observed ResourceID must be complete and match the requested resource");
    }
    const Value& parameters = sourceField("parameters");
    Require(ScalarParameters(parameters, false), kHostCaptureInvalid, path + ": the effective parameters are not scalar");
    const auto& effective = std::get<Object>(parameters.data);
    for (const auto& [name, requested] : overrides) {
        const auto it = effective.find(name);
        Require(it != effective.end() && detail::BridgeScalarEquals(requested, it->second), kHostCaptureInvalid,
                path + ": the effective parameters differ from the requested overrides");
    }
}

/// The scalar texels of a stored plane format as bits.
std::vector<std::uint32_t> Bits(const std::string& texels) {
    std::vector<std::uint32_t> bits(texels.size() / 4);
    std::memcpy(bits.data(), texels.data(), bits.size() * 4);
    return bits;
}

}  // namespace

bool detail::BridgeScalarEquals(const Value& requested, const Value& effective) {
    if (requested.IsString() || effective.IsString()) return requested.IsString() && effective.IsString() && requested == effective;
    const auto a = PythonNumber(requested);
    const auto b = PythonNumber(effective);
    if (!a || !b) return false;
    if (const auto* x = std::get_if<std::int64_t>(&*a)) {
        if (const auto* y = std::get_if<std::int64_t>(&*b)) return *x == *y;
        return IntegerEqualsDouble(*x, std::get<double>(*b));
    }
    const double x = std::get<double>(*a);
    if (const auto* y = std::get_if<std::int64_t>(&*b)) return IntegerEqualsDouble(*y, x);
    return x == std::get<double>(*b);
}

std::expected<VerifiedHostMigration, ImportRefusal> VerifyHostCapture(store::ProjectStore& store, const core::Project& project,
                                                                     const Object& host_capture,
                                                                     const ArtifactBytes& artifacts) {
    try {
        const std::string path = "capture.host";
        const Value captureValue(host_capture);
        const Object& capture = ClosedObject(captureValue, kHostCaptureInvalid, path,
                                             {"protocol", "receipt", "request", "environment", "environment_binding",
                                              "scalar_exports", "rgb_exports"});
        Require(StringAt(capture, "protocol", kHostCaptureInvalid, path) == "paired-scalar-rgb", kHostCaptureInvalid,
                path + ".protocol: expected paired-scalar-rgb");

        // The destination host, its exact request and its recorded snapshot with /3 metadata.
        store::FrozenHostNodes nodes;
        const std::string domain = store::FrozenHostDomainProblem(project, nodes);
        Require(domain.empty(), kTargetContextUnrepresentable, domain);
        auto request = SnapshotFillRequest(project, *nodes.set, core::ChannelType::User0, core::ChannelFormat::L32F,
                                           *nodes.host->fill, *nodes.host_ref, nodes.host->uid, false);
        Require(request.has_value(), kTargetContextUnrepresentable, "the host is outside the snapshot provider's domain");
        const std::string key = SignatureHash(*request);
        std::optional<store::SnapshotEntry> snapshot;
        for (store::SnapshotEntry& entry : store::ProjectSnapshots(project)) {
            if (entry.key == key) snapshot = std::move(entry);
        }
        Require(snapshot && snapshot->source_metadata && snapshot->source_metadata->typed_effective_parameters &&
                    snapshot->source_metadata->observed_resource_id,
                kHostSourceStateMismatch, "no recorded snapshot with /3 metadata holds the host's request");
        const store::ObservationInventory inventory = store.ReadObservationInventory(project);
        const auto plane = std::find_if(inventory.planes.begin(), inventory.planes.end(),
                                        [&](const store::InventoryPlane& p) { return p.row.plane_id == snapshot->plane_id; });
        Require(plane != inventory.planes.end(), kHostSourceStateMismatch, "the census holds no plane of the host snapshot");

        // The receipt, bound to this store, the stored signature and the observed resource.
        const Value receiptValue = Parse(Resolve(At(capture, "receipt"), "snapshot_receipt", artifacts, path + ".receipt"),
                                         kHostCaptureInvalid, "the receipt");
        const Object& receipt = ClosedObject(receiptValue, kHostCaptureInvalid, "receipt",
                                             {"schema", "recorder", "identity", "resource", "readback", "exports",
                                              "project_uuid", "revision", "signature", "files"});
        Require(StringAt(receipt, "schema", kHostCaptureInvalid, "receipt") == "uzpainter/procedural-capture/1",
                kHostCaptureInvalid, "receipt.schema: expected uzpainter/procedural-capture/1");
        Require(StringAt(receipt, "project_uuid", kHostCaptureInvalid, "receipt") == store.project_uuid(),
                kHostSourceStateMismatch, "the receipt was recorded for another project");
        const auto* revision = std::get_if<std::int64_t>(&At(receipt, "revision").data);
        Require(revision != nullptr && *revision >= 0, kHostCaptureInvalid, "receipt.revision: expected a nonnegative integer");
        Require(SameTyped(At(receipt, "signature"), snapshot->signature) && SameTyped(At(receipt, "signature"), SignatureJson(*request)),
                kHostSourceStateMismatch, "the receipt's signature is not the stored host snapshot's");
        const std::string& resource = StringAt(receipt, "resource", kHostCaptureInvalid, "receipt");
        const auto& signature = std::get<Object>(snapshot->signature.data);
        Require(signature.contains("asset") &&
                    signature.at("asset") == Value("uzasset://snapshot/" + core::Sha256Hex(resource)),
                kHostSourceStateMismatch, "the observed resource does not name the snapshot's pin");

        // The request: the exact versioned resource and the scalar overrides.
        const Value requestValue = Parse(Resolve(At(capture, "request"), "snapshot_request", artifacts, path + ".request"),
                                         kHostCaptureInvalid, "the request");
        const Object& captureRequest = ClosedObject(requestValue, kHostCaptureInvalid, "request", {"resource", "parameters"});
        Require(StringAt(captureRequest, "resource", kHostCaptureInvalid, "request") == resource && VersionedResource(resource),
                kHostCaptureInvalid, "the request is not the receipt's exact versioned resource");
        Require(ScalarParameters(At(captureRequest, "parameters"), true), kHostCaptureInvalid,
                "request.parameters: only finite scalar values are supported");

        // The historical H environment and its binding: no supported representation exists, so
        // only their recorded absence is accepted.
        Require(At(capture, "environment").IsNull() && At(capture, "environment_binding").IsNull(), kHostCaptureInvalid,
                path + ": no supported representation of H environment evidence exists; both must be null");
        const Array& scalarRefs = ArrayAt(capture, "scalar_exports", kHostCaptureInvalid, path);
        const Array& rgbRefs = ArrayAt(capture, "rgb_exports", kHostCaptureInvalid, path);
        Require(scalarRefs.size() == 2 && rgbRefs.size() == 2 &&
                    std::all_of(scalarRefs.begin(), scalarRefs.end(), [](const Value& v) { return v.IsObject() && std::get<Object>(v.data).contains("sha256"); }) &&
                    std::all_of(rgbRefs.begin(), rgbRefs.end(), [](const Value& v) { return v.IsObject() && std::get<Object>(v.data).contains("sha256"); }),
                kHostCaptureInvalid, path + ": expected two scalar and two RGB export references");
        CheckReceiptProtocol(receipt, scalarRefs, rgbRefs);

        // The readback and the metadata it observed.
        CheckReadback(At(receipt, "readback"), resource, std::get<Object>(At(captureRequest, "parameters").data));
        const auto metadata = ReceiptSourceMetadata(receiptValue, resource, *request);
        Require(metadata.has_value(), kHostCaptureInvalid, metadata ? std::string() : metadata.error());
        Require(SameTyped(store::SourceMetadataJson(snapshot->signature, *metadata),
                          store::SourceMetadataJson(snapshot->signature, *snapshot->source_metadata)),
                kHostSourceStateMismatch, "the receipt's observations are not the stored /3 metadata");

        // The exports at native precision: scalar rounds, RGB components and the census raster.
        const auto exports = [&](std::string_view field, std::string_view kind, std::uint32_t channels) {
            const Array& refs = ArrayAt(capture, field, kHostCaptureInvalid, path);
            Require(refs.size() == 2, kHostCaptureInvalid, path + "." + std::string(field) + ": expected exactly two exports");
            std::vector<std::vector<std::uint32_t>> rounds;
            for (std::size_t i = 0; i < refs.size(); ++i) {
                const std::string item = path + "." + std::string(field) + "[" + std::to_string(i) + "]";
                const auto texels = SnapshotExportTexels(Resolve(refs[i], kind, artifacts, item),
                                                         RasterSpec{128, ChannelFormat::F32, "raw", channels});
                Require(texels.has_value(), kNativeTransportMismatch, item + ": " + (texels ? std::string() : texels.error()));
                rounds.push_back(Bits(*texels));
            }
            return rounds;
        };
        const auto scalar = exports("scalar_exports", "snapshot_scalar_export", 1);
        const auto rgb = exports("rgb_exports", "snapshot_rgb_export", 3);
        Require(scalar[0] == scalar[1] && rgb[0] == rgb[1], kNativeTransportMismatch, "the paired export rounds differ");
        bool components = rgb[0].size() == scalar[0].size() * 3;
        for (std::size_t i = 0; components && i < scalar[0].size(); ++i) {
            components = rgb[0][3 * i] == scalar[0][i] && rgb[0][3 * i + 1] == scalar[0][i] && rgb[0][3 * i + 2] == scalar[0][i];
        }
        Require(components, kNativeTransportMismatch, "an RGB export component differs from the scalar export");
        const std::string raster(reinterpret_cast<const char*>(scalar[0].data()), scalar[0].size() * 4);
        Require(core::Sha256Hex(raster) == plane->sha256, kNativeTransportMismatch,
                "the scalar export is not the stored snapshot raster");

        VerifiedHostMigration verified;
        verified.host_capture_ = host_capture;
        verified.capture_context_sha256_ = store::ObservationKey(At(receipt, "readback"));
        verified.signature_sha256_ = key;
        verified.project_uuid_ = store.project_uuid();
        verified.plane_id_ = static_cast<std::int64_t>(plane->row.plane_id);
        verified.version_id_ = plane->version.version_id;
        verified.chunk_root_ = plane->version.chunk_root;
        verified.raster_sha256_ = plane->sha256;
        verified.byte_count_ = plane->byte_count;
        verified.metadata_sha256_ =
            store::ObservationKey(store::SourceMetadataJson(snapshot->signature, *snapshot->source_metadata));
        return verified;
    } catch (const ImportRefused& refused) {
        return std::expected<VerifiedHostMigration, ImportRefusal>(std::unexpect, refused.refusal);
    } catch (const std::exception& error) {
        return std::expected<VerifiedHostMigration, ImportRefusal>(
            std::unexpect, ImportRefusal{std::string(kHostCaptureInvalid), error.what()});
    }
}

Object VerifiedHostMigration::Identity() const {
    return Object{{"project_uuid", project_uuid_}, {"signature_sha256", signature_sha256_},
                  {"plane_id", plane_id_},         {"version_id", version_id_},
                  {"chunk_root", chunk_root_},     {"raster_sha256", raster_sha256_},
                  {"byte_count", byte_count_},     {"metadata_sha256", metadata_sha256_},
                  {"capture_context_sha256", capture_context_sha256_}};
}

core::MutationRequest FilterObservationCommitRequest(const VerifiedHostMigration& host, const VerifiedFilterContext& filter,
                                                     const ImportTarget& target) {
    const Object arguments{
        {"target", Object{{"project_uuid", target.project_uuid},
                          {"revision", target.revision},
                          {"base_projection_sha256", target.base_projection_sha256},
                          {"filter_uid", static_cast<std::int64_t>(target.filter_uid)}}},
        {"host", Object{{"capture", host.HostCapture()}, {"identity", host.Identity()}}},
        {"filter", Object{{"effect", core::EffectToJson(filter.Effect(), false)},
                          {"descriptor", filter.Descriptor()},
                          {"observations", filter.Observations()},
                          {"capture", filter.FilterCapture()}}}};
    return core::MutationRequest{"filter-observation-commit-v2", arguments,
                                 "filter-observation-commit-v2:" + store::ObservationKey(arguments), target.revision};
}

std::optional<ImportRefusal> RecheckProspectiveView(store::ProjectStore& store, const core::Document& document,
                                                    const core::Project& project, const Object& context,
                                                    std::int64_t revision) {
    try {
        if (store.CheckpointState().current != revision || document.revision() != revision) {
            return ImportRefusal{std::string(kStaleProspectiveView), "the owning revision moved"};
        }
        Value projection = core::ProjectToJson(project);
        std::get<Object>(projection.data).erase(std::string(store::kFilterObservationsKey));
        if (!SameTyped(projection, context.at("project"))) {
            return ImportRefusal{std::string(kStaleProspectiveView), "the prospective projection changed"};
        }
        if (store.ReadObservationInventory(project).Sha256() != store::ObservationKey(context.at("inventory"))) {
            return ImportRefusal{std::string(kStaleProspectiveView), "the census changed"};
        }
        return std::nullopt;
    } catch (const std::exception& error) {
        return ImportRefusal{std::string(kStaleProspectiveView), error.what()};
    }
}

std::expected<std::string, ImportRefusal> CommitFilterObservation(store::ProjectStore& store, core::Document& document,
                                                                  const VerifiedHostMigration& host,
                                                                  const VerifiedFilterContext& filter,
                                                                  const ImportTarget& target,
                                                                  const evaluator::TemplateLibrary& templates) {
    const std::string descriptorKey = store::ObservationKey(filter.Descriptor());
    std::optional<ImportRefusal> refusal;
    std::string entryKey;
    const core::MutationRequest request = FilterObservationCommitRequest(host, filter, target);
    const core::RequestOutcome outcome = store.Submit(document, request, [&](core::Edit& edit) {
        try {
            core::Project& project = edit.project();
            Require(store.project_uuid() == target.project_uuid, kTargetContextUnrepresentable, "the target is another project");
            Require(host.ProjectUuid() == store.project_uuid(), kHostSourceStateMismatch,
                    "the verified H capture belongs to another store");
            Require(document.revision() == target.revision, kStaleProspectiveView, "the owning Document is at another revision");
            Require(!project.extra.contains(std::string(store::kFilterObservationsKey)), kUnreviewedContextDifference,
                    "the target already holds observations");
            Value base = core::ProjectToJson(project);
            std::get<Object>(base.data).erase(std::string(store::kFilterObservationsKey));
            Require(store::ObservationKey(base) == target.base_projection_sha256, kStaleProspectiveView,
                    "the project is not the target base projection");
            Require(project.texture_sets.size() == 1 && project.texture_sets[0].stacks.size() == 1 &&
                        !project.texture_sets[0].stacks[0].root_layers.empty() &&
                        project.texture_sets[0].stacks[0].root_layers[0].content_effects.empty(),
                    kTargetContextUnrepresentable, "the host Fill is not the base's top layer without effects");
            const core::Id uid = edit.AllocateId();
            Require(uid == target.filter_uid, kTargetContextUnrepresentable, "the Filter id is not the base's next id");
            core::Effect effect = filter.Effect();
            effect.uid = uid;
            Require(effect.procedural && effect.procedural->asset == store::ObservationPin(descriptorKey),
                    kTargetContextUnrepresentable, "the verified Filter reference is not the descriptor's pin");
            project.texture_sets[0].stacks[0].root_layers[0].content_effects.push_back(std::move(effect));

            store::FrozenHostNodes nodes;
            const std::string domain = store::FrozenHostDomainProblem(project, nodes);
            Require(domain.empty(), kTargetContextUnrepresentable, domain);
            auto hostRequest = SnapshotFillRequest(project, *nodes.set, core::ChannelType::User0, core::ChannelFormat::L32F,
                                                   *nodes.host->fill, *nodes.host_ref, nodes.host->uid, false);
            Require(hostRequest && SignatureHash(*hostRequest) == host.SignatureSha256(), kHostSourceStateMismatch,
                    "the host's request is not the verified H snapshot");
            const auto context = CurrentFilterObservationContextV2(store, project);
            Require(context.has_value(), kTargetContextUnrepresentable, context ? std::string() : context.error());
            // The verified H capture still describes this prospective snapshot and its census plane.
            const Object identity = host.Identity();
            bool snapshotBound = false;
            for (const store::SnapshotEntry& entry : store::ProjectSnapshots(project)) {
                if (entry.key != host.SignatureSha256() || !entry.source_metadata) continue;
                snapshotBound = Value(static_cast<std::int64_t>(entry.plane_id)) == identity.at("plane_id") &&
                                Value(store::ObservationKey(store::SourceMetadataJson(entry.signature, *entry.source_metadata))) ==
                                    identity.at("metadata_sha256");
            }
            bool planeBound = false;
            for (const Value& plane : std::get<Array>(std::get<Object>(context->at("inventory").data).at("planes").data)) {
                const auto& object = std::get<Object>(plane.data);
                if (object.at("plane_id") != identity.at("plane_id")) continue;
                planeBound = object.at("version_id") == identity.at("version_id") &&
                             object.at("chunk_root") == identity.at("chunk_root") &&
                             object.at("sha256") == identity.at("raster_sha256") &&
                             object.at("byte_count") == identity.at("byte_count");
            }
            Require(snapshotBound && planeBound, kHostSourceStateMismatch,
                    "the verified H capture no longer describes the host snapshot and its census plane");

            const auto proof = RunFrozenHostProof(store, project, templates);
            Require(proof.has_value(), kNativeTransportMismatch, proof ? std::string() : proof.error());
            Require(proof->nonfinite == 0 && proof->fixed_point_mismatches == 0, kFrozenRasterNotFixedPoint,
                    "the frozen raster is not finite and fixed under the read-out");
            Require(proof->upload_mismatches == 0 && proof->final_output_mismatches == 0, kNativeTransportMismatch,
                    "the native upload or final output differs from the frozen raster");
            for (const char* field : {"signature_sha256", "plane_id", "version_id", "chunk_root", "raster_sha256"}) {
                Require(proof->evidence.at(field) == identity.at(field), kHostSourceStateMismatch,
                        std::string("the native proof ran on another host snapshot (") + field + ")");
            }
            Require(proof->evidence.at("prospective_projection_sha256") == Value(store::ObservationKey(context->at("project"))) &&
                        proof->evidence.at("inventory_sha256") == Value(store::ObservationKey(context->at("inventory"))),
                    kStaleProspectiveView, "the proof ran on another view than the context");
            if (const auto stale = RecheckProspectiveView(store, document, project, *context, target.revision)) {
                RefuseImport(stale->reason, stale->detail);
            }

            const std::string contextHash = store::ObservationKey(*context);
            Value raster;
            for (const Value& plane : std::get<Array>(std::get<Object>(context->at("inventory").data).at("planes").data)) {
                const auto& object = std::get<Object>(plane.data);
                if (object.at("plane_id") == proof->evidence.at("plane_id")) raster = object.at("sha256");
            }
            Object entry{
                {"schema", std::string(store::kObservationEntrySchemaV2)},
                {"project_uuid", store.project_uuid()},
                {"role", std::string("filter")},
                {"host_snapshot", Object{{"signature_sha256", host.SignatureSha256()}, {"plane_id", proof->evidence.at("plane_id")}}},
                {"filter_descriptor", descriptorKey},
                {"binding", Object{{"texture_set", static_cast<std::int64_t>(nodes.set->id)},
                                   {"stack", static_cast<std::int64_t>(nodes.stack->id)},
                                   {"host_uid", static_cast<std::int64_t>(nodes.host->uid)},
                                   {"filter_uid", static_cast<std::int64_t>(nodes.filter->uid)},
                                   {"initial_paint_uid", static_cast<std::int64_t>(nodes.paint->uid)},
                                   {"node_stack", std::string("Content")},
                                   {"effect_index", std::int64_t{0}},
                                   {"host_channel", std::string("User0")},
                                   {"host_reference", core::ProceduralRefToJson(*nodes.host_ref)},
                                   {"filter_reference", core::ProceduralRefToJson(*nodes.filter->procedural)}}},
                {"context", *context},
                {"context_sha256", contextHash},
                {"capture", Object{{"schema", std::string(store::kObservationCaptureSchemaV2)},
                                   {"filter", filter.FilterCapture()},
                                   {"host", host.HostCapture()},
                                   {"migration", Object{{"rule", std::string(store::kFrozenHostRule)},
                                                        {"raster_stage", std::string("frozen_output")},
                                                        {"raster_sha256", raster},
                                                        {"capture_context_sha256", host.CaptureContextSha256()},
                                                        {"destination_host_context_sha256", contextHash},
                                                        {"native_evidence", proof->evidence}}}}},
                {"observations", filter.Observations()}};
            const std::string key = store::ObservationKey(entry);
            const Value space = Object{{"schema", std::string(store::kFilterObservationsSchemaV2)},
                                       {"descriptors", Object{{descriptorKey, filter.Descriptor()}}},
                                       {"entries", Object{{key, std::move(entry)}}},
                                       {"bindings", Object{{std::to_string(nodes.filter->uid), key}}}};
            const std::string problem = store::FilterObservationsProblem(space, store.project_uuid());
            Require(problem.empty(), kUnreviewedContextDifference, problem);
            project.extra[std::string(store::kFilterObservationsKey)] = space;
            const auto observed = ObservedFilter(store, project, nodes.filter->uid);
            Require(observed.has_value() && observed->entry_key == key, kUnreviewedContextDifference,
                    "the inserted observation does not resolve to its entry");
            // Persisted in the operation record, so an exact retry returns this commit's entry.
            edit.returned()["entry_key"] = key;
            entryKey = key;
        } catch (const ImportRefused& refused) {
            refusal = refused.refusal;
            throw std::runtime_error(refused.refusal.reason + ": " + refused.refusal.detail);
        }
    });
    if (refusal) return std::expected<std::string, ImportRefusal>(std::unexpect, *refusal);
    // A stored outcome is an earlier commit of this exact request (only commits are recorded): the
    // store returns its record, not a result, and nothing executes again.
    const bool replayed = outcome.decision.admission == core::Admission::stored_outcome && outcome.decision.record;
    if (!replayed && (!outcome.result || outcome.result->status != core::ResultStatus::committed)) {
        std::string detail = outcome.result ? outcome.result->error : std::string(core::ToString(outcome.decision.admission));
        return std::expected<std::string, ImportRefusal>(std::unexpect,
                                                         ImportRefusal{std::string(kStaleProspectiveView), std::move(detail)});
    }
    if (entryKey.empty()) {
        // An earlier commit of this exact request: the entry that commit returned, never the
        // document's current binding (it may since be removed or rebound to another entry).
        const Value& stored = outcome.decision.record->outcome;
        if (stored.IsObject()) {
            const auto returned = std::get<Object>(stored.data).find("returned");
            if (returned != std::get<Object>(stored.data).end() && returned->second.IsObject()) {
                const auto& values = std::get<Object>(returned->second.data);
                const auto key = values.find("entry_key");
                if (values.size() == 1 && key != values.end() && key->second.IsString() &&
                    core::IsSha256Hex(std::get<std::string>(key->second.data))) {
                    return std::get<std::string>(key->second.data);
                }
            }
        }
        return std::expected<std::string, ImportRefusal>(
            std::unexpect, ImportRefusal{std::string(kStaleProspectiveView), "a stored outcome without its returned entry"});
    }
    return entryKey;
}

}  // namespace uzp::procedural
