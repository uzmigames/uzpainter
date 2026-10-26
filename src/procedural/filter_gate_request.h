#pragma once

#include <cstdint>
#include <expected>
#include <string>
#include <string_view>

#include "procedural/filter_observation_import_v2.h"
#include "uzp_core/manifest/json.h"
#include "uzp_core/operation/operation.h"

namespace uzp::procedural {

/// Closed command payload. Parsing proves structure only; the H/F admission gates prove evidence.
/// Its typed hash and original revision give replay a stable request independent of mapping.
class ParsedFilterImportRequest {
public:
    [[nodiscard]] std::int64_t ExpectedBaseRevision() const { return expected_base_revision_; }
    [[nodiscard]] const core::json::Object& HostCapture() const { return host_; }
    [[nodiscard]] const core::json::Object& ManifestRef() const { return manifest_; }
    [[nodiscard]] const std::string& PayloadSha256() const { return payload_sha256_; }
    [[nodiscard]] core::MutationRequest MutationRequestFor(std::string_view project_uuid) const;

private:
    ParsedFilterImportRequest() = default;
    friend std::expected<ParsedFilterImportRequest, ImportRefusal> ParseFilterImportRequest(std::string_view);
    std::int64_t expected_base_revision_ = 0;
    core::json::Object host_;
    core::json::Object manifest_;
    std::string payload_sha256_;
};

/// Strict JSON: duplicate/unknown keys, non-int revisions/sizes and unsupported H environments
/// refuse. No private values or caller text appear in the fixed refusal detail.
std::expected<ParsedFilterImportRequest, ImportRefusal> ParseFilterImportRequest(std::string_view bytes);

}  // namespace uzp::procedural
