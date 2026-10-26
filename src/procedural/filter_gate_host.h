#pragma once

#include <expected>
#include <map>
#include <optional>
#include <string>
#include <string_view>

#include "procedural/filter_gate_admission.h"

namespace uzp::procedural {

/// An H capture admitted by the store's snapshot admission and the compiled producer policy.
/// Owns all evidence and native validation; neither a byte callback nor a report constructs it.
class AdmittedHostCapture {
public:
    [[nodiscard]] const ValidatedHostArtifacts& Artifacts() const { return artifacts_; }
    [[nodiscard]] const core::json::Object& HostCapture() const { return artifacts_.HostCapture(); }
    [[nodiscard]] const core::json::Object& Identity() const { return identity_; }
    /// Only the six admitted slots are available, including repeated hashes.
    [[nodiscard]] std::optional<std::string> Bytes(std::string_view sha256) const;

private:
    AdmittedHostCapture(ValidatedHostArtifacts artifacts, core::json::Object identity,
                        std::map<std::string, std::string, std::less<>> bytes);
    static std::expected<AdmittedHostCapture, ImportRefusal> Admit(const core::json::Object& host,
                                                                 const OracleStoreReader& store);
    friend std::expected<AdmittedHostCapture, ImportRefusal> AdmitHostCapture(const core::json::Object&,
                                                                           const OracleStoreReader&);
    ValidatedHostArtifacts artifacts_;
    core::json::Object identity_;
    std::map<std::string, std::string, std::less<>> bytes_;
};

/// No public policy override: the retained policy must match the compiled v1 bytes and hash.
/// Admission and policy are checked before any blob, then reread after native validation.
std::expected<AdmittedHostCapture, ImportRefusal> AdmitHostCapture(const core::json::Object& host,
                                                                 const OracleStoreReader& store);

}  // namespace uzp::procedural
