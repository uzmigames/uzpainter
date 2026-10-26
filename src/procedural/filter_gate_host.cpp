#include "procedural/filter_gate_host.h"

#include <chrono>
#include <regex>
#include <set>
#include <stdexcept>
#include <utility>
#include <vector>

#include "uzp_core/manifest/sha256.h"

namespace uzp::procedural {
namespace {

using core::json::Array;
using core::json::Object;
using core::json::Value;
using Unexpected = std::expected<AdmittedHostCapture, ImportRefusal>::unexpected_type;
constexpr std::string_view kProtocol = "paired-scalar-rgb";
constexpr std::string_view kPolicySha = "17ea078d57d88eeb1759a8010d3b304afc3a8a7192d4baf9ac71847e68cdf4ce";
constexpr std::string_view kValidator = "uzpainter/snapshot-capture-validator/1";

#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wc23-extensions"
constexpr unsigned char kPolicyBytes[] = {
#embed "../../parity/snapshot-producer-policy-v1.json"
};
#pragma clang diagnostic pop

struct HostAdmissionRefused { std::string_view code; };
void Require(bool condition, std::string_view code = "H_ADMISSION_INVALID") {
    if (!condition) throw HostAdmissionRefused{code};
}
const Object& Obj(const Value& value) {
    Require(value.IsObject()); return std::get<Object>(value.data);
}
const Array& Arr(const Value& value) {
    Require(value.IsArray()); return std::get<Array>(value.data);
}
const std::string& Text(const Value& value) {
    Require(value.IsString()); return std::get<std::string>(value.data);
}
const Value& At(const Object& object, std::string_view key) {
    const auto found = object.find(key); Require(found != object.end()); return found->second;
}
void Closed(const Object& object, std::initializer_list<std::string_view> fields) {
    Require(object.size() == fields.size());
    for (const auto field : fields) Require(object.contains(field));
}
bool Same(const Value& a, const Value& b) {
    return core::json::WriteCanonical(a) == core::json::WriteCanonical(b);
}
void Hash(const Value& value) { Require(value.IsString() && core::IsSha256Hex(Text(value))); }
std::int64_t Integer(const Value& value, std::int64_t minimum = 0) {
    Require(value.IsInt()); const auto number = std::get<std::int64_t>(value.data);
    Require(number >= minimum); return number;
}
Object Decode(std::string_view bytes) { return Obj(core::json::Parse(bytes)); }
std::string Digest(const Value& value) { return core::Sha256Hex(core::json::WriteCanonical(value)); }

// Slot IDs are assigned by protocol position; capture/2 refs never accept a caller-supplied ID.
Object Slots(const Object& host, std::vector<Object>& refs) {
    Closed(host, {"protocol", "receipt", "request", "environment", "environment_binding", "scalar_exports", "rgb_exports"});
    Require(Text(At(host, "protocol")) == kProtocol);
    Require(At(host, "environment").IsNull() && At(host, "environment_binding").IsNull());
    std::map<std::string, std::int64_t> sizes;
    const auto slot = [&](const Value& value, std::string id, std::string kind) {
        Object ref = Obj(value); Closed(ref, {"kind", "sha256", "size_bytes"});
        Require(Text(At(ref, "kind")) == kind); Hash(At(ref, "sha256"));
        const auto size = Integer(At(ref, "size_bytes")); const auto& sha = Text(At(ref, "sha256"));
        const auto [found, inserted] = sizes.emplace(sha, size);
        Require(inserted || found->second == size);
        ref["record_id"] = std::move(id); refs.push_back(ref); return ref;
    };
    Object result{{"environment", nullptr}, {"environment_binding", nullptr}};
    result["receipt"] = slot(At(host, "receipt"), "receipt", "snapshot_receipt");
    result["request"] = slot(At(host, "request"), "request", "snapshot_request");
    for (const auto role : {"scalar", "rgb"}) {
        const std::string field = std::string(role) + "_exports";
        const auto& rounds = Arr(At(host, field)); Require(rounds.size() == 2);
        Array values;
        for (std::size_t i = 0; i < rounds.size(); ++i) {
            values.push_back(slot(rounds[i], "r" + std::to_string(i + 1) + "-" + role,
                                  "snapshot_" + std::string(role) + "_export"));
        }
        result[field] = std::move(values);
    }
    return result;
}

void Timestamp(const Value& value) {
    const auto& stamp = Text(value);
    static const std::regex pattern(R"(([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})(\.[0-9]{1,6})?(Z|\+00:00))");
    std::smatch match; Require(std::regex_match(stamp, match, pattern));
    const auto number = [&](int index) { return std::stoi(match[index].str()); };
    Require(number(1) >= 1 && number(4) <= 23 && number(5) <= 59 && number(6) <= 59);
    const std::chrono::year_month_day date{std::chrono::year(number(1)),
                                          std::chrono::month(static_cast<unsigned>(number(2))),
                                          std::chrono::day(static_cast<unsigned>(number(3)))};
    Require(date.ok());
}

Object Admission(std::string_view bytes, const Object& slots, std::string_view capture) {
    Object document = Decode(bytes);
    Closed(document, {"schema", "protocol", "capture_id", "producer_policy", "artifacts", "provenance", "validation", "admitted_at"});
    Require(Text(At(document, "schema")) == "uzpainter/parity/snapshot-capture-admission/1" &&
            Text(At(document, "protocol")) == kProtocol && Text(At(document, "capture_id")) == capture);
    Require(Same(At(document, "artifacts"), slots));
    Require(Same(At(document, "producer_policy"), Object{{"sha256", kPolicySha}, {"revision", 1}}));
    Require(Same(At(document, "provenance"), Object{{"basis", "owner_local_submission"}, {"execution_attestation", "none"}}));
    const auto& validation = Obj(At(document, "validation"));
    Closed(validation, {"validator_revision", "validator_code_sha256", "validator_binary_sha256", "signature_sha256",
                         "capture_context_sha256", "scalar_raster_sha256"});
    Require(Text(At(validation, "validator_revision")) == kValidator);
    for (const auto& [key, value] : validation) if (key != "validator_revision") Hash(value);
    Timestamp(At(document, "admitted_at"));
    return document;
}

Object Policy(std::string_view retained) {
    const std::string_view compiled(reinterpret_cast<const char*>(kPolicyBytes), sizeof(kPolicyBytes));
    Require(core::Sha256Hex(compiled) == kPolicySha && retained == compiled, "H_POLICY_INVALID");
    Object policy = Decode(retained); Closed(policy, {"schema", "revision", "producers"});
    Require(Text(At(policy, "schema")) == "uzpainter/parity/snapshot-producer-policy/1" &&
            Integer(At(policy, "revision"), 1) == 1, "H_POLICY_INVALID");
    const auto& producers = Arr(At(policy, "producers")); Require(!producers.empty(), "H_POLICY_INVALID");
    std::set<std::pair<std::string, std::string>> pairs;
    for (const auto& value : producers) {
        const auto& row = Obj(value); Closed(row, {"protocol", "source_revision", "bridge_sha256", "painter_side_sha256"});
        Require(Text(At(row, "protocol")) == kProtocol, "H_POLICY_INVALID");
        const auto& revision = Text(At(row, "source_revision"));
        Require(revision.size() == 40 && revision.find_first_not_of("0123456789abcdef") == std::string::npos, "H_POLICY_INVALID");
        Hash(At(row, "bridge_sha256")); Hash(At(row, "painter_side_sha256"));
        Require(pairs.emplace(Text(At(row, "bridge_sha256")), Text(At(row, "painter_side_sha256"))).second, "H_POLICY_INVALID");
    }
    return policy;
}

Object Producer(std::string_view receiptBytes, const Object& policy) {
    const Object receipt = Decode(receiptBytes); const Object recorder = Obj(At(receipt, "recorder"));
    Closed(recorder, {"bridge_sha256", "painter_side_sha256"});
    Hash(At(recorder, "bridge_sha256")); Hash(At(recorder, "painter_side_sha256"));
    bool approved = false;
    for (const auto& value : Arr(At(policy, "producers"))) {
        const auto& row = Obj(value);
        approved = approved || (Same(At(row, "bridge_sha256"), At(recorder, "bridge_sha256")) &&
                                Same(At(row, "painter_side_sha256"), At(recorder, "painter_side_sha256")));
    }
    Require(approved, "H_PRODUCER_UNAPPROVED"); return recorder;
}

ImportRefusal Refusal(std::string_view code) { return {std::string(kHostCaptureInvalid), std::string(code)}; }

}  // namespace

AdmittedHostCapture::AdmittedHostCapture(ValidatedHostArtifacts artifacts, Object identity,
                                         std::map<std::string, std::string, std::less<>> bytes)
    : artifacts_(std::move(artifacts)), identity_(std::move(identity)), bytes_(std::move(bytes)) {}

std::optional<std::string> AdmittedHostCapture::Bytes(std::string_view sha256) const {
    const auto found = bytes_.find(sha256);
    return found == bytes_.end() ? std::nullopt : std::optional<std::string>(found->second);
}

std::expected<AdmittedHostCapture, ImportRefusal> AdmittedHostCapture::Admit(const Object& host,
                                                                         const OracleStoreReader& store) {
    try {
        std::vector<Object> refs;
        const Object slots = Slots(host, refs);
        const std::string capture = Digest(Object{{"protocol", kProtocol}, {"artifacts", slots}});
        const auto admissionBytes = store.SnapshotAdmissionBytes(capture, kPolicySha);
        Require(admissionBytes.has_value(), "H_ADMISSION_UNAVAILABLE");
        const Object admission = Admission(*admissionBytes, slots, capture);
        const auto policyBytes = store.SnapshotPolicyBytes(kPolicySha);
        Require(policyBytes.has_value(), "H_POLICY_UNAVAILABLE");
        const Object policy = Policy(*policyBytes);
        std::map<std::string, std::string, std::less<>> owned;
        Object producer;
        for (std::size_t index = 0; index < refs.size(); ++index) {
            const auto& ref = refs[index]; const auto& sha = Text(At(ref, "sha256"));
            auto bytes = store.Blob(sha, Integer(At(ref, "size_bytes")));
            Require(bytes.has_value(), "H_ARTIFACT_UNAVAILABLE");
            if (index == 0) producer = Producer(*bytes, policy);
            owned.insert_or_assign(sha, std::move(*bytes));
        }
        const auto validated = ValidateHostCaptureArtifacts(host, [&](std::string_view sha) -> std::optional<std::string> {
            const auto found = owned.find(sha);
            return found == owned.end() ? std::nullopt : std::optional<std::string>(found->second);
        });
        if (!validated) return Unexpected(ImportRefusal{validated.error().reason, "H_ARTIFACT_INVALID"});
        const Object native = validated->Identity(); const auto& validation = Obj(At(admission, "validation"));
        Require(Same(At(validation, "signature_sha256"), At(native, "signature_sha256")) &&
                Same(At(validation, "capture_context_sha256"), At(native, "capture_context_sha256")) &&
                Same(At(validation, "scalar_raster_sha256"), At(native, "raster_sha256")), "H_VALIDATION_MISMATCH");
        const auto finalAdmission = store.SnapshotAdmissionBytes(capture, kPolicySha);
        const auto finalPolicy = store.SnapshotPolicyBytes(kPolicySha);
        Require(finalAdmission == admissionBytes && finalPolicy == policyBytes, "H_ADMISSION_CHANGED");
        return AdmittedHostCapture(*validated,
            Object{{"capture_id", capture}, {"admission_sha256", core::Sha256Hex(*admissionBytes)},
                   {"producer_policy", At(admission, "producer_policy")}, {"producer", std::move(producer)},
                   {"artifacts_identity", native}}, std::move(owned));
    } catch (const HostAdmissionRefused& error) { return Unexpected(Refusal(error.code)); }
    catch (const std::exception&) { return Unexpected(Refusal("H_ADMISSION_INVALID")); }
}

std::expected<AdmittedHostCapture, ImportRefusal> AdmitHostCapture(const Object& host, const OracleStoreReader& store) {
    return AdmittedHostCapture::Admit(host, store);
}

}  // namespace uzp::procedural
