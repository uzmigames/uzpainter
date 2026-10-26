#include "procedural/filter_gate_request.h"

#include <initializer_list>
#include <stdexcept>

#include "uzp_core/manifest/sha256.h"

namespace uzp::procedural {
namespace {
using namespace core::json;

bool Closed(const Object& value, std::initializer_list<std::string_view> keys) {
    if (value.size() != keys.size()) return false;
    for (const auto key : keys)
        if (!value.contains(key)) return false;
    return true;
}

bool Text(const Value& value, std::string_view expected) {
    return value.IsString() && std::get<std::string>(value.data) == expected;
}

bool NonnegativeInt(const Value& value) {
    return value.IsInt() && std::get<std::int64_t>(value.data) >= 0;
}

bool Ref(const Value& value, std::string_view kind) {
    if (!value.IsObject()) return false;
    const auto& ref = std::get<Object>(value.data);
    return Closed(ref, {"kind", "sha256", "size_bytes"}) && Text(ref.at("kind"), kind) &&
           ref.at("sha256").IsString() && core::IsSha256Hex(std::get<std::string>(ref.at("sha256").data)) &&
           NonnegativeInt(ref.at("size_bytes"));
}

bool Pair(const Value& value, std::string_view kind) {
    if (!value.IsArray()) return false;
    const auto& refs = std::get<Array>(value.data);
    return refs.size() == 2 && Ref(refs[0], kind) && Ref(refs[1], kind);
}

bool Host(const Value& value) {
    if (!value.IsObject()) return false;
    const auto& host = std::get<Object>(value.data);
    return Closed(host, {"protocol", "receipt", "request", "environment", "environment_binding", "scalar_exports",
                         "rgb_exports"}) &&
           Text(host.at("protocol"), "paired-scalar-rgb") && Ref(host.at("receipt"), "snapshot_receipt") &&
           Ref(host.at("request"), "snapshot_request") && host.at("environment").IsNull() &&
           host.at("environment_binding").IsNull() && Pair(host.at("scalar_exports"), "snapshot_scalar_export") &&
           Pair(host.at("rgb_exports"), "snapshot_rgb_export");
}

std::expected<ParsedFilterImportRequest, ImportRefusal> Invalid() {
    return std::expected<ParsedFilterImportRequest, ImportRefusal>(
        std::unexpect, ImportRefusal{"FILTER_IMPORT_REQUEST_INVALID", "FILTER_IMPORT_REQUEST_SCHEMA"});
}
}  // namespace

std::expected<ParsedFilterImportRequest, ImportRefusal> ParseFilterImportRequest(std::string_view bytes) {
    try {
        const auto parsed = core::json::Parse(bytes);
        if (!parsed.IsObject()) return Invalid();
        const auto& payload = std::get<core::json::Object>(parsed.data);
        if (!Closed(payload, {"schema", "manifest", "host", "expected_base_revision"}) ||
            !Text(payload.at("schema"), "uzpainter/filter-observation-v2-import/1") ||
            !Ref(payload.at("manifest"), "filter_manifest") || !Host(payload.at("host")) ||
            !NonnegativeInt(payload.at("expected_base_revision")))
            return Invalid();
        ParsedFilterImportRequest result;
        result.expected_base_revision_ = std::get<std::int64_t>(payload.at("expected_base_revision").data);
        result.manifest_ = std::get<core::json::Object>(payload.at("manifest").data);
        result.host_ = std::get<core::json::Object>(payload.at("host").data);
        result.payload_sha256_ = core::Sha256Hex(core::json::WriteCanonical(parsed));
        return result;
    } catch (const std::exception&) {
        return Invalid();
    }
}

core::MutationRequest ParsedFilterImportRequest::MutationRequestFor(std::string_view project_uuid) const {
    core::MutationRequest request;
    request.tool = "filter-observation-commit-v2";
    request.arguments = {{"payload_sha256", payload_sha256_},
                         {"project_uuid", project_uuid},
                         {"expected_base_revision", expected_base_revision_}};
    request.idempotency_key = request.tool + ":" + core::Sha256Hex(core::json::WriteCanonical(request.arguments));
    request.expected_revision = expected_base_revision_;
    return request;
}

}  // namespace uzp::procedural
