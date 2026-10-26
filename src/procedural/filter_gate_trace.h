#pragma once

// C3: the complete admitted F trace, context census and per-round hashes. No constructor or
// caller-authored trace grants this capability; the factory joins C1 and C2 before checking it.

#include <expected>
#include <optional>
#include <string>

#include "procedural/filter_gate_admission.h"
#include "uzp_core/types/ids.h"

namespace uzp::procedural {

class CheckedSettingsPanels;

// Pure structural check of one frame, used by C2 for its actual before/after readbacks. This
// checks the closed leaves and selectors only, not the census, full lifecycle or admission.
std::optional<ImportRefusal> ValidateFilterContextFrame(const core::json::Object& frame);

class ValidatedFilterTrace {
public:
    [[nodiscard]] const std::string& OriginalRecordSha256() const { return original_record_sha256_; }
    [[nodiscard]] const core::json::Object& AdmissionIdentity() const { return admission_identity_; }
    [[nodiscard]] const core::json::Array& Contexts() const { return contexts_; }
    [[nodiscard]] core::Id InitialPaintUid() const { return initial_paint_uid_; }
    // Exactly two objects: condition and the four hashes defined in section 11 (F9).
    [[nodiscard]] const core::json::Array& Rounds() const { return rounds_; }

private:
    ValidatedFilterTrace() = default;
    friend std::expected<ValidatedFilterTrace, ImportRefusal> ValidateFilterTrace(
        const AdmittedFilterCapture&, const CheckedSettingsPanels&);
    std::string original_record_sha256_;
    core::json::Object admission_identity_;
    core::json::Array contexts_;
    core::Id initial_paint_uid_ = core::kNoId;
    core::json::Array rounds_;
};

std::expected<ValidatedFilterTrace, ImportRefusal> ValidateFilterTrace(
    const AdmittedFilterCapture& capture, const CheckedSettingsPanels& panels);

}  // namespace uzp::procedural
