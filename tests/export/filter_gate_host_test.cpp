// Authored snapshot admissions only: no Painter, private store or policy override.
#include <algorithm>
#include <fstream>
#include <functional>
#include <iostream>
#include <iterator>
#include <type_traits>

#include "export/exr_writer.h"
#include "filter_gate_test_support.h"
#include "procedural/filter_gate_host.h"
#include "procedural/snapshot_source.h"

static_assert(!std::is_default_constructible_v<uzp::procedural::AdmittedHostCapture>);

namespace {
using namespace uzp;
using namespace uzp::filter_gate_test;
constexpr std::string_view kPolicySha = "17ea078d57d88eeb1759a8010d3b304afc3a8a7192d4baf9ac71847e68cdf4ce";
constexpr std::string_view kBridge = "ddfcdae4ac03d2a7981fa772b1af7ca2712f4e70e726a35b2808eb02d7011d5f";
constexpr std::string_view kPainter = "625323d83cb6e7ff7878518861412dbf5c7f7cf0872435f154da1303870bd44d";

std::string Read(const fs::path& path) {
    std::ifstream file(path, std::ios::binary); Require(bool(file), "authored public fixture present");
    return {std::istreambuf_iterator<char>(file), std::istreambuf_iterator<char>()};
}
std::string Digest(const json::Value& value) { return core::Sha256Hex(json::WriteCanonical(value)); }

json::Object Readback() {
    const json::Object source{
        {"resource", fx::kHostUrl}, {"inputs", json::Array{}}, {"outputs", json::Array{"scalar"}},
        {"active_output", "scalar"}, {"opacity", 1}, {"blending", "Normal"},
        {"resolution", json::Object{{"mode", "Auto"}, {"log2_offset", 0}}},
        {"resource_id", json::Object{{"url", fx::kHostUrl}, {"context", "authored"}, {"name", "host"}, {"version", "1"}}},
        {"parameters", json::Object{{"amount", 0.5}}}};
    return {
        {"channel_formats", json::Object{{"User0", "L32F"}, {"User1", "RGB32F"}}},
        {"source_mode", "Split"}, {"projection_mode", "UV"}, {"active_channels", json::Array{"User0", "User1"}},
        {"projection", json::Object{{"filtering", "Nearest"}, {"wrapping", "RepeatNone"}, {"scale_mode", "Factors"},
                                    {"scale", json::Array{1, 1}}, {"rotation", 0}, {"offset", json::Array{0, 0}}}},
        {"isolated_tree", json::Object{{"roots", json::Array{7}}, {"fill", 7}, {"visible", true}, {"mask", false},
                                       {"content_effects", json::Array{}}, {"mask_effects", json::Array{}}}},
        {"sets", json::Array{json::Object{{"name", "uzp_plane"}, {"resolution", json::Array{128, 128}}, {"has_uv_tiles", false}}}},
        {"sources", json::Array{source, source}}};
}

json::Object ExportRound(int round) {
    const std::string directory = "C:/authored/export" + std::to_string(round);
    json::Array maps;
    for (const auto& [name, channels] : {std::pair{"user0", "L"}, std::pair{"user1", "RGB"}}) {
        json::Array list;
        for (const char* channel = channels; *channel; ++channel) {
            list.push_back(json::Object{{"destChannel", std::string(1, *channel)}, {"srcChannel", std::string(1, *channel)},
                                        {"srcMapType", "documentMap"}, {"srcMapName", name}});
        }
        maps.push_back(json::Object{{"fileName", name}, {"channels", std::move(list)}});
    }
    return {
        {"config", json::Object{
            {"exportPath", directory}, {"exportShaderParams", false}, {"defaultExportPreset", "uzp_snapshot"},
            {"exportPresets", json::Array{json::Object{{"name", "uzp_snapshot"}, {"maps", maps}}}},
            {"exportList", json::Array{json::Object{{"rootPath", "uzp_plane"}}}},
            {"exportParameters", json::Array{json::Object{{"parameters", json::Object{
                {"fileFormat", "exr"}, {"bitDepth", "32f"}, {"dithering", false}, {"paddingAlgorithm", "passthrough"}}}}}}}},
        {"result", json::Object{{"status", "Success"}, {"message", ""},
                                 {"files", json::Array{directory + "/user0.exr", directory + "/user1.exr"}}}}};
}

struct HostFixture {
    json::Object receipt, request, host, slots, admission;
    std::map<std::string, std::string, std::less<>> blobs;
    std::string scalar, rgb, capture, policy;
    bool write_admission = true, write_policy = true;
    std::optional<std::string> admission_bytes;

