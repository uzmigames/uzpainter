// Decision 363: the internal V2 verified-context transaction component on authored evidence. The
// H artifacts (receipt, request, exports) and the F context are authored here, never Painter
// records; the F context is built through the test-only access below, which no production source
// defines.

#include <bit>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <functional>
#include <iostream>
#include <limits>
#include <map>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

#include "evaluator/templates.h"
#include "export/exr_writer.h"
#include "procedural/filter_observation_import_v2.h"
#include "procedural/filter_observation_source.h"
#include "procedural/seam.h"
#include "procedural/snapshot_backend.h"
#include "procedural/snapshot_recording.h"
#include "procedural/snapshot_source.h"
#include "store/filter_observations.h"
#include "store/observation_inventory.h"
#include "store/project_store.h"
#include "store/snapshots.h"
#include "uzp_core/manifest/manifest.h"
#include "uzp_core/manifest/sha256.h"
#include "../filter_observation_v2_fixture.h"

namespace uzp::procedural {

/// The authored-tests-only route to a verified F context (the F gate does not exist yet).
struct FilterImportTestAccess {
    static VerifiedFilterContext Make(core::Effect effect, core::json::Object descriptor, core::json::Object observations,
                                      core::json::Object filter_capture) {
        VerifiedFilterContext context;
        context.effect_ = std::move(effect);
        context.descriptor_ = std::move(descriptor);
        context.observations_ = std::move(observations);
        context.filter_capture_ = std::move(filter_capture);
        return context;
    }
};

}  // namespace uzp::procedural

namespace {

namespace fs = std::filesystem;
namespace json = uzp::core::json;
namespace fx = uzp::v2fixture;
using namespace uzp;
using procedural::FilterImportTestAccess;
using procedural::ImportRefusal;

void Expect(bool okay, const std::string& message) {
    if (!okay) throw std::runtime_error(message);
}

/// The authored H readback of the paired capture (the bridge's isolated User0/User1 layer).
json::Object Readback() {
    const json::Object source{
        {"resource", std::string(fx::kHostUrl)},
        {"inputs", json::Array{}},
        {"outputs", json::Array{std::string("scalar")}},
        {"active_output", std::string("scalar")},
        {"opacity", std::int64_t{1}},
        {"blending", std::string("Normal")},
        {"resolution", json::Object{{"mode", std::string("Auto")}, {"log2_offset", std::int64_t{0}}}},
        {"resource_id", json::Object{{"url", std::string(fx::kHostUrl)}, {"context", std::string("authored")},
                                     {"name", std::string("host")}, {"version", std::string("1")}}},
        {"parameters", json::Object{{"amount", 0.5}}}};
    return json::Object{
        {"channel_formats", json::Object{{"User0", std::string("L32F")}, {"User1", std::string("RGB32F")}}},
        {"source_mode", std::string("Split")},
        {"projection_mode", std::string("UV")},
        {"active_channels", json::Array{std::string("User0"), std::string("User1")}},
        {"projection", json::Object{{"filtering", std::string("Nearest")}, {"wrapping", std::string("RepeatNone")},
                                    {"scale_mode", std::string("Factors")}, {"scale", json::Array{std::int64_t{1}, std::int64_t{1}}},
                                    {"rotation", std::int64_t{0}}, {"offset", json::Array{std::int64_t{0}, std::int64_t{0}}}}},
        {"isolated_tree", json::Object{{"roots", json::Array{std::int64_t{7}}}, {"fill", std::int64_t{7}}, {"visible", true},
                                       {"mask", false}, {"content_effects", json::Array{}}, {"mask_effects", json::Array{}}}},
        {"sets", json::Array{json::Object{{"name", std::string("uzp_plane")},
                                          {"resolution", json::Array{std::int64_t{128}, std::int64_t{128}}},
                                          {"has_uv_tiles", false}}}},
        {"sources", json::Array{source, source}}};
}

/// The bridge's raw export configuration and a successful result for round `index`.
json::Object ExportRound(int index) {
    const std::string directory = "C:/private/h-capture/export" + std::to_string(index);
    json::Array maps;
    for (const auto& [name, channels] : {std::pair<const char*, const char*>{"user0", "L"}, {"user1", "RGB"}}) {
        json::Array list;
        for (const char* c = channels; *c != '\0'; ++c) {
            list.push_back(json::Object{{"destChannel", std::string(1, *c)}, {"srcChannel", std::string(1, *c)},
                                        {"srcMapType", std::string("documentMap")}, {"srcMapName", std::string(name)}});
        }
        maps.push_back(json::Object{{"fileName", std::string(name)}, {"channels", std::move(list)}});
    }
    const json::Object config{
        {"exportPath", directory}, {"exportShaderParams", false}, {"defaultExportPreset", std::string("uzp_snapshot")},
        {"exportPresets", json::Array{json::Object{{"name", std::string("uzp_snapshot")}, {"maps", std::move(maps)}}}},
        {"exportList", json::Array{json::Object{{"rootPath", std::string("uzp_plane")}}}},
        {"exportParameters", json::Array{json::Object{{"parameters", json::Object{{"fileFormat", std::string("exr")},
                                                                                  {"bitDepth", std::string("32f")},
                                                                                  {"dithering", false},
                                                                                  {"paddingAlgorithm", std::string("passthrough")}}}}}}};
    return json::Object{{"config", config},
                        {"result", json::Object{{"status", std::string("Success")}, {"message", std::string("")},
                                                {"files", json::Array{directory + "/user0.exr", directory + "/user1.exr"}}}}};
}

/// One authored destination with its H evidence and transport.
struct Case {
    std::unique_ptr<store::ProjectStore> store;
    std::unique_ptr<core::Document> document;
    fx::SceneIds ids;
    json::Object receipt;
    json::Object request;
    std::string scalarExr;
    std::string rgbExr;
    std::map<std::string, std::string, std::less<>> artifacts;

