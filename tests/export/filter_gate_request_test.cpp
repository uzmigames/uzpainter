// Pure authored command parsing and replay identity: no store or artifact reads.
#include <functional>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <type_traits>

#include "procedural/filter_gate_request.h"
#include "uzp_core/manifest/sha256.h"

static_assert(!std::is_default_constructible_v<uzp::procedural::ParsedFilterImportRequest>);

namespace {
using namespace uzp;
namespace json = core::json;
json::Object& Object(json::Object& value, const std::string& key) { return std::get<json::Object>(value.at(key).data); }
json::Array& Array(json::Object& value, const std::string& key) { return std::get<json::Array>(value.at(key).data); }
std::string Digest(const json::Value& value) { return core::Sha256Hex(json::WriteCanonical(value)); }

json::Object Payload() {
    const auto ref = [](std::string_view kind) {
        return json::Object{{"kind", kind}, {"sha256", core::Sha256Hex(kind)}, {"size_bytes", 42}};
    };
    return {
        {"schema", "uzpainter/filter-observation-v2-import/1"}, {"expected_base_revision", 7},
        {"manifest", ref("filter_manifest")},
        {"host", json::Object{
            {"protocol", "paired-scalar-rgb"}, {"receipt", ref("snapshot_receipt")}, {"request", ref("snapshot_request")},
            {"environment", nullptr}, {"environment_binding", nullptr},
            {"scalar_exports", json::Array{ref("snapshot_scalar_export"), ref("snapshot_scalar_export")}},
            {"rgb_exports", json::Array{ref("snapshot_rgb_export"), ref("snapshot_rgb_export")}}}}};
}
}  // namespace