    HostFixture() {
        policy = Read(fs::path(__FILE__).parent_path().parent_path().parent_path() / "parity/snapshot-producer-policy-v1.json");
        Require(core::Sha256Hex(policy) == kPolicySha, "public approved policy stays pinned");
        fx::SceneIds ids;
        const auto project = fx::Scene(store::ObservationPin(Digest(fx::FilterDescriptor())), fx::PlaneObj().size(), ids);
        const auto& set = project.texture_sets[0]; const auto& fill = set.stacks[0].root_layers[0];
        const auto& source = std::get<core::ProceduralSource>(fill.fill->sources.at(core::ChannelType::User0).value);
        const auto nativeRequest = procedural::SnapshotFillRequest(project, set, core::ChannelType::User0,
            core::ChannelFormat::L32F, *fill.fill, source.ref, fill.uid, false);
        Require(nativeRequest.has_value(), "authored snapshot request");
        const auto exr = [](std::uint32_t channels) {
            exporter::ExrImage image{128, 128, channels, {}, false};
            image.values.assign(128 * 128 * channels, 0.5f); return exporter::EncodeExr(image);
        };
        scalar = exr(1); rgb = exr(3);
        request = {{"resource", fx::kHostUrl}, {"parameters", json::Object{{"amount", 0.5}}}};
        receipt = {
            {"schema", "uzpainter/procedural-capture/1"},
            {"recorder", json::Object{{"bridge_sha256", kBridge}, {"painter_side_sha256", kPainter}}},
            {"identity", json::Object{{"pid", 4242}, {"version", "12.2.0"}, {"version_info", json::Array{12, 2, 0}},
                                       {"OCIO", nullptr}, {"PAINTER_ACE_CONFIG", nullptr}, {"project_open", false}, {"mesh", nullptr}}},
            {"resource", fx::kHostUrl}, {"readback", Readback()}, {"exports", json::Array{ExportRound(1), ExportRound(2)}},
            {"project_uuid", "6f1c2a3e-0000-4000-8000-0000000a3633"}, {"revision", 0},
            {"signature", procedural::SignatureJson(*nativeRequest)},
            {"files", json::Object{{"export1/user0.exr", core::Sha256Hex(scalar)}, {"export2/user0.exr", core::Sha256Hex(scalar)},
                                    {"export1/user1.exr", core::Sha256Hex(rgb)}, {"export2/user1.exr", core::Sha256Hex(rgb)}}}};
        Refresh();
    }

