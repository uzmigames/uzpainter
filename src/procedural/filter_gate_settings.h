#pragma once

#include "procedural/filter_gate_admission.h"

namespace uzp::procedural {

class ValidatedFilterTrace;
class ValidatedFilterSettings;

// Pure bounded decoder check; does not admit an image or construct a settings
// token.
std::optional<ImportRefusal> ValidateFilterSettingsImage(std::string_view bytes);

// Slot/panel/image checks only. Full lifecycle validation belongs to the trace
// gate.
class CheckedSettingsPanels {
  public:
    const core::json::Object &StrippedRecord() const { return stripped_record_; }
    const core::json::Array &Panels() const { return panels_; }
    const core::json::Object &AdmissionIdentity() const { return admission_identity_; }
    const std::string &OriginalRecordSha256() const { return original_record_sha256_; }

  private:
    CheckedSettingsPanels() = default;
    friend std::expected<CheckedSettingsPanels, ImportRefusal>
    CheckFilterSettingsPanels(const AdmittedFilterCapture &);
    core::json::Object stripped_record_;
    core::json::Array panels_;
    core::json::Object admission_identity_;
    std::string original_record_sha256_;
};

class ValidatedFilterSettings {
  public:
    const core::json::Object &AdmissionIdentity() const { return admission_identity_; }
    const std::string &OriginalRecordSha256() const { return original_record_sha256_; }
    std::string_view TangentSpace() const { return "PerVertex"; }
    std::string_view Workflow() const { return "Default"; }
    std::int64_t EffectiveCmPerUnit() const { return 1; }
    std::string_view ProvenanceBasis() const { return "unitless-obj-internal-centimetres-v1"; }

  private:
    ValidatedFilterSettings() = default;
    friend std::expected<ValidatedFilterSettings, ImportRefusal>
    DeriveFilterSettings(const AdmittedFilterCapture &, const CheckedSettingsPanels &,
                         const ValidatedFilterTrace &);
    core::json::Object admission_identity_;
    std::string original_record_sha256_;
};

std::expected<CheckedSettingsPanels, ImportRefusal> CheckFilterSettingsPanels(const AdmittedFilterCapture &);
std::expected<ValidatedFilterSettings, ImportRefusal> DeriveFilterSettings(const AdmittedFilterCapture &,
                                                                           const CheckedSettingsPanels &,
                                                                           const ValidatedFilterTrace &);

} // namespace uzp::procedural