int RunFilterGateRequestCases() {
    int checks = 0;
    const auto check = [&](bool condition, std::string_view label) {
        if (!condition) throw std::runtime_error(std::string(label));
        ++checks;
    };
    const auto payload = Payload();
    const auto parsed = procedural::ParseFilterImportRequest(json::WriteCanonical(payload));
    check(parsed.has_value(), "closed authored payload parses");
    check(parsed->ExpectedBaseRevision() == 7 && parsed->PayloadSha256() == Digest(payload), "original revision and typed payload hash");
    check(json::WriteCanonical(parsed->HostCapture()) == json::WriteCanonical(payload.at("host")) &&
          json::WriteCanonical(parsed->ManifestRef()) == json::WriteCanonical(payload.at("manifest")), "preserve payload references");
    const auto request = parsed->MutationRequestFor("authored-project");
    const json::Object arguments{{"payload_sha256", Digest(payload)}, {"project_uuid", "authored-project"}, {"expected_base_revision", 7}};
    check(request.tool == "filter-observation-commit-v2" && request.expected_revision == 7 &&
          json::WriteCanonical(request.arguments) == json::WriteCanonical(arguments), "stable command request fields");
    check(request.idempotency_key == "filter-observation-commit-v2:" + Digest(arguments) &&
          request.request_hash() == core::RequestHash("filter-observation-commit-v2", arguments), "exact operation identity");
    const std::string reordered = " {\n\"host\":" + json::WriteCanonical(payload.at("host")) +
        ",\"manifest\":" + json::WriteCanonical(payload.at("manifest")) +
        ",\"expected_base_revision\":7,\"schema\":\"uzpainter/filter-observation-v2-import/1\"\n}\n";
    const auto equivalent = procedural::ParseFilterImportRequest(reordered);
    check(equivalent && equivalent->PayloadSha256() == parsed->PayloadSha256(), "whitespace and key ordering preserve payload identity");
    check(equivalent->MutationRequestFor("authored-project").idempotency_key == request.idempotency_key &&
          equivalent->MutationRequestFor("authored-project").request_hash() == request.request_hash(), "equivalent payload replays same operation");
    check(parsed->MutationRequestFor("other-project").idempotency_key != request.idempotency_key &&
          parsed->MutationRequestFor("other-project").request_hash() != request.request_hash(), "operation is project scoped");

    const auto refuseText = [&](const std::string& text) {
        const auto result = procedural::ParseFilterImportRequest(text);
        check(!result && result.error().reason == "FILTER_IMPORT_REQUEST_INVALID" &&
              result.error().detail == "FILTER_IMPORT_REQUEST_SCHEMA", "closed parser refusal never echoes supplied values");
    };
    const auto refuse = [&](const std::function<void(json::Object&)>& mutate) {
        auto value = payload; mutate(value); refuseText(json::WriteCanonical(value));
    };
    refuse([](auto& p) { p["extra"] = true; });
    refuse([](auto& p) { p.erase("manifest"); });
    refuse([](auto& p) { p["schema"] = "uzpainter/filter-observation-import/2"; });
    refuse([](auto& p) { p["expected_base_revision"] = false; });
    refuse([](auto& p) { p["expected_base_revision"] = 7.0; });
    refuse([](auto& p) { p["expected_base_revision"] = -1; });
    refuse([](auto& p) { p["expected_base_revision"] = "7"; });
    refuse([](auto& p) { p["expected_base_revision"] = nullptr; });
    refuse([](auto& p) { Object(p, "manifest")["size_bytes"] = false; });
    refuse([](auto& p) { Object(p, "manifest")["size_bytes"] = 42.0; });
    refuse([](auto& p) { Object(p, "manifest")["size_bytes"] = -0.0; });
    refuse([](auto& p) { Object(p, "manifest")["size_bytes"] = -1; });
    refuse([](auto& p) { Object(p, "manifest")["kind"] = "snapshot_receipt"; });
    refuse([](auto& p) { Object(p, "manifest")["sha256"] = std::string(64, 'A'); });
    refuse([](auto& p) { Object(p, "manifest")["sha256"] = "../private"; });
    refuse([](auto& p) { Object(p, "manifest")["record_id"] = "external"; });
    refuse([](auto& p) { Object(p, "host")["extra"] = true; });
    refuse([](auto& p) { Object(p, "host")["protocol"] = "scalar-only"; });
    refuse([](auto& p) { Object(p, "host")["environment"] = json::Object{}; });
    refuse([](auto& p) { Object(p, "host")["environment_binding"] = json::Object{}; });
    refuse([](auto& p) { Object(Object(p, "host"), "receipt")["size_bytes"] = true; });
    refuse([](auto& p) { Object(Object(p, "host"), "request")["size_bytes"] = 1.0; });
    refuse([](auto& p) { Object(Object(p, "host"), "receipt")["record_id"] = "receipt"; });
    refuse([](auto& p) { Array(Object(p, "host"), "scalar_exports").pop_back(); });
    refuse([](auto& p) { auto& rows = Array(Object(p, "host"), "rgb_exports"); rows.push_back(rows[0]); });
    refuse([](auto& p) { std::get<json::Object>(Array(Object(p, "host"), "scalar_exports")[0].data)["size_bytes"] = false; });
    refuse([](auto& p) { std::get<json::Object>(Array(Object(p, "host"), "rgb_exports")[1].data)["kind"] = "snapshot_scalar_export"; });
    refuse([](auto& p) { p["host"] = json::Array{}; });
    refuseText("{\"schema\":1,\"schema\":2}");
    refuseText("[]");
    refuseText("{\"expected_base_revision\":9223372036854775808}");
    refuseText("{\"expected_base_revision\":NaN}");

    for (const auto revision : {std::int64_t{0}, std::numeric_limits<std::int64_t>::max()}) {
        auto value = payload; value["expected_base_revision"] = revision;
        const auto result = procedural::ParseFilterImportRequest(json::WriteCanonical(value));
        check(result && result->ExpectedBaseRevision() == revision, "full nonnegative int64 revision domain");
    }
    const auto changed = [&](const std::function<void(json::Object&)>& mutate) {
        auto value = payload; mutate(value);
        const auto result = procedural::ParseFilterImportRequest(json::WriteCanonical(value));
        check(result && result->PayloadSha256() != parsed->PayloadSha256() &&
              result->MutationRequestFor("authored-project").idempotency_key != request.idempotency_key &&
              result->MutationRequestFor("authored-project").request_hash() != request.request_hash(), "material input changes replay identity");
    };
    changed([](auto& p) { p["expected_base_revision"] = 8; });
    changed([](auto& p) { Object(p, "manifest")["sha256"] = core::Sha256Hex("another manifest"); });
    changed([](auto& p) { Object(Object(p, "host"), "receipt")["sha256"] = core::Sha256Hex("another receipt"); });
    changed([](auto& p) { Object(Object(p, "host"), "request")["size_bytes"] = 43; });
    std::cout << "FILTER_GATE_REQUEST: " << json::WriteCanonical(json::Object{{"checks", checks}}) << '\n';
    return 0;
}