    void Refresh() {
        blobs.clear();
        const auto ref = [&](std::string_view kind, const std::string& bytes) {
            const auto sha = core::Sha256Hex(bytes); blobs[sha] = bytes;
            return json::Object{{"kind", kind}, {"sha256", sha}, {"size_bytes", static_cast<std::int64_t>(bytes.size())}};
        };
        host = {{"protocol", "paired-scalar-rgb"}, {"receipt", ref("snapshot_receipt", json::WriteCanonical(receipt))},
                {"request", ref("snapshot_request", json::WriteCanonical(request))}, {"environment", nullptr}, {"environment_binding", nullptr},
                {"scalar_exports", json::Array{ref("snapshot_scalar_export", scalar), ref("snapshot_scalar_export", scalar)}},
                {"rgb_exports", json::Array{ref("snapshot_rgb_export", rgb), ref("snapshot_rgb_export", rgb)}}};
        slots = host; slots.erase("protocol");
        Obj(slots, "receipt")["record_id"] = "receipt"; Obj(slots, "request")["record_id"] = "request";
        for (const auto role : {"scalar", "rgb"}) {
            auto& rows = Arr(slots, std::string(role) + "_exports");
            for (std::size_t i = 0; i < rows.size(); ++i) Obj(rows[i])["record_id"] = "r" + std::to_string(i + 1) + "-" + role;
        }
        capture = Digest(json::Object{{"protocol", "paired-scalar-rgb"}, {"artifacts", slots}});
        const auto validated = procedural::ValidateHostCaptureArtifacts(host, [&](std::string_view sha) -> std::optional<std::string> {
            const auto found = blobs.find(sha); return found == blobs.end() ? std::nullopt : std::optional<std::string>(found->second);
        });
        if (admission.empty()) Require(validated.has_value(), validated ? "" : validated.error().detail);
        if (validated) {
            admission["validation"] = json::Object{
                {"validator_revision", "uzpainter/snapshot-capture-validator/1"},
                {"validator_code_sha256", core::Sha256Hex("authored validator code")},
                {"validator_binary_sha256", core::Sha256Hex("authored validator binary")},
                {"signature_sha256", validated->Identity().at("signature_sha256")},
                {"capture_context_sha256", validated->CaptureContextSha256()}, {"scalar_raster_sha256", validated->ScalarSha256()}};
        }
        admission["schema"] = "uzpainter/parity/snapshot-capture-admission/1";
        admission["protocol"] = "paired-scalar-rgb"; admission["capture_id"] = capture;
        admission["producer_policy"] = json::Object{{"sha256", kPolicySha}, {"revision", 1}};
        admission["artifacts"] = slots;
        admission["provenance"] = json::Object{{"basis", "owner_local_submission"}, {"execution_attestation", "none"}};
        admission["admitted_at"] = "2026-10-26T12:34:56.123456+00:00";
    }

    fs::path AdmissionPath(const fs::path& root) const { return root / "snapshot-captures" / capture / (std::string(kPolicySha) + ".json"); }
    fs::path PolicyPath(const fs::path& root) const { return root / "snapshot-producer-policies" / (std::string(kPolicySha) + ".json"); }
    void Store(const fs::path& root) const {
        WriteFile(root / "store.json", json::WriteCanonical(json::Object{{"schema", "uzpainter/parity/store/1"}, {"hash", "sha256"}}));
        if (write_admission) WriteFile(AdmissionPath(root), admission_bytes.value_or(json::WriteCanonical(admission)));
        if (write_policy) WriteFile(PolicyPath(root), policy);
        for (const auto& [sha, bytes] : blobs) WriteFile(root / "blobs" / sha.substr(0, 2) / sha, bytes);
    }
};
}  // namespace