    procedural::ArtifactBytes Transport() const {
        return [this](std::string_view sha) -> std::optional<std::string> {
            const auto found = artifacts.find(sha);
            return found == artifacts.end() ? std::nullopt : std::optional<std::string>(found->second);
        };
    }
    json::Object Ref(const std::string& kind, const std::string& bytes) {
        const std::string sha = core::Sha256Hex(bytes);
        artifacts[sha] = bytes;
        return json::Object{{"kind", kind}, {"sha256", sha}, {"size_bytes", static_cast<std::int64_t>(bytes.size())}};
    }
    /// The capture/2 host section over the current authored artifacts.
    json::Object HostCapture() {
        const std::string receiptBytes = json::WriteCanonical(receipt);
        const std::string requestBytes = json::WriteCanonical(request);
        return json::Object{{"protocol", std::string("paired-scalar-rgb")},
                            {"receipt", Ref("snapshot_receipt", receiptBytes)},
                            {"request", Ref("snapshot_request", requestBytes)},
                            {"environment", json::Value()},
                            {"environment_binding", json::Value()},
                            {"scalar_exports", json::Array{Ref("snapshot_scalar_export", scalarExr), Ref("snapshot_scalar_export", scalarExr)}},
                            {"rgb_exports", json::Array{Ref("snapshot_rgb_export", rgbExr), Ref("snapshot_rgb_export", rgbExr)}}};
    }
};

std::string Exr(const std::vector<std::uint32_t>& bits, std::uint32_t channels) {
    exporter::ExrImage image{128, 128, channels, {}, false};
    image.values.reserve(bits.size() * channels);
    for (const std::uint32_t b : bits) {
        for (std::uint32_t c = 0; c < channels; ++c) image.values.push_back(std::bit_cast<float>(b));
    }
    return exporter::EncodeExr(image);
}

Case Prepare(const fs::path& file, const std::vector<std::uint32_t>& pattern,
             const std::string& uuid = "6f1c2a3e-0000-4000-8000-0000000a3633") {
    Case c;
    const std::string plane = fx::PlaneObj();
    core::DocumentState initial;
    initial.project_uuid = uuid;
    initial.project = fx::Scene(store::ObservationPin(store::ObservationKey(fx::FilterDescriptor())), plane.size(), c.ids);
    initial.project.texture_sets[0].stacks[0].root_layers[0].content_effects.clear();
    store::CreateOptions options;
    options.resources = {store::PendingContent::Bytes{plane, "model/obj"}};
    c.store = store::ProjectStore::Create(file, initial, options);
    c.document = std::make_unique<core::Document>(initial);
    c.store->Attach(*c.document);
    std::vector<std::uint32_t> bits(128 * 128);
    for (std::size_t i = 0; i < bits.size(); ++i) bits[i] = pattern[i % pattern.size()];
    std::string bytes(bits.size() * 4, '\0');
    std::memcpy(bytes.data(), bits.data(), bytes.size());
    c.scalarExr = Exr(bits, 1);
    c.rgbExr = Exr(bits, 3);
    c.request = json::Object{{"resource", std::string(fx::kHostUrl)}, {"parameters", json::Object{{"amount", 0.5}}}};
    std::optional<std::string> failure;
    const auto outcome = c.store->Submit(
        *c.document, {"filter-import-v2-test", json::Object{}, "record", c.document->revision()}, [&](core::Edit& edit) {
            core::Project& project = edit.project();
            core::Layer& host = project.texture_sets[0].stacks[0].root_layers[0];
            const core::ProceduralRef& ref = std::get<core::ProceduralSource>(host.fill->sources.at(core::ChannelType::User0).value).ref;
            auto request = procedural::SnapshotFillRequest(project, project.texture_sets[0], core::ChannelType::User0,
                                                           core::ChannelFormat::L32F, *host.fill, ref, host.uid, false);
            if (!request) throw std::runtime_error(request.error());
            c.receipt = json::Object{
                {"schema", std::string("uzpainter/procedural-capture/1")},
                {"recorder", json::Object{{"bridge_sha256", core::Sha256Hex("authored bridge")},
                                          {"painter_side_sha256", core::Sha256Hex("authored painter side")}}},
                {"identity", json::Object{{"pid", std::int64_t{4242}}, {"version", std::string("12.2.0")},
                                          {"version_info", json::Array{std::int64_t{12}, std::int64_t{2}, std::int64_t{0}}},
                                          {"OCIO", json::Value()}, {"PAINTER_ACE_CONFIG", json::Value()},
                                          {"project_open", false}, {"mesh", json::Value()}}},
                {"resource", std::string(fx::kHostUrl)},
                {"readback", Readback()},
                {"exports", json::Array{ExportRound(1), ExportRound(2)}},
                {"project_uuid", c.store->project_uuid()},
                {"revision", c.document->revision()},
                {"signature", procedural::SignatureJson(*request)},
                {"files", json::Object{{"export1/user0.exr", core::Sha256Hex(c.scalarExr)},
                                       {"export1/user1.exr", core::Sha256Hex(c.rgbExr)},
                                       {"export2/user0.exr", core::Sha256Hex(c.scalarExr)},
                                       {"export2/user1.exr", core::Sha256Hex(c.rgbExr)}}}};
            auto metadata = procedural::ReceiptSourceMetadata(c.receipt, fx::kHostUrl, *request);
            if (!metadata) {
                failure = metadata.error();
                throw std::runtime_error(metadata.error());
            }
            procedural::RecordSnapshot(*c.store, edit, *request, bytes, *metadata);
        });
    Expect(outcome.result && outcome.result->status == core::ResultStatus::committed,
           "record the authored host snapshot: " + failure.value_or(outcome.result ? outcome.result->error : ""));
    return c;
}

/// The authored verified F context (through the test-only access).
procedural::VerifiedFilterContext FilterContext(const std::string& name = "Blur", bool emptyOutputs = true) {
    const json::Object descriptor = fx::FilterDescriptor();
    core::Effect effect;
    effect.kind = core::EffectKind::filter;
    effect.name = name;
    effect.active_channels = {core::ChannelType::User0};
    effect.blending[core::ChannelType::User0] = core::Blending{core::BlendingMode::Normal, 1.0, {}};
    effect.procedural.emplace();
    effect.procedural->asset = store::ObservationPin(store::ObservationKey(descriptor));
    effect.procedural->params = {{"radius", std::int64_t{1}}, {"zero", 0.0}};
    const auto round = [](const std::string& condition) {
        return json::Object{{"condition", condition},
                            {"probe_sequence_sha256", core::Sha256Hex(condition + " probes")},
                            {"context_readback_sha256", core::Sha256Hex(condition + " context")},
                            {"host_readback_sha256", core::Sha256Hex(condition + " host")},
                            {"filter_readback_sha256", core::Sha256Hex(condition + " filter")}};
    };
    const auto ref = [](const std::string& kind) {
        return json::Object{{"kind", kind}, {"sha256", core::Sha256Hex(kind)}, {"size_bytes", std::int64_t{1}}};
    };
    const json::Object filterCapture{
        {"provenance", json::Object{{"recorder", std::string("authored")}, {"envelope_id", std::string("authored")},
                                    {"painter_build_id", std::string("authored")}, {"recipe_sha256", core::Sha256Hex("recipe")},
                                    {"resource_query", std::string("authored")}, {"authored_inputs", json::Array{}},
                                    {"receipts", json::Array{json::Object{{"condition", std::string("same_session")},
                                                                          {"sha256", core::Sha256Hex("r1")}},
                                                             json::Object{{"condition", std::string("after_save_reopen")},
                                                                          {"sha256", core::Sha256Hex("r2")}}}}}},
        {"manifest", ref("filter_manifest")},
        {"record", ref("filter_record")},
        {"environment", ref("filter_environment")},
        {"rounds", json::Array{round("same_session"), round("after_save_reopen")}}};
    const json::Object observations{{"parameters", descriptor.at("parameters")},
                                    {"resource_id", descriptor.at("resource_id")},
                                    {"image_outputs", emptyOutputs ? json::Array{} : json::Array{std::string("other")}}};
    return FilterImportTestAccess::Make(std::move(effect), descriptor, observations, filterCapture);
}

core::Project Prospective(const core::Project& base, const procedural::VerifiedFilterContext& filter) {
    core::Project prospective = base;
    core::Effect effect = filter.Effect();
    effect.uid = prospective.AllocateId();
    prospective.texture_sets[0].stacks[0].root_layers[0].content_effects.push_back(std::move(effect));
    return prospective;
}

procedural::ImportTarget Target(const Case& c) {
    const core::Project project = *c.document->snapshot().project;
    json::Value projection = core::ProjectToJson(project);
    std::get<json::Object>(projection.data).erase(std::string(store::kFilterObservationsKey));
    return procedural::ImportTarget{c.store->project_uuid(), c.document->revision(), store::ObservationKey(projection),
                                    project.next_id};
}

bool Refused(const std::expected<procedural::VerifiedHostMigration, ImportRefusal>& result, std::string_view reason) {
    return !result && result.error().reason == reason;
}

bool Refused(const std::expected<procedural::ValidatedHostArtifacts, ImportRefusal>& result, std::string_view reason) {
    return !result && result.error().reason == reason;
}

}  // namespace