int RunFilterGateHostCases(const std::filesystem::path& work) {
    HostFixture base;
    int checks = 0;
    const auto run = [&](const HostFixture& fixture, const std::string& code, int blobCount,
                         const std::function<void(std::string_view, const fs::path&)>& change = {}) {
        const auto root = work / ("h" + std::to_string(checks)); fixture.Store(root);
        auto reader = procedural::OracleStoreReader::Open(root, work / "unused-registry.json");
        Require(reader.has_value(), "authored snapshot store opens");
        std::vector<std::string> reads;
        procedural::FilterGateTestAccess::Observe(*reader, [&](std::string_view what) {
            reads.emplace_back(what); if (change) change(what, root);
        });
        const auto admitted = procedural::AdmitHostCapture(fixture.host, *reader);
        Require(static_cast<int>(std::count(reads.begin(), reads.end(), "blob")) == blobCount, code + " read ordering");
        if (code.empty()) {
            Require(admitted.has_value(), admitted ? "" : admitted.error().detail);
            Require(reads.size() == 10 && reads[0] == "snapshot-admission" && reads[1] == "snapshot-policy" &&
                    reads[8] == "snapshot-admission" && reads[9] == "snapshot-policy", "admission and policy surround all blobs");
            Require(admitted->Identity().at("capture_id") == json::Value(fixture.capture), "derived capture ID");
            Require(admitted->Artifacts().CapturedProjectUuid() == "6f1c2a3e-0000-4000-8000-0000000a3633", "preserve H UUID");
            Require(admitted->Artifacts().CapturedRevision() == 0 && !admitted->Bytes(core::Sha256Hex("unlisted")), "owned H evidence only");
        } else Require(!admitted && admitted.error().detail == code, code);
        ++checks;
    };
    run(base, "", 6);
    const auto refusal = [&](const std::string& code, int blobs, const std::function<void(HostFixture&)>& change) {
        auto fixture = base; change(fixture); run(fixture, code, blobs);
    };
    refusal("H_ADMISSION_UNAVAILABLE", 0, [](auto& c) { c.write_admission = false; });
    refusal("H_POLICY_UNAVAILABLE", 0, [](auto& c) { c.write_policy = false; });
    refusal("H_POLICY_INVALID", 0, [](auto& c) { c.policy += "\n"; });
    refusal("H_ADMISSION_INVALID", 0, [](auto& c) { c.admission["extra"] = true; });
    refusal("H_ADMISSION_INVALID", 0, [](auto& c) { c.admission["capture_id"] = std::string(64, '0'); });
    refusal("H_ADMISSION_INVALID", 0, [](auto& c) { Obj(c.admission, "producer_policy")["revision"] = true; });
    refusal("H_ADMISSION_INVALID", 0, [](auto& c) { Obj(c.admission, "producer_policy")["sha256"] = std::string(64, '0'); });
    refusal("H_ADMISSION_INVALID", 0, [](auto& c) { Obj(c.admission, "provenance")["execution_attestation"] = "trusted"; });
    refusal("H_ADMISSION_INVALID", 0, [](auto& c) { c.admission["admitted_at"] = "2026-02-30T12:34:56Z"; });
    refusal("H_ADMISSION_INVALID", 0, [](auto& c) { c.admission["admitted_at"] = "2026-10-26T12:34:56+01:00"; });
    refusal("H_ADMISSION_INVALID", 0, [](auto& c) { Obj(Obj(c.admission, "artifacts"), "receipt")["record_id"] = "request"; });
    refusal("H_ADMISSION_INVALID", 0, [](auto& c) { Obj(c.host, "receipt")["record_id"] = "receipt"; });
    refusal("H_ADMISSION_INVALID", 0, [](auto& c) { Obj(c.host, "receipt")["size_bytes"] = true; });
    refusal("H_ADMISSION_INVALID", 0, [](auto& c) { Obj(Arr(c.host, "scalar_exports")[1])["size_bytes"] = 1; });
    refusal("H_ADMISSION_INVALID", 0, [](auto& c) { c.host["environment"] = json::Object{}; });
    refusal("H_ADMISSION_INVALID", 0, [](auto& c) { c.admission_bytes = "{\"schema\":1,\"schema\":2}"; });
    refusal("H_PRODUCER_UNAPPROVED", 1, [](auto& c) { Obj(c.receipt, "recorder")["bridge_sha256"] = std::string(64, '0'); c.Refresh(); });
    refusal("H_ARTIFACT_UNAVAILABLE", 1, [](auto& c) { c.blobs[std::get<std::string>(Obj(c.host, "receipt").at("sha256").data)] += "x"; });
    refusal("H_ARTIFACT_INVALID", 6, [](auto& c) { Obj(c.receipt, "identity")["project_open"] = true; c.Refresh(); });
    refusal("H_VALIDATION_MISMATCH", 6, [](auto& c) { Obj(c.admission, "validation")["signature_sha256"] = std::string(64, '0'); });
    refusal("H_VALIDATION_MISMATCH", 6, [](auto& c) { Obj(c.admission, "validation")["capture_context_sha256"] = std::string(64, '0'); });
    refusal("H_VALIDATION_MISMATCH", 6, [](auto& c) { Obj(c.admission, "validation")["scalar_raster_sha256"] = std::string(64, '0'); });
    run(base, "H_ADMISSION_CHANGED", 6, [&](std::string_view what, const fs::path& root) {
        if (what == "blob") WriteFile(base.AdmissionPath(root), json::WriteCanonical(base.admission) + "\n");
    });
    run(base, "H_ADMISSION_CHANGED", 6, [&](std::string_view what, const fs::path& root) {
        if (what == "blob") WriteFile(base.PolicyPath(root), base.policy + "\n");
    });
    std::cout << "FILTER_GATE_HOST: " << json::WriteCanonical(json::Object{{"checks", checks}}) << '\n';
    return 0;
}