int RunFilterImportV2Cases(const fs::path& work) {
    const auto templates = evaluator::TemplateLibrary::Load(evaluator::TemplateLibrary::DefaultDirectory());
    const std::vector<std::uint32_t> fixed{0x00000000u, 0x33800000u, 0x3f000000u, 0x3f800000u};
    int checks = 0;
    const auto check = [&](bool okay, const std::string& message) {
        Expect(okay, message);
        ++checks;
    };

    // H: the authored capture verifies; its context hash is the validated readback's.
    Case good = Prepare(work / "import-fixed.uzp", fixed);
    const core::Project scene = Prospective(*good.document->snapshot().project, FilterContext());
    const json::Object hostCapture = good.HostCapture();
    const auto verified = procedural::VerifyHostCapture(*good.store, scene, hostCapture, good.Transport());
    Expect(verified.has_value(), verified ? "" : verified.error().reason + ": " + verified.error().detail);
    check(verified->CaptureContextSha256() == store::ObservationKey(good.receipt.at("readback")),
          "the capture context hash is computed from the validated readback");

    // H refusals, each on a changed artifact.
    const auto refusedHost = [&](const std::string& label, std::string_view reason, const std::function<void(Case&)>& change) {
        Case copy;
        copy.receipt = good.receipt;
        copy.request = good.request;
        copy.scalarExr = good.scalarExr;
        copy.rgbExr = good.rgbExr;
        change(copy);
        const json::Object capture = copy.HostCapture();
        const auto result = procedural::VerifyHostCapture(*good.store, scene, capture, copy.Transport());
        check(Refused(result, reason), label + ": expected " + std::string(reason) +
                                           (result ? std::string(", accepted") : ", got " + result.error().reason + ": " + result.error().detail));
    };
    const auto readback = [](Case& c) -> json::Object& { return std::get<json::Object>(c.receipt.at("readback").data); };
    const auto source = [&](Case& c) -> json::Object& {
        return std::get<json::Object>(std::get<json::Array>(readback(c).at("sources").data)[0].data);
    };
    refusedHost("foreign receipt", procedural::kHostSourceStateMismatch,
                [](Case& c) { c.receipt["project_uuid"] = std::string("6f1c2a3e-0000-4000-8000-0000000000ff"); });
    refusedHost("receipt schema", procedural::kHostCaptureInvalid,
                [](Case& c) { c.receipt["schema"] = std::string("uzpainter/procedural-capture/2"); });
    // A seed other than the observed effective random seed is an invalid receipt on its own.
    refusedHost("receipt signature seed", procedural::kHostCaptureInvalid, [](Case& c) {
        std::get<json::Object>(c.receipt.at("signature").data)["seed"] = std::int64_t{9};
    });
    refusedHost("projection filtering", procedural::kHostCaptureInvalid, [&](Case& c) {
        std::get<json::Object>(readback(c).at("projection").data)["filtering"] = std::string("BilinearHQ");
    });
    refusedHost("active channels", procedural::kHostCaptureInvalid,
                [&](Case& c) { readback(c)["active_channels"] = json::Array{std::string("User0")}; });
    refusedHost("set resolution", procedural::kHostCaptureInvalid, [&](Case& c) {
        std::get<json::Object>(std::get<json::Array>(readback(c).at("sets").data)[0].data)["resolution"] =
            json::Array{std::int64_t{256}, std::int64_t{256}};
    });
    refusedHost("paired sources differ", procedural::kHostCaptureInvalid, [&](Case& c) { source(c)["opacity"] = 0.5; });
    refusedHost("requested override", procedural::kHostCaptureInvalid,
                [](Case& c) { c.request["parameters"] = json::Object{{"amount", 0.25}}; });
    refusedHost("unversioned request", procedural::kHostCaptureInvalid, [](Case& c) {
        c.request["resource"] = std::string("resource://authored/host");
    });
    refusedHost("identity under OCIO", procedural::kHostCaptureInvalid, [](Case& c) {
        std::get<json::Object>(c.receipt.at("identity").data)["OCIO"] = std::string("config.ocio");
    });
    refusedHost("identity colour selection of another type", procedural::kHostCaptureInvalid, [](Case& c) {
        std::get<json::Object>(c.receipt.at("identity").data)["PAINTER_ACE_CONFIG"] = false;
    });
    {
        // Empty strings are Legacy too: the bridge refuses only a truthy selection.
        Case legacy;
        legacy.receipt = good.receipt;
        legacy.request = good.request;
        legacy.scalarExr = good.scalarExr;
        legacy.rgbExr = good.rgbExr;
        auto& identity = std::get<json::Object>(legacy.receipt.at("identity").data);
        identity["OCIO"] = std::string();
        identity["PAINTER_ACE_CONFIG"] = std::string();
        const json::Object capture = legacy.HostCapture();
        check(procedural::VerifyHostCapture(*good.store, scene, capture, legacy.Transport()).has_value(),
              "an identity with empty OCIO and PAINTER_ACE_CONFIG strings is Legacy");
    }
    refusedHost("missing recorder pin", procedural::kHostCaptureInvalid,
                [](Case& c) { std::get<json::Object>(c.receipt.at("recorder").data).erase("painter_side_sha256"); });
    refusedHost("failed export round", procedural::kHostCaptureInvalid, [](Case& c) {
        auto& round = std::get<json::Object>(std::get<json::Array>(c.receipt.at("exports").data)[1].data);
        std::get<json::Object>(round.at("result").data)["status"] = std::string("Error");
    });
    refusedHost("dithered export configuration", procedural::kHostCaptureInvalid, [](Case& c) {
        auto& round = std::get<json::Object>(std::get<json::Array>(c.receipt.at("exports").data)[0].data);
        auto& config = std::get<json::Object>(round.at("config").data);
        auto& parameters = std::get<json::Object>(std::get<json::Object>(std::get<json::Array>(config.at("exportParameters").data)[0].data).at("parameters").data);
        parameters["dithering"] = true;
    });
    refusedHost("files not linked to the artifacts", procedural::kHostCaptureInvalid, [](Case& c) {
        std::get<json::Object>(c.receipt.at("files").data)["export2/user0.exr"] = core::Sha256Hex("another export");
    });
    refusedHost("exports of another raster", procedural::kNativeTransportMismatch, [](Case& c) {
        std::vector<std::uint32_t> other(128 * 128, 0x3f000000u);
        c.scalarExr = Exr(other, 1);
        c.rgbExr = Exr(other, 3);
        auto& files = std::get<json::Object>(c.receipt.at("files").data);
        for (const char* round : {"export1", "export2"}) {
            files[std::string(round) + "/user0.exr"] = core::Sha256Hex(c.scalarExr);
            files[std::string(round) + "/user1.exr"] = core::Sha256Hex(c.rgbExr);
        }
    });
    refusedHost("RGB component differs", procedural::kNativeTransportMismatch, [](Case& c) {
        std::vector<std::uint32_t> other(128 * 128, 0x3f800000u);
        c.rgbExr = Exr(other, 3);
        auto& files = std::get<json::Object>(c.receipt.at("files").data);
        files["export1/user1.exr"] = core::Sha256Hex(c.rgbExr);
        files["export2/user1.exr"] = core::Sha256Hex(c.rgbExr);
    });
    {
        json::Object capture = hostCapture;
        capture["capture_context_sha256"] = core::Sha256Hex("claimed");
        check(Refused(procedural::VerifyHostCapture(*good.store, scene, capture, good.Transport()), procedural::kHostCaptureInvalid),
              "a caller-supplied capture context hash is refused");
        json::Object missing = hostCapture;
        Case empty;
        check(Refused(procedural::VerifyHostCapture(*good.store, scene, missing, empty.Transport()), procedural::kHostCaptureInvalid),
              "an artifact absent from the transport is refused");
        json::Object wrongSize = hostCapture;
        std::get<json::Object>(wrongSize.at("receipt").data)["size_bytes"] = std::int64_t{1};
        check(Refused(procedural::VerifyHostCapture(*good.store, scene, wrongSize, good.Transport()), procedural::kHostCaptureInvalid),
              "an artifact of another size is refused");
        json::Object environment = hostCapture;
        environment["environment"] = good.Ref("snapshot_environment", "authored environment");
        check(Refused(procedural::VerifyHostCapture(*good.store, scene, environment, good.Transport()), procedural::kHostCaptureInvalid),
              "an H environment without its binding is refused");
        environment["environment_binding"] = good.Ref("snapshot_environment_binding", "authored binding");
        check(Refused(procedural::VerifyHostCapture(*good.store, scene, environment, good.Transport()), procedural::kHostCaptureInvalid),
              "an H environment with a binding is refused: no supported representation exists");
    }

    // The H artifacts on their own: no store, target or F. A standalone copy holds only the
    // artifacts; the result carries what the receipt recorded and what the validation computed.
    {
        const auto standalone = [&]() {
            Case copy;
            copy.receipt = good.receipt;
            copy.request = good.request;
            copy.scalarExr = good.scalarExr;
            copy.rgbExr = good.rgbExr;
            return copy;
        };
        Case alone = standalone();
        const json::Object aloneCapture = alone.HostCapture();
        const auto artifacts = procedural::ValidateHostCaptureArtifacts(aloneCapture, alone.Transport());
        Expect(artifacts.has_value(), artifacts ? "" : artifacts.error().reason + ": " + artifacts.error().detail);
        std::string texels;
        for (std::size_t i = 0; i < 128 * 128; ++i) {
            const std::uint32_t bits = fixed[i % fixed.size()];
            texels.append(reinterpret_cast<const char*>(&bits), 4);
        }
        check(alone.store == nullptr && artifacts->CapturedProjectUuid() == good.store->project_uuid() &&
                  artifacts->CapturedRevision() == std::get<std::int64_t>(good.receipt.at("revision").data) &&
                  artifacts->Resource() == std::get<std::string>(good.receipt.at("resource").data),
              "standalone H artifacts validate with the recorded project, revision and resource");
        check(artifacts->Signature() == good.receipt.at("signature") && artifacts->Readback() == good.receipt.at("readback") &&
                  procedural::SignatureJson(artifacts->Request()) == good.receipt.at("signature") &&
                  artifacts->Metadata().typed_effective_parameters && artifacts->Metadata().observed_resource_id,
              "the result keeps the typed signature and readback, the request they name and the /3 metadata");
        check(artifacts->ScalarTexels() == texels && artifacts->ScalarSha256() == core::Sha256Hex(texels),
              "the result owns the decoded scalar raster");
        const json::Object identity = artifacts->Identity();
        const json::Object bound = verified->Identity();
        check(identity.at("signature_sha256") == bound.at("signature_sha256") && identity.at("raster_sha256") == bound.at("raster_sha256") &&
                  identity.at("metadata_sha256") == bound.at("metadata_sha256") &&
                  identity.at("capture_context_sha256") == bound.at("capture_context_sha256") &&
                  artifacts->CaptureContextSha256() == verified->CaptureContextSha256(),
              "the computed identity is the one VerifyHostCapture binds to the destination");

        Case foreignUuid = standalone();
        foreignUuid.receipt["project_uuid"] = std::string("6f1c2a3e-0000-4000-8000-0000000000ff");
        const json::Object foreignCapture = foreignUuid.HostCapture();
        const auto foreignArtifacts = procedural::ValidateHostCaptureArtifacts(foreignCapture, foreignUuid.Transport());
        check(foreignArtifacts && foreignArtifacts->CapturedProjectUuid() == "6f1c2a3e-0000-4000-8000-0000000000ff",
              "standalone validation records the captured project and binds it to no store");

        const auto refusedArtifacts = [&](const std::string& label, std::string_view reason,
                                          const std::function<json::Object(Case&)>& change) {
            Case copy = standalone();
            const json::Object capture = change(copy);
            const auto result = procedural::ValidateHostCaptureArtifacts(capture, copy.Transport());
            check(Refused(result, reason), "standalone " + label + ": expected " + std::string(reason) +
                                               (result ? std::string(", accepted") : ", got " + result.error().reason + ": " + result.error().detail));
        };
        refusedArtifacts("empty project uuid", procedural::kHostCaptureInvalid, [](Case& c) {
            c.receipt["project_uuid"] = std::string();
            return c.HostCapture();
        });
        refusedArtifacts("signature outside the H domain", procedural::kHostCaptureInvalid, [](Case& c) {
            auto& signature = std::get<json::Object>(c.receipt.at("signature").data);
            std::get<json::Object>(signature.at("output").data)["resolution"] = std::int64_t{256};
            return c.HostCapture();
        });
        refusedArtifacts("readback without the observed ResourceID", procedural::kHostCaptureInvalid, [](Case& c) {
            auto& readbackObject = std::get<json::Object>(c.receipt.at("readback").data);
            for (json::Value& item : std::get<json::Array>(readbackObject.at("sources").data)) {
                std::get<json::Object>(item.data).erase("resource_id");
            }
            return c.HostCapture();
        });
        refusedArtifacts("non-finite raster", procedural::kNativeTransportMismatch, [](Case& c) {
            const std::vector<std::uint32_t> infinite(128 * 128, 0x7f800000u);
            c.scalarExr = Exr(infinite, 1);
            c.rgbExr = Exr(infinite, 3);
            auto& files = std::get<json::Object>(c.receipt.at("files").data);
            for (const char* round : {"export1", "export2"}) {
                files[std::string(round) + "/user0.exr"] = core::Sha256Hex(c.scalarExr);
                files[std::string(round) + "/user1.exr"] = core::Sha256Hex(c.rgbExr);
            }
            return c.HostCapture();
        });
        refusedArtifacts("scalar rounds differ", procedural::kNativeTransportMismatch, [](Case& c) {
            const std::string other = Exr(std::vector<std::uint32_t>(128 * 128, 0x3f000000u), 1);
            std::get<json::Object>(c.receipt.at("files").data)["export2/user0.exr"] = core::Sha256Hex(other);
            json::Object capture = c.HostCapture();
            std::get<json::Array>(capture.at("scalar_exports").data)[1] = c.Ref("snapshot_scalar_export", other);
            return capture;
        });
        refusedArtifacts("caller-supplied context hash", procedural::kHostCaptureInvalid, [](Case& c) {
            json::Object capture = c.HostCapture();
            capture["capture_context_sha256"] = core::Sha256Hex("claimed");
            return capture;
        });

        // The signature's seed is the observed `$randomseed` (an integer), or 0 when absent.
        const auto& goodSources = std::get<json::Array>(std::get<json::Object>(good.receipt.at("readback").data).at("sources").data);
        check(!std::get<json::Object>(std::get<json::Object>(goodSources[0].data).at("parameters").data).contains("$randomseed") &&
                  std::get<json::Object>(good.receipt.at("signature").data).at("seed") == json::Value(std::int64_t{0}) &&
                  artifacts.has_value(),
              "an absent effective random seed is the signature's seed 0");
        const auto seeded = [](Case& c, const json::Value& observed, std::int64_t seed) {
            for (json::Value& item : std::get<json::Array>(std::get<json::Object>(c.receipt.at("readback").data).at("sources").data)) {
                std::get<json::Object>(std::get<json::Object>(item.data).at("parameters").data)["$randomseed"] = observed;
            }
            auto& signature = std::get<json::Object>(c.receipt.at("signature").data);
            std::get<json::Object>(signature.at("params").data)["$randomseed"] = observed;
            signature["seed"] = seed;
        };
        {
            Case copy = standalone();
            seeded(copy, json::Value(std::int64_t{-7}), -7);
            const json::Object capture = copy.HostCapture();
            const auto result = procedural::ValidateHostCaptureArtifacts(capture, copy.Transport());
            check(result.has_value(), "an observed integer random seed equal to the signature's seed validates" +
                                          (result ? std::string() : " (" + result.error().reason + ": " + result.error().detail + ")"));
        }
        refusedArtifacts("seed without an observed random seed", procedural::kHostCaptureInvalid, [](Case& c) {
            std::get<json::Object>(c.receipt.at("signature").data)["seed"] = std::int64_t{9};
            return c.HostCapture();
        });
        refusedArtifacts("observed random seed with the default seed", procedural::kHostCaptureInvalid, [&](Case& c) {
            seeded(c, json::Value(std::int64_t{7}), 0);
            return c.HostCapture();
        });
        refusedArtifacts("non-integer observed random seed", procedural::kHostCaptureInvalid, [&](Case& c) {
            seeded(c, json::Value(7.0), 7);
            return c.HostCapture();
        });
    }

    // The bridge's override comparison is Python's: exact integers, an integer and a float only
    // when the float is that integer.
    {
        using procedural::detail::BridgeScalarEquals;
        const std::int64_t big = (std::int64_t{1} << 53) + 1;
        check(!BridgeScalarEquals(json::Value(big), json::Value(9007199254740992.0)), "2^53+1 is not the float 2^53");
        check(BridgeScalarEquals(json::Value(std::int64_t{1} << 53), json::Value(9007199254740992.0)), "2^53 is the float 2^53");
        check(!BridgeScalarEquals(json::Value(big), json::Value(big - 1)), "integers compare exactly");
        check(!BridgeScalarEquals(json::Value(std::numeric_limits<std::int64_t>::max()), json::Value(9223372036854775808.0)),
              "int64 max is not the float 2^63");
        check(BridgeScalarEquals(json::Value(std::numeric_limits<std::int64_t>::min()), json::Value(-9223372036854775808.0)),
              "int64 min is the float -2^63");
        check(BridgeScalarEquals(json::Value(true), json::Value(1.0)) && BridgeScalarEquals(json::Value(std::int64_t{1}), json::Value(1.0)),
              "a boolean is its integer and 1 is 1.0");
        check(BridgeScalarEquals(json::Value(0.5), json::Value(0.5)) && !BridgeScalarEquals(json::Value(0.5), json::Value(0.25)),
              "floats compare by value");
        check(!BridgeScalarEquals(json::Value(std::int64_t{1}), json::Value(std::string("1"))) &&
                  BridgeScalarEquals(json::Value(std::string("a")), json::Value(std::string("a"))),
              "strings equal only strings");
    }

    // The transaction: commit, then a fresh lookup after save and reopen.
    const procedural::VerifiedFilterContext filter = FilterContext();
    const procedural::ImportTarget target = Target(good);
    {
        const auto request = procedural::FilterObservationCommitRequest(*verified, filter, target);
        check(request.idempotency_key == procedural::FilterObservationCommitRequest(*verified, FilterContext(), target).idempotency_key,
              "the same validated inputs give the same request key");
        procedural::ImportTarget later = target;
        later.revision += 1;
        check(procedural::FilterObservationCommitRequest(*verified, filter, later).idempotency_key != request.idempotency_key,
              "the same import at another revision is another request");
        check(procedural::FilterObservationCommitRequest(*verified, FilterContext("Blur", false), target).request_hash() !=
                  request.request_hash(),
              "other observations are another request");
    }
    const auto committed = procedural::CommitFilterObservation(*good.store, *good.document, *verified, filter, target, templates);
    Expect(committed.has_value(), committed ? "" : committed.error().reason + ": " + committed.error().detail);
    check(good.document->revision() == target.revision + 1, "the commit adds one revision");
    const auto found = procedural::ObservedFilter(*good.store, *good.document->snapshot().project, target.filter_uid);
    check(found && found->entry_key == *committed && found->parameters && found->resource_id && found->image_outputs,
          "the committed entry resolves with its three observations");
    const auto replay = procedural::CommitFilterObservation(*good.store, *good.document, *verified, filter, target, templates);
    check(replay && *replay == *committed && good.document->revision() == target.revision + 1,
          "replaying the same request returns its stored outcome without a second insertion" +
              (replay ? std::string() : " (" + replay.error().reason + ": " + replay.error().detail + ")") +
              " at revision " + std::to_string(good.document->revision()));
    {
        const auto notReplayed = [&](const std::string& label, const procedural::VerifiedFilterContext& context,
                                     const procedural::ImportTarget& t, const procedural::VerifiedHostMigration& host) {
            const std::int64_t before = good.document->revision();
            const auto result = procedural::CommitFilterObservation(*good.store, *good.document, host, context, t, templates);
            check(!result && good.document->revision() == before, label + " does not replay the stored outcome");
        };
        notReplayed("other observations", FilterContext("Blur", false), target, *verified);
        notReplayed("another effect", FilterContext("Renamed"), target, *verified);
        procedural::ImportTarget otherUid = target;
        otherUid.filter_uid += 1;
        notReplayed("another target", filter, otherUid, *verified);
        Case recaptured;
        recaptured.receipt = good.receipt;
        recaptured.request = good.request;
        recaptured.scalarExr = good.scalarExr;
        recaptured.rgbExr = good.rgbExr;
        std::get<json::Object>(recaptured.receipt.at("recorder").data)["bridge_sha256"] = core::Sha256Hex("another bridge");
        const json::Object otherCapture = recaptured.HostCapture();
        const auto otherHost = procedural::VerifyHostCapture(*good.store, scene, otherCapture, recaptured.Transport());
        Expect(otherHost.has_value(), "the capture of another recorder verifies");
        notReplayed("another H capture", filter, target, *otherHost);
    }
    good.store->Save(*good.document);
    good.document.reset();
    good.store->Close();
    good.store.reset();
    {
        auto reopened = store::ProjectStore::Open(work / "import-fixed.uzp");
        const auto fresh = procedural::ObservedFilter(*reopened.store, reopened.state.project, target.filter_uid);
        check(reopened.report.ok() && fresh && fresh->entry_key == *committed, "after save and reopen a fresh lookup serves the entry");
        reopened.store->Close();
    }

    // An exact retry returns the entry its commit returned, whatever the Filter is bound to now:
    // after the binding is removed, and after another import B binds the same Filter uid.
    {
        Case retry = Prepare(work / "import-retry.uzp", fixed);
        const core::Project retryScene = Prospective(*retry.document->snapshot().project, FilterContext());
        const auto retryHost = procedural::VerifyHostCapture(*retry.store, retryScene, retry.HostCapture(), retry.Transport());
        Expect(retryHost.has_value(), "the retry authored capture verifies");
        const procedural::ImportTarget a = Target(retry);
        const auto keyA = procedural::CommitFilterObservation(*retry.store, *retry.document, *retryHost, filter, a, templates);
        Expect(keyA.has_value(), keyA ? "" : keyA.error().reason + ": " + keyA.error().detail);
        // Remove the Filter and its observations, handing its uid out again.
        const auto unbound = retry.store->Submit(
            *retry.document, {"filter-import-v2-test", json::Object{}, "unbind", retry.document->revision()}, [&](core::Edit& edit) {
                core::Project& project = edit.project();
                project.texture_sets[0].stacks[0].root_layers[0].content_effects.clear();
                project.extra.erase(std::string(store::kFilterObservationsKey));
                project.next_id = a.filter_uid;
            });
        Expect(unbound.result && unbound.result->status == core::ResultStatus::committed, "the unbinding commits");
        const auto retried = [&](const std::string& label) {
            const std::int64_t before = retry.document->revision();
            const auto result = procedural::CommitFilterObservation(*retry.store, *retry.document, *retryHost, filter, a, templates);
            check(result && *result == *keyA && retry.document->revision() == before,
                  "retrying A " + label + " returns A's entry without a revision" +
                      (result ? std::string() : " (" + result.error().reason + ": " + result.error().detail + ")"));
        };
        retried("after its binding is removed");
        check(!retry.document->snapshot().project->extra.contains(std::string(store::kFilterObservationsKey)),
              "the retry after the removal inserts nothing");
        const procedural::ImportTarget b = Target(retry);
        const auto keyB =
            procedural::CommitFilterObservation(*retry.store, *retry.document, *retryHost, FilterContext("Blur", false), b, templates);
        check(keyB && *keyB != *keyA && b.filter_uid == a.filter_uid,
              "import B with other observations binds the same Filter uid to another entry" +
                  (keyB ? std::string() : " (" + keyB.error().reason + ": " + keyB.error().detail + ")"));
        retried("after B binds the same uid");
        const auto bound = procedural::ObservedFilter(*retry.store, *retry.document->snapshot().project, a.filter_uid);
        check(keyB && bound && bound->entry_key == *keyB, "the retry of A leaves the Filter bound to B");
    }

    // Refused transactions leave no revision, operation record, census change or namespace.
    const auto refusedCommit = [&](const std::string& label, std::string_view reason, Case& c,
                                   const procedural::VerifiedHostMigration& host, procedural::ImportTarget t) {
        const std::int64_t before = c.document->revision();
        const core::Project prior = *c.document->snapshot().project;
        const std::string census = c.store->ReadObservationInventory(prior).Sha256();
        const auto result = procedural::CommitFilterObservation(*c.store, *c.document, host, filter, t, templates);
        const core::Project after = *c.document->snapshot().project;
        check(!result && result.error().reason == reason && c.document->revision() == before &&
                  c.store->OperationsAfter(before).records.empty() &&
                  c.store->ReadObservationInventory(after).Sha256() == census &&
                  !after.extra.contains(std::string(store::kFilterObservationsKey)),
              label + ": expected " + std::string(reason) + (result ? std::string(", committed") : ", got " + result.error().reason));
    };
    Case other = Prepare(work / "import-refusals.uzp", fixed);
    const core::Project otherScene = Prospective(*other.document->snapshot().project, FilterContext());
    const auto otherHost = procedural::VerifyHostCapture(*other.store, otherScene, other.HostCapture(), other.Transport());
    Expect(otherHost.has_value(), "the second authored capture verifies");
    procedural::ImportTarget wrongBase = Target(other);
    wrongBase.base_projection_sha256 = core::Sha256Hex("another base");
    refusedCommit("another base projection", procedural::kStaleProspectiveView, other, *otherHost, wrongBase);
    procedural::ImportTarget wrongId = Target(other);
    wrongId.filter_uid += 1;
    refusedCommit("not the next id", procedural::kTargetContextUnrepresentable, other, *otherHost, wrongId);
    procedural::ImportTarget wrongRevision = Target(other);
    wrongRevision.revision += 1;
    refusedCommit("a stale revision", procedural::kStaleProspectiveView, other, *otherHost, wrongRevision);

    // A capture verified on raster B1 never commits over another fixed raster B2 with the same
    // uuid and signature, nor into another store.
    Case rewritten = Prepare(work / "import-raster-b2.uzp", {0x3f800000u});
    refusedCommit("a capture of another raster", procedural::kHostSourceStateMismatch, rewritten, *otherHost, Target(rewritten));
    Case foreign = Prepare(work / "import-foreign.uzp", fixed, "6f1c2a3e-0000-4000-8000-0000000a3634");
    refusedCommit("a capture of another store", procedural::kHostSourceStateMismatch, foreign, *otherHost, Target(foreign));

    // A mixed raster (-0 and 2^-26 are not fixed points): the H capture verifies (finite, exact
    // exports) and the native proof refuses the commit.
    Case mixed = Prepare(work / "import-mixed.uzp", {0x00000000u, 0x80000000u, 0x32800000u, 0x33800000u, 0x3f000000u, 0x3f800000u});
    const core::Project mixedScene = Prospective(*mixed.document->snapshot().project, FilterContext());
    const auto mixedHost = procedural::VerifyHostCapture(*mixed.store, mixedScene, mixed.HostCapture(), mixed.Transport());
    Expect(mixedHost.has_value(), "the mixed authored capture verifies");
    refusedCommit("a raster that is not a fixed point", procedural::kFrozenRasterNotFixedPoint, mixed, *mixedHost, Target(mixed));

    // The post-proof recheck: a same-version staged rewrite of a plane, a changed projection and a
    // moved revision are each refused.
    {
        Case plain = Prepare(work / "import-recheck.uzp", fixed);
        bool staleCensus = false;
        bool staleProjection = false;
        bool staleRevision = false;
        const auto outcome = plain.store->Submit(
            *plain.document, {"filter-import-v2-test", json::Object{}, "recheck", plain.document->revision()},
            [&](core::Edit& edit) {
                core::Project& project = edit.project();
                const core::Id paint = project.texture_sets[0].stacks[0].root_layers[1].uid;
                const core::Id planeId =
                    plain.store->CreatePlane(edit, store::PlaneSpec{paint, core::ChannelType::User0, 1001, core::ChannelFormat::L32F, 128, 128});
                plain.store->WritePlane(edit, planeId, store::PlaneImage{128, 128, core::ChannelFormat::L32F, std::string(128 * 128 * 4, '\x01')});
                json::Value projection = core::ProjectToJson(project);
                std::get<json::Object>(projection.data).erase(std::string(store::kFilterObservationsKey));
                const json::Object context{{"project", projection}, {"inventory", plain.store->ReadObservationInventory(project).ToJson()}};
                const std::int64_t revision = plain.document->revision();
                staleRevision = procedural::RecheckProspectiveView(*plain.store, *plain.document, project, context, revision + 1).has_value();
                // The transaction rewrites its staged version under the same id; the rebinding also
                // changes the projection, so the census leg is checked against the current projection
                // with the census taken before the rewrite.
                plain.store->WritePlane(edit, planeId, store::PlaneImage{128, 128, core::ChannelFormat::L32F, std::string(128 * 128 * 4, '\x02')});
                json::Value rewritten = core::ProjectToJson(project);
                std::get<json::Object>(rewritten.data).erase(std::string(store::kFilterObservationsKey));
                const json::Object sameProjection{{"project", rewritten}, {"inventory", context.at("inventory")}};
                const auto census = procedural::RecheckProspectiveView(*plain.store, *plain.document, project, sameProjection, revision);
                staleCensus = census.has_value() && census->detail == "the census changed";
                project.texture_sets[0].stacks[0].root_layers[0].name = "renamed";
                const auto renamed = procedural::RecheckProspectiveView(*plain.store, *plain.document, project, sameProjection, revision);
                staleProjection = renamed.has_value() && renamed->detail == "the prospective projection changed";
                throw std::runtime_error("roll the recheck transaction back");
            });
        check(!(outcome.result && outcome.result->status == core::ResultStatus::committed) && staleRevision && staleCensus &&
                  staleProjection,
              "the recheck refuses a moved revision, a same-version census change and a changed projection (revision " +
                  std::to_string(staleRevision) + ", census " + std::to_string(staleCensus) + ", projection " +
                  std::to_string(staleProjection) + ")");
    }

    std::cout << "FILTER_IMPORT_V2: " << json::WriteCanonical(json::Object{{"checks", checks}}) << "\n";
    return 0;
}
